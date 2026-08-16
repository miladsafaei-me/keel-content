"""Deterministic verification + rendering of external further-reading links.

A blog article may link EXTERNAL further-reading sources (any genuinely
authoritative, high-value page — regulators, official docs, educational
references, reputable publications, market/statistical bodies, and even a
competitor's genuinely educational page) as a single "Sources & Further Reading"
list at the *end* of the post. This module is the deterministic gate that turns
an agent's *proposed* sources into the *published* list. It runs a **tiered**
trust model rather than a single closed allowlist, so the outbound circle is not
artificially narrowed to a handful of domains:

1. **Domain tiering** —
   - **Blocked** (:data:`BLOCKED_DOMAINS`): url-shorteners and known
     junk/content-farm hosts are dropped unconditionally.
   - **Trusted fast-lane** (:data:`AUTHORITATIVE_DOMAINS`): auto-pass on the host
     alone — no per-source judgement needed.
   - **Everything else**: NOT auto-dropped. It survives the deterministic layer
     only if the LLM ``link-relevance-gate`` has vetted it (the source carries
     ``"vetted": true``). Without that marker an off-fast-lane host is dropped, so
     a raw (un-gated) author bundle degrades safely to the trusted set. The gate —
     not this module — is the authority/value judge for the long tail; here we
     only trust its verdict. **Authors must NOT self-stamp ``vetted``**; only the
     gate sets it, which is why an un-gated import stays conservative.
   - **Wikipedia cap**: at most :data:`WIKIPEDIA_MAX_PER_ARTICLE` Wikipedia links
     ship per article (first kept wins), and the second only alongside at least
     one non-Wikipedia source — domain diversity is part of the quality bar, not
     just per-link authority.
2. **Live 200 check** — HTTP-verify each surviving URL returns **200** (following
   redirects). A dead, moved, or unreachable link is dropped, so every link that
   ships answered 200 at least once (trusted bot-blockers excepted — see
   :data:`VERIFY_EXEMPT_DOMAINS`).
3. **Render** — emit the survivors as a Markdown ``## Sources & Further Reading
   {#sources}`` list of *follow* links and append it to the article body. The
   append is idempotent: a re-run strips the previously-appended section first.

The liveness + tiering here is deterministic (pure host matching plus real HTTP);
the authority/value judgement for off-fast-lane domains lives in the LLM gate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Trusted fast-lane domains — a blog post may link these on the host alone, no
# per-source vetting. This is NOT the whole universe of allowed sources (any
# genuinely authoritative, high-value page can ship once the relevance gate marks
# it ``vetted``); it is the curated set we trust without a case-by-case judgement.
# Extend deliberately. Large, genuinely valuable platform / tooling / protocol
# reference sites ARE welcome here (charting & algo platforms like NinjaTrader,
# TradingView, cTrader, QuantConnect; DeFi protocol docs like Uniswap, Aave,
# MakerDAO) — for their educational / documentation pages. The per-page rules
# still bite regardless of domain: the author brief + relevance gate drop any
# sign-up / pricing / product / download / bare-homepage / affiliate URL, so a
# fast-laned platform is a *reference*, never a funnel.
#
# What stays OFF the fast lane, on purpose:
#   * Our own IB / affiliate / exchange PARTNERS (any market). Blog posts route the
#     reader to OUR landing, where the affiliate link lives — never straight to the
#     partner — so IB attribution + market integrity (BUSINESS-MAP.md §9) hold. A
#     competitor's page is admitted only through the vetted path, never the fast lane.
#   * Centralized crypto exchanges we monetize through (Binance, Bybit, BingX, CoinEx,
#     etc.) — same attribution reason. DeFi *protocols* (non-custodial, not a partner)
#     are fine; centralized exchanges are not.
#   * Offshore regulators with weak supervision reputations (VFSC, IFSC Belize, FSA
#     Seychelles/SVG).
#   * Hard-paywalled press (Bloomberg, FT, WSJ, The Economist — a paywalled page has
#     no reader value; a specific free article there can still earn a per-page ``vetted``).
#
# NOTE: a domain being trusted does not guarantee it answers 200 to a
# datacenter request — several majors (investopedia.com, sec.gov, cme group,
# mql5.com, imf.org) bot-block and would be dropped by the live-200 check. They
# stay on the list because they are legitimately authoritative and may answer
# 200 from other networks; the agent brief steers writers toward the reliably
# fetchable subset (see :data:`VERIFY_EXEMPT_DOMAINS`).
AUTHORITATIVE_DOMAINS: frozenset[str] = frozenset(
    {
        # ---- Education / reference
        "investopedia.com",
        "babypips.com",
        "corporatefinanceinstitute.com",
        "wikipedia.org",
        "britannica.com",
        "xe.com",  # currency reference / historical FX rates
        "khanacademy.org",  # finance & capital-markets course pages
        "cfainstitute.org",
        "garp.org",  # GARP — FRM / risk-management body of knowledge
        "optionseducation.org",  # OIC — Options Industry Council investor education
        "thebalancemoney.com",  # Dotdash Meredith personal-finance reference
        "morningstar.com",  # investing research + education
        "stockcharts.com",  # ChartSchool — technical-analysis reference
        "nerdwallet.com",  # personal-finance guides & comparison education
        "mymoney.gov",
        # ---- US regulators / federal bodies
        "sec.gov",
        "investor.gov",  # SEC's investor-education site (readable bulletins/alerts/glossary)
        "cftc.gov",
        "nfa.futures.org",
        "finra.org",
        "sipc.org",
        "federalreserve.gov",
        "treasury.gov",
        "treasurydirect.gov",  # auctions, yields, savings bonds
        "consumerfinance.gov",
        "fdic.gov",
        "irs.gov",  # trader-tax topics (wash sales, 1256 contracts, capital gains)
        "fincen.gov",
        "ftc.gov",  # consumer fraud alerts
        "ic3.gov",  # FBI Internet Crime Complaint Center — trading/crypto fraud reports
        "fbi.gov",
        "justice.gov",  # fraud prosecutions / press releases
        "nasaa.org",  # North American state/provincial securities administrators
        "msrb.org",
        "federalregister.gov",
        "congress.gov",
        "gao.gov",
        "cbo.gov",
        # ---- International regulators / supervisory bodies
        "fca.org.uk",
        "fscs.org.uk",  # UK deposit/investment compensation scheme
        "financial-ombudsman.org.uk",
        "esma.europa.eu",
        "eba.europa.eu",
        "ec.europa.eu",
        "cysec.gov.cy",  # regulates the bulk of retail CFD/FX brokers
        "bafin.de",
        "amf-france.org",
        "consob.it",
        "cnmv.es",
        "afm.nl",
        "fsma.be",  # publishes the well-known binary/CFD warning lists
        "cssf.lu",
        "mfsa.mt",  # Malta — home regulator of many retail brokers
        "cmvm.pt",
        "hcmc.gr",
        "knf.gov.pl",
        "cnb.cz",
        "mnb.hu",
        "fi.se",  # Sweden Finansinspektionen
        "finanstilsynet.no",
        "finanstilsynet.dk",
        "finanssivalvonta.fi",  # Finland FIN-FSA
        "finma.ch",
        "asic.gov.au",
        "moneysmart.gov.au",  # ASIC's investor-education site
        "fma.govt.nz",
        "ciro.ca",
        "osc.ca",
        "securities-administrators.ca",  # CSA — national investor alerts
        "mas.gov.sg",
        "fsa.go.jp",  # Japan FSA
        "sfc.hk",
        "hkma.gov.hk",
        "fsc.go.kr",  # Korea Financial Services Commission
        "sc.com.my",  # Malaysia Securities Commission
        "sec.or.th",
        "ojk.go.id",  # Indonesia OJK
        "sec.gov.ph",
        "sebi.gov.in",
        "isa.gov.il",  # Israel Securities Authority — led the binary-options ban
        "cma.org.sa",  # Saudi Capital Market Authority
        "sca.gov.ae",
        "dfsa.ae",
        "fsca.co.za",
        "cnbv.gob.mx",
        "cvm.gov.br",
        "cmfchile.cl",
        "centralbank.ie",
        # Additional national financial-market regulators & central banks acting as
        # market supervisors (cited in broker-regulation / country-guide content).
        # Weak-supervision offshore regulators (Seychelles, Anguilla, Antigua, etc.)
        # stay OFF by policy — see the header notes on AUTHORITATIVE_DOMAINS.
        "fma.gv.at",  # Austria — Financial Market Authority (FMA)
        "fsc.bg",  # Bulgaria — Financial Supervision Commission
        "hanfa.hr",  # Croatia — Financial Services Supervisory Agency (HANFA)
        "dfsa.dk",  # Denmark — Danish FSA (alias of finanstilsynet.dk)
        "fi.ee",  # Estonia — Finantsinspektsioon (Financial Supervision Authority)
        "cb.is",  # Central Bank of Iceland
        "jsc.gov.jo",  # Jordan Securities Commission
        "cma.or.ke",  # Kenya — Capital Markets Authority
        "cmb.gov.tr",  # Turkey — Capital Markets Board (CMB)
        "bcra.gob.ar",  # Central Bank of Argentina (BCRA)
        "bma.bm",  # Bermuda Monetary Authority (BMA)
        "asfi.gob.bo",  # Bolivia — Financial System Supervisory Authority (ASFI)
        "bch.hn",  # Central Bank of Honduras
        "fscjamaica.org",  # Jamaica — Financial Services Commission
        "secp.gov.pk",  # Pakistan — Securities & Exchange Commission (SECP)
        "bcu.gub.uy",  # Central Bank of Uruguay (BCU)
        "cbr.ru",  # Central Bank of Russia (CBR)
        "iosco.org",
        "fatf-gafi.org",  # AML/CFT standards body
        # ---- Central banks & Federal Reserve system
        "newyorkfed.org",  # NY Fed — FX committee, reference rates
        "stlouisfed.org",  # includes fred.stlouisfed.org (FRED data)
        "chicagofed.org",
        "frbsf.org",  # San Francisco Fed
        "atlantafed.org",
        "clevelandfed.org",
        "dallasfed.org",
        "kansascityfed.org",
        "minneapolisfed.org",
        "philadelphiafed.org",
        "richmondfed.org",
        "bostonfed.org",
        "ecb.europa.eu",
        "bankofengland.co.uk",
        "bundesbank.de",
        "banque-france.fr",
        "bancaditalia.it",
        "bde.es",  # Bank of Spain
        "dnb.nl",
        "nbb.be",
        "oenb.at",
        "bportugal.pt",
        "riksbank.se",
        "norges-bank.no",
        "nationalbanken.dk",
        "suomenpankki.fi",
        "boj.or.jp",
        "bankofcanada.ca",
        "rba.gov.au",
        "rbnz.govt.nz",
        "snb.ch",
        "rbi.org.in",
        "pboc.gov.cn",
        "bok.or.kr",
        "bcb.gov.br",
        "banxico.org.mx",
        "tcmb.gov.tr",
        "sama.gov.sa",
        # ---- Statistical / macro / multilateral
        "bis.org",
        "imf.org",
        "worldbank.org",
        "oecd.org",
        "wto.org",
        "ilo.org",
        "adb.org",  # Asian Development Bank
        "ebrd.com",
        "bls.gov",
        "bea.gov",
        "census.gov",
        "tradingeconomics.com",  # economic indicators, calendars, macro data
        "eia.gov",  # US energy data — WTI/Brent, natural gas
        "iea.org",  # International Energy Agency
        "opec.org",
        "ons.gov.uk",
        "destatis.de",
        "insee.fr",
        "istat.it",
        "ine.es",
        "statcan.gc.ca",
        "abs.gov.au",
        "stats.govt.nz",
        "stat.go.jp",
        "stats.gov.cn",
        # ---- Exchanges / market operators / market infrastructure
        "cmegroup.com",
        "nasdaq.com",
        "nyse.com",
        "cboe.com",
        "lseg.com",
        "ice.com",
        "eurex.com",
        "euronext.com",
        "deutsche-boerse.com",
        "six-group.com",  # SIX Swiss Exchange
        "asx.com.au",
        "jpx.co.jp",
        "hkex.com.hk",
        "sgx.com",
        "krx.co.kr",
        "tmx.com",  # Toronto
        "b3.com.br",
        "nseindia.com",
        "bseindia.com",
        "lme.com",  # London Metal Exchange
        "dtcc.com",
        "theocc.com",  # Options Clearing Corporation
        "swift.com",
        # ---- Index providers / rating agencies
        "spglobal.com",  # S&P Dow Jones Indices, S&P Ratings research
        "msci.com",
        "ftserussell.com",
        "moodys.com",
        "fitchratings.com",
        # ---- Industry bodies / commodity market references
        "isda.org",
        "fia.org",  # Futures Industry Association
        "sifma.org",
        "ici.org",  # Investment Company Institute
        "aima.org",  # Alternative Investment Management Association
        "iif.com",  # Institute of International Finance
        "world-exchanges.org",  # World Federation of Exchanges
        "gold.org",  # World Gold Council research
        "lbma.org.uk",  # London bullion benchmarks
        "silverinstitute.org",
        # ---- Consumer protection / fraud & scam references
        "scamwatch.gov.au",
        "actionfraud.police.uk",
        "bbb.org",
        "europol.europa.eu",
        "interpol.int",
        # ---- Trading platforms / charting / algo & quant tooling docs
        "metaquotes.net",
        "metatrader4.com",
        "metatrader5.com",
        "mql4.com",  # docs.mql4.com — official MQL4 language reference (readable docs)
        "mql5.com",
        "tradingview.com",
        "ctrader.com",  # help.ctrader.com — official cTrader docs
        "ninjatrader.com",  # NinjaScript strategy/indicator docs
        "multicharts.com",
        "sierrachart.com",
        "quantconnect.com",  # cloud algo platform + LEAN engine docs
        "backtrader.com",  # open-source Python backtesting framework docs
        "interactivebrokers.com",  # IBKR — TWS/API developer docs
        "tradestation.com",
        "ig.com",  # IG Academy — trading education (non-partner)
        "telegram.org",  # core.telegram.org — official Bot API / platform docs
        "developer.chrome.com",  # extension platform docs (subdomain-scoped on purpose)
        "developer.mozilla.org",  # MDN
        "developer.android.com",
        "developer.apple.com",
        "python.org",  # official language docs for algo-trading content
        "numpy.org",
        "pandas.pydata.org",
        "scipy.org",
        "scikit-learn.org",
        "statsmodels.org",
        "matplotlib.org",
        "plotly.com",  # open-source charting library docs
        "jupyter.org",
        "r-project.org",
        "quantlib.org",
        "ta-lib.org",  # canonical technical-analysis library docs
        "nist.gov",  # cryptography / security standards (API keys, 2FA)
        # ---- Crypto protocols / open data / research / journalism
        "bitcoin.org",
        "bitcoincore.org",
        "lightning.network",
        "ethereum.org",
        "litecoin.org",
        "xrpl.org",  # XRP Ledger docs
        "cardano.org",
        "polkadot.network",
        "solana.com",
        "chain.link",  # Chainlink oracle docs
        "etherscan.io",
        "blockchair.com",
        "mempool.space",
        "coinmarketcap.com",
        "coingecko.com",
        "defillama.com",  # open DeFi TVL/data reference
        "glassnode.com",
        "chainalysis.com",  # widely-cited crypto-crime research
        "coindesk.com",
        "theblock.co",
        "messari.io",
        "decrypt.co",
        "blockworks.co",
        "bitcoinmagazine.com",
        "dune.com",  # open on-chain analytics
        # ---- DeFi protocols & crypto platform docs
        # (educational/docs pages; centralized exchanges we monetize through stay
        # off — see the header notes on AUTHORITATIVE_DOMAINS above)
        "uniswap.org",
        "aave.com",
        "makerdao.com",
        "compound.finance",
        "curve.fi",
        "lido.fi",
        "pancakeswap.finance",
        "dydx.exchange",  # perpetuals DEX docs
        "1inch.io",
        "synthetix.io",
        "balancer.fi",
        "sushi.com",
        "thegraph.com",  # open indexing protocol docs
        "ipfs.tech",
        "consensys.io",  # Ethereum tooling docs/research
        "alchemy.com",  # web3 developer platform — node/API docs & education
        "ledger.com",  # Ledger Academy — wallet-security education
        "trezor.io",
        # ---- Financial journalism (non-paywalled outlets only)
        # A hard-paywalled page has no reader value; Bloomberg/FT/WSJ/Economist stay
        # OFF this list and must earn a per-page ``vetted`` if ever proposed.
        "reuters.com",
        "apnews.com",
        "cnbc.com",
        "marketwatch.com",
        "benzinga.com",  # free markets news & analysis (Benzinga Pro is separate/paid)
        "investing.com",  # markets news + data portal (free)
        "bbc.com",
        "bbc.co.uk",
        "theguardian.com",
        "npr.org",
        "axios.com",
        "fortune.com",
        "forbes.com",  # business/finance journalism (free Forbes.com articles)
        "money.com",  # Money — personal-finance journalism
        "financemagnates.com",  # retail-trading / FX & fintech industry trade news
        "kitco.com",  # precious-metals news & charts
        # ---- Academic / research
        "nber.org",
        "ssrn.com",
        "arxiv.org",  # q-fin
        "repec.org",  # ideas.repec.org — open economics papers
        "cepr.org",
        "brookings.edu",
        "piie.com",  # Peterson Institute
        # ---- Payments / money transfer / currency-exchange services
        # (deposit/withdrawal-method and FX/remittance references; the per-page gate
        # still drops their sign-up / pricing / product URLs, so a fast-laned service
        # is a reference, never a funnel — same rule as every other domain here)
        "wise.com",  # Wise — multi-currency accounts, FX rates & transfer guides
        "paypal.com",  # payment rail — deposit/withdrawal method reference
        "riamoneytransfer.com",  # Ria — remittance / money-transfer reference
        "bestchange.com",  # e-currency / crypto exchange-rate aggregator
        # ---- Precious metals — bullion dealers & price data
        "goldprice.org",  # live gold/silver spot prices & historical charts
        "bullionvault.com",  # bullion market data / gold-investing education
        "moneymetals.com",  # precious-metals news & market analysis
    }
)

# Top-tier authoritative domains that blanket-block datacenter / bot traffic with
# 403/401/429 (Cloudflare/Akamai), serving 200 only to real human browsers. Their
# pages are live and high-value for readers, so the live-200 check must NOT drop
# them — a 403 here means "bot-blocked", not "dead". They are kept regardless of a
# block status; only a definitive dead status (see ``_DEAD_CODES``) drops them.
#
# Trade-off: because these domains return 403 to *every* automated client (ours and
# prod's alike — they even block our search crawler), we cannot machine-verify that
# a given URL on them is real. A wrong/typo'd URL would ship unflagged, so links to
# these domains rely on curation accuracy + the human draft review (a real browser
# is the verifier). Every domain here MUST also be in ``AUTHORITATIVE_DOMAINS``.
VERIFY_EXEMPT_DOMAINS: frozenset[str] = frozenset(
    {
        "investopedia.com",
        "babypips.com",
        "sec.gov",
        "cmegroup.com",
        "mql5.com",
        "imf.org",
    }
)

# Enforce the documented invariant at import: a bot-blocked exempt domain that is
# NOT also allowlisted would be dropped by ``domain_allowed`` before the exemption is
# ever consulted, silently defeating the exemption. Fail loudly on a future edit that
# adds one to VERIFY_EXEMPT_DOMAINS but forgets AUTHORITATIVE_DOMAINS.
assert VERIFY_EXEMPT_DOMAINS <= AUTHORITATIVE_DOMAINS, (
    "VERIFY_EXEMPT_DOMAINS must be a subset of AUTHORITATIVE_DOMAINS; missing: "
    f"{sorted(VERIFY_EXEMPT_DOMAINS - AUTHORITATIVE_DOMAINS)}"
)

# Hard denylist — dropped unconditionally, before the trusted / vetted tiers are
# consulted. These are hosts no further-reading link should ever point at: url
# shorteners (opaque redirects that hide the real destination) and known
# content-farm / AI-spam mills. Our own affiliate/IB/exchange partners are NOT
# listed here on purpose — a broker's genuinely educational page (e.g. official
# API docs) may still be linked; what is forbidden is the *affiliate/tracking*
# URL, which the author brief + relevance gate block by policy, not by host.
# (Market-integrity / attribution rules live in BUSINESS-MAP.md §3; this list is
# only the deterministic reader-safety floor.)
BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        # URL shorteners — opaque, unverifiable, and a spam/cloaking vector.
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "buff.ly",
        "is.gd",
        "cutt.ly",
        "rebrand.ly",
        "shorturl.at",
        "lnkd.in",
    }
)

# Per-article cap on Wikipedia links. Wikipedia is the agents' reflexive default
# (it carried ~70% of all outbound links before this cap existed), which
# concentrates the outbound profile onto one host and reads thin for E-E-A-T.
# Up to two Wikipedia links may ship per article, but the second one only
# alongside at least one non-Wikipedia source — an all-Wikipedia list is trimmed
# back to one. Extras beyond the cap are dropped deterministically (first kept
# wins) so domain diversity does not depend on prompt compliance alone.
WIKIPEDIA_DOMAIN = "wikipedia.org"
WIKIPEDIA_MAX_PER_ARTICLE = 2

# Definitive "the page is gone" statuses — these drop a link even on an exempt domain.
_DEAD_CODES: frozenset[int] = frozenset({404, 410})

_HTTP_TIMEOUT = (8, 12)  # (connect, read) seconds
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_REQUEST_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_SOURCES_HEADING = "Sources & Further Reading"
_SOURCES_ANCHOR = "sources"
_SOURCES_LEAD = (
    "Want to go deeper? These independent, authoritative sources shaped this "
    "guide — each one is worth reading in full:"
)
# Matches the section this module appends, so a re-run is idempotent.
_SOURCES_SECTION_RE = re.compile(
    r"\n*#{2,3}[ \t]+"
    + re.escape(_SOURCES_HEADING)
    + r"[ \t]*\{#"
    + re.escape(_SOURCES_ANCHOR)
    + r"\}.*\Z",
    re.IGNORECASE | re.DOTALL,
)

_ALLOWED_ROLES = ("citation", "further_reading")
# citation first, then further_reading — stable ordering within the rendered list.
_ROLE_ORDER = {"citation": 0, "further_reading": 1}


def domain_of(url: str) -> str:
    """Lower-cased registrable host of ``url`` with a leading ``www.`` stripped."""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_domain_root(url: str) -> bool:
    """True when ``url`` is a bare domain root / homepage (a banned link target).

    An external link must be *page-relevant* — it must point to the specific page
    that covers the exact point being made, not merely to a relevant organisation's
    front door. A homepage (empty path or ``/``, no query, no fragment) is authority
    without value: live and on-brand, but not reading material. This is the
    deterministic backstop for the ``link-relevance-gate`` prompt's "drop generic
    homepage" instruction — an LLM can still let one slip, so the mechanical gate
    drops it regardless of how trusted the domain is (even a fast-lane regulator
    homepage must be deep-linked or dropped).
    """
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    return p.path.rstrip("/") == "" and not p.query and not p.fragment


def _fast_lane_domains() -> frozenset[str]:
    """The trusted fast-lane: the shipped default set plus any host-supplied hosts.

    A host extends the default finance/reference allowlist with its own trusted
    domains via ``KEEL_CONTENT["external_domains"]`` (see ``keel_content.config``);
    it never has to fork this module's curated default.
    """
    from keel_content.config import external_domains

    extra = external_domains()
    return AUTHORITATIVE_DOMAINS | frozenset(extra) if extra else AUTHORITATIVE_DOMAINS


def domain_allowed(url: str) -> bool:
    """True when the URL's host is an allowlisted authoritative domain (or a subdomain)."""
    host = domain_of(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in _fast_lane_domains())


def domain_verify_exempt(url: str) -> bool:
    """True when the host is a top-tier domain that bot-blocks (kept despite 403)."""
    host = domain_of(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in VERIFY_EXEMPT_DOMAINS)


def domain_blocked(url: str) -> bool:
    """True when the URL's host is on the hard denylist (dropped unconditionally)."""
    host = domain_of(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


@dataclass
class SourceCheck:
    """Result of checking one proposed external source."""

    url: str
    anchor: str
    role: str
    ok: bool
    status: int | None = None
    reason: str = ""


@dataclass
class SourcesReport:
    """Outcome of verifying a bundle's proposed external sources."""

    verified: list[SourceCheck] = field(default_factory=list)
    dropped: list[SourceCheck] = field(default_factory=list)

    @property
    def exempt_kept(self) -> int:
        """Count of links kept on trust (verify-exempt domain that bot-blocked, no 200)."""
        return sum(1 for c in self.verified if (c.reason or "").startswith("kept:"))

    @property
    def summary(self) -> str:
        ek = self.exempt_kept
        extra = f" ({ek} kept on trust)" if ek else ""
        return f"{len(self.verified)} verified{extra}, {len(self.dropped)} dropped"


def _http_ok(url: str, *, session: requests.Session) -> tuple[bool, int | None, str]:
    """True only when ``url`` answers HTTP 200 (after redirects).

    Tries a cheap HEAD first; many sites reject HEAD, so it falls back to GET.
    """
    for method in ("head", "get"):
        try:
            resp = session.request(
                method,
                url,
                headers=_REQUEST_HEADERS,
                timeout=_HTTP_TIMEOUT,
                allow_redirects=True,
                stream=(method == "get"),
            )
            code = resp.status_code
            if method == "get":
                resp.close()
            if code == 200:
                return True, code, ""
            # HEAD is frequently disallowed/blocked even on live pages — retry GET.
            if method == "head" and code in (400, 401, 403, 405, 406, 501):
                continue
            return False, code, f"status {code}"
        except requests.RequestException as exc:
            if method == "head":
                continue
            return False, None, type(exc).__name__
    return False, None, "unreachable"


def _normalize_source(raw: dict) -> tuple[str, str, str, bool]:
    url = (raw.get("url") or "").strip()
    anchor = (raw.get("anchor") or raw.get("title") or "").strip()
    role = (raw.get("role") or "further_reading").strip().lower().replace("-", "_")
    if role not in _ALLOWED_ROLES:
        role = "further_reading"
    # ``vetted`` is the relevance gate's promotion marker for an off-fast-lane host.
    # Accept either a truthy ``vetted`` flag or an explicit ``tier == "vetted"``.
    vetted = bool(raw.get("vetted")) or (raw.get("tier") or "").strip().lower() == "vetted"
    return url, anchor, role, vetted


def verify_sources(
    sources, *, session: requests.Session | None = None, verify: bool = True
) -> SourcesReport:
    """Verify proposed external sources: dedupe, allowlist, live-200 check.

    ``sources`` is an iterable of dicts ``{"url", "anchor", "role"}`` (``title``
    accepted as an alias for ``anchor``). Returns a :class:`SourcesReport`.

    ``verify=False`` skips the live HTTP-200 check (dedupe + allowlist still run).
    Use only when re-importing bundles whose sources a generation-time
    relevance-gate pass already vetted, or when offline/CI: a since-dead link can
    slip through, so it is opt-in and the default stays ``True``.
    """
    report = SourcesReport()
    seen: set[str] = set()
    wiki_kept = 0

    def _is_wiki(u: str) -> bool:
        host = domain_of(u)
        return host == WIKIPEDIA_DOMAIN or host.endswith("." + WIKIPEDIA_DOMAIN)

    own_session = session or requests.Session()
    try:
        for raw in sources or []:
            if not isinstance(raw, dict):
                continue
            url, anchor, role, vetted = _normalize_source(raw)
            if not url or not anchor:
                report.dropped.append(
                    SourceCheck(url, anchor, role, False, reason="missing url/anchor")
                )
                continue
            key = url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            if domain_blocked(url):
                report.dropped.append(
                    SourceCheck(
                        url, anchor, role, False,
                        reason=f"blocked domain ({domain_of(url) or 'invalid url'})",
                    )
                )
                continue
            if is_domain_root(url):
                # Page-relevant, never domain-relevant: a bare homepage is dropped
                # even on the trusted fast-lane — deep-link the exact page or drop.
                report.dropped.append(
                    SourceCheck(
                        url, anchor, role, False,
                        reason="bare domain root / homepage — link a page-relevant deep page or drop",
                    )
                )
                continue
            trusted = domain_allowed(url)
            if not trusted and not vetted:
                # Off the trusted fast-lane and not promoted by the relevance gate.
                # Drop by default so an un-gated author bundle stays conservative.
                report.dropped.append(
                    SourceCheck(
                        url, anchor, role, False,
                        reason=(
                            "off-allowlist domain not vetted by the relevance gate "
                            f"({domain_of(url) or 'invalid url'})"
                        ),
                    )
                )
                continue
            if _is_wiki(url) and wiki_kept >= WIKIPEDIA_MAX_PER_ARTICLE:
                report.dropped.append(
                    SourceCheck(
                        url, anchor, role, False,
                        reason=(
                            f"wikipedia cap: max {WIKIPEDIA_MAX_PER_ARTICLE} Wikipedia "
                            "links per article — vary the source domains"
                        ),
                    )
                )
                continue
            if not verify:
                report.verified.append(
                    SourceCheck(url, anchor, role, True, reason="kept: 200-check skipped")
                )
                wiki_kept += _is_wiki(url)
                continue
            ok, code, reason = _http_ok(url, session=own_session)
            if ok:
                report.verified.append(SourceCheck(url, anchor, role, True, status=code))
                wiki_kept += _is_wiki(url)
            elif domain_verify_exempt(url) and code not in _DEAD_CODES:
                # Trusted top-tier domain that bot-blocks (403/etc.) but serves humans 200.
                # Keep it — a block is not death; only a 404/410 (handled above) drops it.
                report.verified.append(
                    SourceCheck(
                        url, anchor, role, True, status=code,
                        reason=f"kept: trusted domain, not 200-verifiable (status {code or 'no response'})",
                    )
                )
                wiki_kept += _is_wiki(url)
            else:
                report.dropped.append(SourceCheck(url, anchor, role, False, status=code, reason=reason))
    finally:
        if session is None:
            own_session.close()
    # Diversity condition on the cap: a second Wikipedia link ships only alongside
    # at least one non-Wikipedia source. An all-Wikipedia list trims back to one.
    wiki_verified = [c for c in report.verified if _is_wiki(c.url)]
    if len(wiki_verified) > 1 and len(wiki_verified) == len(report.verified):
        for extra in wiki_verified[1:]:
            report.verified.remove(extra)
            extra.ok = False
            extra.reason = (
                "wikipedia cap: a 2nd Wikipedia link ships only alongside a "
                "source from another domain"
            )
            report.dropped.append(extra)
    return report


def render_sources_markdown(verified: list[SourceCheck]) -> str:
    """Render verified sources as a Markdown ``## Sources & Further Reading`` list.

    Links are plain Markdown, so they render as ``follow`` anchors. Citations are
    listed before further-reading entries; order within a role is preserved.
    """
    if not verified:
        return ""
    ordered = sorted(verified, key=lambda c: _ROLE_ORDER.get(c.role, 1))
    lines = [
        f"## {_SOURCES_HEADING} {{#{_SOURCES_ANCHOR}}}",
        "",
        _SOURCES_LEAD,
        "",
    ]
    lines += [f"- [{c.anchor}]({c.url})" for c in ordered]
    return "\n".join(lines) + "\n"


def strip_sources_section(body_markdown: str) -> str:
    """Remove a previously-appended Sources section so re-rendering is idempotent."""
    return _SOURCES_SECTION_RE.sub("", body_markdown or "").rstrip()


def apply_external_sources(
    body_markdown: str,
    sources,
    *,
    log: logging.Logger = logger,
    verify: bool = True,
) -> tuple[str, SourcesReport]:
    """Verify ``sources`` and append a fresh Sources section to ``body_markdown``.

    Deterministic and idempotent: any prior Sources section is stripped first,
    then only links that pass the allowlist + live-200 check are appended.
    Returns the new body and the verification report. ``verify=False`` skips the
    live-200 check (see :func:`verify_sources`).
    """
    report = verify_sources(sources, verify=verify)
    body = strip_sources_section(body_markdown)
    for d in report.dropped:
        log.warning("external_links: dropped %s — %s", d.url or "(no url)", d.reason)
    section = render_sources_markdown(report.verified)
    if section:
        body = f"{body}\n\n{section}" if body else section
    log.info("external_links: %s", report.summary)
    return body, report

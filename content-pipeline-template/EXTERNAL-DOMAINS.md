# External-source fast-lane domains — categorized reference

**319 domains.** This is the human-readable mirror of `AUTHORITATIVE_DOMAINS`
in [`backend/content_pipeline/core/external_links.py`](../backend/content_pipeline/core/external_links.py)
— **the code is the source of truth**; edit there first, then regenerate this file.
Links to these hosts (and their subdomains) auto-pass the deterministic
external-source gate; any other host ships only with a per-page `vetted` from the
link-relevance gate. Wikipedia is additionally capped at 2 links/article (the 2nd
only alongside a source from another domain).

Large, genuinely valuable **platform / tooling / protocol** reference sites are
welcome (charting & algo platforms, DeFi protocol docs) for their educational /
documentation pages — the per-page rules still drop any sign-up / pricing /
product / download / affiliate URL, so a fast-laned platform is a *reference*,
never a funnel.

**Deliberately absent** (do not add without an explicit decision): our own
IB / affiliate / exchange **partners** in any market — blog posts route the reader
to *our* landing where the affiliate link lives, never straight to the partner
(IB attribution + market integrity, BUSINESS-MAP.md §9); **centralized crypto
exchanges we monetize through** (Binance, Bybit, BingX, CoinEx…) for the same
reason — DeFi protocols and non-partner platforms are fine, centralized exchanges
are not; offshore regulators with weak supervision (VFSC, IFSC Belize, FSA
Seychelles/SVG); hard-paywalled press (Bloomberg, FT, WSJ, The Economist — a free
article there can still earn a per-page `vetted`); URL shorteners (hard-blocked);
anonymous content farms and thin affiliate blogs (gate-rejected).

## Education / reference (15)

- `investopedia.com`
- `babypips.com`
- `corporatefinanceinstitute.com`
- `wikipedia.org`
- `britannica.com`
- `xe.com` — currency reference / historical FX rates
- `khanacademy.org` — finance & capital-markets course pages
- `cfainstitute.org`
- `garp.org` — GARP — FRM / risk-management body of knowledge
- `optionseducation.org` — OIC — Options Industry Council investor education
- `thebalancemoney.com` — Dotdash Meredith personal-finance reference
- `morningstar.com` — investing research + education
- `stockcharts.com` — ChartSchool — technical-analysis reference
- `nerdwallet.com` — personal-finance guides & comparison education
- `mymoney.gov`

## US regulators / federal bodies (23)

- `sec.gov`
- `investor.gov` — SEC's investor-education site (readable bulletins/alerts/glossary)
- `cftc.gov`
- `nfa.futures.org`
- `finra.org`
- `sipc.org`
- `federalreserve.gov`
- `treasury.gov`
- `treasurydirect.gov` — auctions, yields, savings bonds
- `consumerfinance.gov`
- `fdic.gov`
- `irs.gov` — trader-tax topics (wash sales, 1256 contracts, capital gains)
- `fincen.gov`
- `ftc.gov` — consumer fraud alerts
- `ic3.gov` — FBI Internet Crime Complaint Center — trading/crypto fraud reports
- `fbi.gov`
- `justice.gov` — fraud prosecutions / press releases
- `nasaa.org` — North American state/provincial securities administrators
- `msrb.org`
- `federalregister.gov`
- `congress.gov`
- `gao.gov`
- `cbo.gov`

## International regulators / supervisory bodies (69)

- `fca.org.uk`
- `fscs.org.uk` — UK deposit/investment compensation scheme
- `financial-ombudsman.org.uk`
- `esma.europa.eu`
- `eba.europa.eu`
- `ec.europa.eu`
- `cysec.gov.cy` — regulates the bulk of retail CFD/FX brokers
- `bafin.de`
- `amf-france.org`
- `consob.it`
- `cnmv.es`
- `afm.nl`
- `fsma.be` — publishes the well-known binary/CFD warning lists
- `cssf.lu`
- `mfsa.mt` — Malta — home regulator of many retail brokers
- `cmvm.pt`
- `hcmc.gr`
- `knf.gov.pl`
- `cnb.cz`
- `mnb.hu`
- `fi.se` — Sweden Finansinspektionen
- `finanstilsynet.no`
- `finanstilsynet.dk`
- `finanssivalvonta.fi` — Finland FIN-FSA
- `finma.ch`
- `asic.gov.au`
- `moneysmart.gov.au` — ASIC's investor-education site
- `fma.govt.nz`
- `ciro.ca`
- `osc.ca`
- `securities-administrators.ca` — CSA — national investor alerts
- `mas.gov.sg`
- `fsa.go.jp` — Japan FSA
- `sfc.hk`
- `hkma.gov.hk`
- `fsc.go.kr` — Korea Financial Services Commission
- `sc.com.my` — Malaysia Securities Commission
- `sec.or.th`
- `ojk.go.id` — Indonesia OJK
- `sec.gov.ph`
- `sebi.gov.in`
- `isa.gov.il` — Israel Securities Authority — led the binary-options ban
- `cma.org.sa` — Saudi Capital Market Authority
- `sca.gov.ae`
- `dfsa.ae`
- `fsca.co.za`
- `cnbv.gob.mx`
- `cvm.gov.br`
- `cmfchile.cl`
- `centralbank.ie`
- `fma.gv.at` — Austria — Financial Market Authority (FMA)
- `fsc.bg` — Bulgaria — Financial Supervision Commission
- `hanfa.hr` — Croatia — Financial Services Supervisory Agency (HANFA)
- `dfsa.dk` — Denmark — Danish FSA (alias of finanstilsynet.dk)
- `fi.ee` — Estonia — Finantsinspektsioon (Financial Supervision Authority)
- `cb.is` — Central Bank of Iceland
- `jsc.gov.jo` — Jordan Securities Commission
- `cma.or.ke` — Kenya — Capital Markets Authority
- `cmb.gov.tr` — Turkey — Capital Markets Board (CMB)
- `bcra.gob.ar` — Central Bank of Argentina (BCRA)
- `bma.bm` — Bermuda Monetary Authority (BMA)
- `asfi.gob.bo` — Bolivia — Financial System Supervisory Authority (ASFI)
- `bch.hn` — Central Bank of Honduras
- `fscjamaica.org` — Jamaica — Financial Services Commission
- `secp.gov.pk` — Pakistan — Securities & Exchange Commission (SECP)
- `bcu.gub.uy` — Central Bank of Uruguay (BCU)
- `cbr.ru` — Central Bank of Russia (CBR)
- `iosco.org`
- `fatf-gafi.org` — AML/CFT standards body

## Central banks & Federal Reserve system (38)

- `newyorkfed.org` — NY Fed — FX committee, reference rates
- `stlouisfed.org` — includes fred.stlouisfed.org (FRED data)
- `chicagofed.org`
- `frbsf.org` — San Francisco Fed
- `atlantafed.org`
- `clevelandfed.org`
- `dallasfed.org`
- `kansascityfed.org`
- `minneapolisfed.org`
- `philadelphiafed.org`
- `richmondfed.org`
- `bostonfed.org`
- `ecb.europa.eu`
- `bankofengland.co.uk`
- `bundesbank.de`
- `banque-france.fr`
- `bancaditalia.it`
- `bde.es` — Bank of Spain
- `dnb.nl`
- `nbb.be`
- `oenb.at`
- `bportugal.pt`
- `riksbank.se`
- `norges-bank.no`
- `nationalbanken.dk`
- `suomenpankki.fi`
- `boj.or.jp`
- `bankofcanada.ca`
- `rba.gov.au`
- `rbnz.govt.nz`
- `snb.ch`
- `rbi.org.in`
- `pboc.gov.cn`
- `bok.or.kr`
- `bcb.gov.br`
- `banxico.org.mx`
- `tcmb.gov.tr`
- `sama.gov.sa`

## Statistical / macro / multilateral (25)

- `bis.org`
- `imf.org`
- `worldbank.org`
- `oecd.org`
- `wto.org`
- `ilo.org`
- `adb.org` — Asian Development Bank
- `ebrd.com`
- `bls.gov`
- `bea.gov`
- `census.gov`
- `tradingeconomics.com` — economic indicators, calendars, macro data
- `eia.gov` — US energy data — WTI/Brent, natural gas
- `iea.org` — International Energy Agency
- `opec.org`
- `ons.gov.uk`
- `destatis.de`
- `insee.fr`
- `istat.it`
- `ine.es`
- `statcan.gc.ca`
- `abs.gov.au`
- `stats.govt.nz`
- `stat.go.jp`
- `stats.gov.cn`

## Exchanges / market operators / market infrastructure (23)

- `cmegroup.com`
- `nasdaq.com`
- `nyse.com`
- `cboe.com`
- `lseg.com`
- `ice.com`
- `eurex.com`
- `euronext.com`
- `deutsche-boerse.com`
- `six-group.com` — SIX Swiss Exchange
- `asx.com.au`
- `jpx.co.jp`
- `hkex.com.hk`
- `sgx.com`
- `krx.co.kr`
- `tmx.com` — Toronto
- `b3.com.br`
- `nseindia.com`
- `bseindia.com`
- `lme.com` — London Metal Exchange
- `dtcc.com`
- `theocc.com` — Options Clearing Corporation
- `swift.com`

## Index providers / rating agencies (5)

- `spglobal.com` — S&P Dow Jones Indices, S&P Ratings research
- `msci.com`
- `ftserussell.com`
- `moodys.com`
- `fitchratings.com`

## Industry bodies / commodity market references (10)

- `isda.org`
- `fia.org` — Futures Industry Association
- `sifma.org`
- `ici.org` — Investment Company Institute
- `aima.org` — Alternative Investment Management Association
- `iif.com` — Institute of International Finance
- `world-exchanges.org` — World Federation of Exchanges
- `gold.org` — World Gold Council research
- `lbma.org.uk` — London bullion benchmarks
- `silverinstitute.org`

## Consumer protection / fraud & scam references (5)

- `scamwatch.gov.au`
- `actionfraud.police.uk`
- `bbb.org`
- `europol.europa.eu`
- `interpol.int`

## Trading platforms / charting / algo & quant tooling docs (33)

- `metaquotes.net`
- `metatrader4.com`
- `metatrader5.com`
- `mql4.com` — docs.mql4.com — official MQL4 language reference (readable docs)
- `mql5.com`
- `tradingview.com`
- `ctrader.com` — help.ctrader.com — official cTrader docs
- `ninjatrader.com` — NinjaScript strategy/indicator docs
- `multicharts.com`
- `sierrachart.com`
- `quantconnect.com` — cloud algo platform + LEAN engine docs
- `backtrader.com` — open-source Python backtesting framework docs
- `interactivebrokers.com` — IBKR — TWS/API developer docs
- `tradestation.com`
- `ig.com` — IG Academy — trading education (non-partner)
- `telegram.org` — core.telegram.org — official Bot API / platform docs
- `developer.chrome.com` — extension platform docs (subdomain-scoped on purpose)
- `developer.mozilla.org` — MDN
- `developer.android.com`
- `developer.apple.com`
- `python.org` — official language docs for algo-trading content
- `numpy.org`
- `pandas.pydata.org`
- `scipy.org`
- `scikit-learn.org`
- `statsmodels.org`
- `matplotlib.org`
- `plotly.com` — open-source charting library docs
- `jupyter.org`
- `r-project.org`
- `quantlib.org`
- `ta-lib.org` — canonical technical-analysis library docs
- `nist.gov` — cryptography / security standards (API keys, 2FA)

## Crypto protocols / open data / research / journalism (25)

- `bitcoin.org`
- `bitcoincore.org`
- `lightning.network`
- `ethereum.org`
- `litecoin.org`
- `xrpl.org` — XRP Ledger docs
- `cardano.org`
- `polkadot.network`
- `solana.com`
- `chain.link` — Chainlink oracle docs
- `etherscan.io`
- `blockchair.com`
- `mempool.space`
- `coinmarketcap.com`
- `coingecko.com`
- `defillama.com` — open DeFi TVL/data reference
- `glassnode.com`
- `chainalysis.com` — widely-cited crypto-crime research
- `coindesk.com`
- `theblock.co`
- `messari.io`
- `decrypt.co`
- `blockworks.co`
- `bitcoinmagazine.com`
- `dune.com` — open on-chain analytics

## DeFi protocols & crypto platform docs (18)

- `uniswap.org`
- `aave.com`
- `makerdao.com`
- `compound.finance`
- `curve.fi`
- `lido.fi`
- `pancakeswap.finance`
- `dydx.exchange` — perpetuals DEX docs
- `1inch.io`
- `synthetix.io`
- `balancer.fi`
- `sushi.com`
- `thegraph.com` — open indexing protocol docs
- `ipfs.tech`
- `consensys.io` — Ethereum tooling docs/research
- `alchemy.com` — web3 developer platform — node/API docs & education
- `ledger.com` — Ledger Academy — wallet-security education
- `trezor.io`

## Financial journalism (non-paywalled outlets only) (16)

- `reuters.com`
- `apnews.com`
- `cnbc.com`
- `marketwatch.com`
- `benzinga.com` — free markets news & analysis (Benzinga Pro is separate/paid)
- `investing.com` — markets news + data portal (free)
- `bbc.com`
- `bbc.co.uk`
- `theguardian.com`
- `npr.org`
- `axios.com`
- `fortune.com`
- `forbes.com` — business/finance journalism (free Forbes.com articles)
- `money.com` — Money — personal-finance journalism
- `financemagnates.com` — retail-trading / FX & fintech industry trade news
- `kitco.com` — precious-metals news & charts

## Academic / research (7)

- `nber.org`
- `ssrn.com`
- `arxiv.org` — q-fin
- `repec.org` — ideas.repec.org — open economics papers
- `cepr.org`
- `brookings.edu`
- `piie.com` — Peterson Institute

## Payments / money transfer / currency-exchange services (4)

Deposit/withdrawal-method and FX/remittance references — the per-page gate still
drops their sign-up / pricing / product URLs, so a fast-laned service is a
reference, never a funnel (same rule as every other domain here).

- `wise.com` — Wise — multi-currency accounts, FX rates & transfer guides
- `paypal.com` — payment rail — deposit/withdrawal method reference
- `riamoneytransfer.com` — Ria — remittance / money-transfer reference
- `bestchange.com` — e-currency / crypto exchange-rate aggregator

## Precious metals — bullion dealers & price data (3)

- `goldprice.org` — live gold/silver spot prices & historical charts
- `bullionvault.com` — bullion market data / gold-investing education
- `moneymetals.com` — precious-metals news & market analysis

## Regenerating this file

After editing `AUTHORITATIVE_DOMAINS`, either regenerate mechanically (parse the
`# ---- <category>` comments + quoted entries out of the frozenset block and
rewrite the sections above), or update the affected section by hand — keeping the
per-category counts and the total in the intro accurate.

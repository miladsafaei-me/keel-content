"""Value-level host configuration for keel-content (the ``KEEL_CONTENT`` settings dict).

Two config surfaces exist and are intentionally separate:

* ``keel_content.host`` — resolves the host's Django *models* and *render callables*
  (the CMS seam). See that module.
* ``keel_content.config`` (this file) — resolves *value-level* configuration: the brand
  tokens the hero / OG-image builders paint with, and the external-domain fast-lane the
  further-reading gate trusts. None of it touches the database.

Every key is optional; the defaults are deliberately NEUTRAL (a generic dark theme, no
wordmark, no logo mark) so the package carries no host brand identity. A host paints its
identity by setting ``KEEL_CONTENT["brand"]`` and, if it wants a curated outbound
allowlist, ``KEEL_CONTENT["external_domains"]``::

    KEEL_CONTENT = {
        "brand": {
            "navy_0": "#050b1a", "accent": "#41ffa0",
            "wordmark": "MySite",
            "logo_mark_svg": "<polygon .../>",
            "logo_mark_viewbox": (2.0, 0.62, 87.25, 145.4),  # (xmin, ymin, w, h)
        },
        "external_domains": ["sec.gov", "investopedia.com", ...],  # extra fast-lane hosts
    }
"""

from __future__ import annotations

# Neutral brand defaults. The BUY/SELL pair are trade-semantic standards (green = up /
# long, red = down / short) rather than any one site's identity, so they ship as-is; a
# host that trades keeps them, a non-trading host simply never renders a trade visual.
_DEFAULT_BRAND = {
    "navy_0": "#0b1020",
    "navy_1": "#141b2e",
    "navy_2": "#0c1322",
    "accent": "#3b82f6",
    "accent_aa": "#1e40af",
    "buy": "#3bb273",
    "sell": "#df2c53",
    "blue": "#60a5fa",
    "amber": "#f59e0b",
    "text_main": "#ffffff",
    "text_secondary": "#a1afc6",
    "text_muted": "#cbd5e1",
    "wordmark": "",
    "logo_mark_svg": "",
    "logo_mark_viewbox": None,
}


def _keel_content() -> dict:
    """Return the ``KEEL_CONTENT`` settings dict, tolerating unconfigured settings."""
    try:
        from django.conf import settings

        return getattr(settings, "KEEL_CONTENT", {}) or {}
    except Exception:
        return {}


def content_setting(key: str, default=None):
    return _keel_content().get(key, default)


def brand(token: str, default=None):
    merged = {**_DEFAULT_BRAND, **(content_setting("brand", {}) or {})}
    return merged.get(token, default)


def external_domains() -> list:
    """Host-supplied extra fast-lane domains for the further-reading gate (or [])."""
    return list(content_setting("external_domains", []) or [])

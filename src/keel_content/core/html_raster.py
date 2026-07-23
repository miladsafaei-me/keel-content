"""Rasterize an HTML string to PNG bytes with the in-image Playwright Chromium.

Replaces the old flatpak-Chromium CLI path (``nb2_image._rasterize`` and
``tools/content_pipeline/figure_rasterize.sh``) so the content-pipeline render
stages run anywhere the Playwright browser is installed. In production that is
inside the web image (the base is ``mcr.microsoft.com/playwright/python`` and the
Dockerfile already runs ``playwright install chromium``), which is where the
render stages now execute over SSH — no system browser, no flatpak, no local
Linux tooling on the box driving generation.
"""

from __future__ import annotations


def rasterize_html(html: str, *, width: int, height: int, settle_ms: int = 1500) -> bytes:
    """Render ``html`` at exactly ``width`` x ``height`` (device scale 1) and return
    PNG bytes. Waits for web fonts to load plus ``settle_ms`` so any in-page sizing
    script (e.g. the NB2 chip auto-sizer) has run before the screenshot."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--force-color-profile=srgb"]
        )
        try:
            page = browser.new_page(
                viewport={"width": int(width), "height": int(height)},
                device_scale_factor=1,
            )
            page.set_content(html, wait_until="load")
            try:
                page.evaluate("document.fonts && document.fonts.ready")
            except Exception:  # noqa: BLE001 — fonts API best-effort; still settle below
                pass
            page.wait_for_timeout(int(settle_ms))
            png = page.screenshot(type="png")
        finally:
            browser.close()
    return png

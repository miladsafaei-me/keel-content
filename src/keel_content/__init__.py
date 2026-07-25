"""keel-content: the reusable, business-blind content-generation pipeline.

Extracted from SignalBots and neutralized: the engine (``core/``), the four intake
routes, the generator workflow, the in-article figure / hero / external-link passes, and
the glossary-term authoring pipeline all live here; every reach into a host CMS is routed
through ``keel_content.host`` (models + render callables) or ``keel_content.config``
(brand tokens + external-domain fast-lane), and the one sanctioned publish seam is the
``ContentPublisher`` protocol in ``keel_content.core.publisher`` (a host writes its own
adapter). The in-body visual catalog is consumed from the sibling package ``keel-ui``.

The pipeline is deliberately business-blind: it produces a *draft*; monetization
(affiliate wiring, product showcase, asides) is the host's render-layer concern.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Single source of truth: the installed dist version (pyproject [project].version),
    # so __version__ can never drift from the release tag. See keel-kit
    # methodology/versioning-and-release.md.
    __version__ = _pkg_version("keel-content")
except PackageNotFoundError:  # running from an uninstalled source checkout
    __version__ = "0.0.0+unknown"

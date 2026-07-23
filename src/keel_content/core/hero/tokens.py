"""Brand tokens for hero SVGs.

Resolved from ``KEEL_CONTENT["brand"]`` (see ``keel_content.config``) with neutral
defaults, so the hero library carries no host brand identity of its own. A host paints
its palette by setting the brand dict; unset, the heroes render in a neutral dark theme.
The BUY/GREEN and SELL tokens are the trade-semantic standard (up/long green,
down/short red), not any one site's identity.
"""

from __future__ import annotations

from keel_content.config import brand as _brand

NAVY_0 = _brand("navy_0")          # base background
NAVY_1 = _brand("navy_1")          # raised surface
NAVY_2 = _brand("navy_2")          # darker side-face for isometric depth
GREEN = _brand("accent")           # primary brand accent
GREEN_AA = _brand("accent_aa")     # darker accent, iso side faces
BUY = _brand("buy")                # trade-semantic: up/long only
SELL = _brand("sell")              # trade-semantic: down/short only
BLUE = _brand("blue")              # secondary role
AMBER = _brand("amber")            # secondary role
TEXT_MAIN = _brand("text_main")
TEXT_SECONDARY = _brand("text_secondary")
TEXT_MUTED = _brand("text_muted")

# Canvas: 1.91:1 is the strict og ratio; the on-page 16:9 box cover-crops ~3%.
W, H = 1200, 630

# The motif occupies the right zone; the headline lives in the left zone.
MOTIF_CX, MOTIF_CY = 968, 440   # default center of the motif area
MARGIN = 74

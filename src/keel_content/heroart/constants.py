"""Canvas size and the type stack. Kept apart from draw and worlds so those two can
import it without a cycle."""

W, H = 1200, 675

"""The wordmark signed into the corner of the directions that sign their canvas.

Empty by default and deliberately so: a hero signed with the wrong brand is worse
than a hero signed with none, and this package is consumed by several unrelated
sites. A consumer opts in by passing ``--wordmark`` to the build CLI, or by
setting this value before rendering.
"""
WORDMARK = ""

SANS = "Inter, 'Noto Sans', Helvetica, Arial, sans-serif"
SERIF = "'Noto Serif', Georgia, 'Times New Roman', serif"
MONO = "'IBM Plex Mono', 'Source Code Pro', ui-monospace, monospace"

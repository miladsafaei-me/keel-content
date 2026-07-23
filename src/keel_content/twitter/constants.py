"""Tunable knobs for the Twitter/X intake route.

Kept in one place so the quality bar, the per-post embed cap, and the LLM models
are all adjustable without touching service logic.
"""

from __future__ import annotations

# --- Triage (job 1) ---
# Deterministic pre-filter: a tweet below this view count is dropped before any
# LLM sees it (cheap noise removal). Set to 0 to disable the floor.
MIN_VIEW_COUNT = 3000
# Phrases that mark a self-promo / house-ad tweet — dropped deterministically.
PROMO_MARKERS = (
    "subscribe",
    "sign up",
    "our trades",
    "premium members",
    "link below",
    "link in bio",
    "join our",
    "our api",
    "we just launched",
    "we have just launched",
    "free trial",
    "check it out",
    "view or sign up",
)

# --- Embed (job 3) ---
# Hard cap: at most this many active embedded tweets per post. Enforced in code
# (a rolling window), never delegated to the LLM.
TWEETS_PER_POST_CAP = 3
# A tweet must reach this match relevance (0..1) to be embedded at all; below it,
# an otherwise-good embed tweet is treated as a content-gap signal and rerouted
# to the idea sink instead of force-fitting it into a weakly-related post.
MIN_EMBED_RELEVANCE = 0.55

# --- LLM models ---
# Cheap classifier for the high-volume triage pass.
TRIAGE_MODEL = "claude-haiku-4-5-20251001"
# Slightly stronger model for the lower-volume idea-spec + embed-match reasoning.
REASONING_MODEL = "claude-sonnet-4-6"

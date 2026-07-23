"""Twitter/X intake — the fourth Content-Pipeline route.

Funnel: monitor (fetch) → triage (quality gate + route) → {ingest (idea →
ContentPlan) | embed (attach to a published post)}. Each stage is a thin service
here, driven by a matching management command; state lives in the
``keel_content.TweetCandidate`` staging table.
"""

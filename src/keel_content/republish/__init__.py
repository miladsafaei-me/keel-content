"""Republish route — turn pages that already rank into our own content.

A fourth intake route beside the keyword, Twitter and YouTube ones. It differs
from them in one way that shapes everything here: **the number of outputs is
independent of the number of inputs**. Two thin sources often deserve one
article, one broad source can owe several, and the smallest useful output is a
single visual dropped into an article published months ago.

The division of labour is deliberate:

* ``page-extract`` (a standalone package, no Django, no keel) does everything
  mechanical — fetching, extraction, image triage, chart recovery from a
  screenshot, figure drawing, and the markup-or-picture policy.
* This module does everything that knows about *our* content model — the plan
  contract, bundle assembly, the component catalog, and grafting a visual into
  a post that already exists.

A model is paid for exactly two things in between: mapping each extracted visual
job onto a component or a builder, and writing the prose.
"""
from .plan import PLAN_SCHEMA, validate_plan
from .compose import compose
from .brief import visual_opportunities

__all__ = ["PLAN_SCHEMA", "validate_plan", "compose", "visual_opportunities"]

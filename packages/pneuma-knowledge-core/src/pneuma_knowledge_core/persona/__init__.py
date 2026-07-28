"""persona: LLM-expand one sentence → a self-consistent UserProfile draft.

Mirrors recall/ layout: a small package whose public surface is re-exported here.
The draft carries only the SEMANTIC subset a human would fill on the onboarding form;
the service overlays it onto a deterministic mock base for the non-semantic fields
(avatar color, joined_at) that the LLM must never invent.
"""

from .generate import (
    ProfileDraft,
    DraftWorkspace,
    DraftLocale,
    DraftPreferences,
    synthesize_profile_draft,
)

__all__ = [
    "ProfileDraft",
    "DraftWorkspace",
    "DraftLocale",
    "DraftPreferences",
    "synthesize_profile_draft",
]

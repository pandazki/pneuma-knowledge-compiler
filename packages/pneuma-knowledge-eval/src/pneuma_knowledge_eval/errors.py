"""Evaluation failure modes. Both are loud on purpose.

`EvalInputError` — the bundle/corpus handed in is not what it claims to be. Evaluation
stops rather than reporting a number computed over half an input.

`EvalDependencyError` — a `full`-mode arm was requested without the credential or the
service it needs. It must not fall back to the mechanical matcher: that would publish a
weaker measurement under the stronger label, which is worse than no measurement.
"""

from __future__ import annotations


class EvalInputError(ValueError):
    """The evaluation input is missing, malformed, or internally inconsistent."""


class EvalDependencyError(RuntimeError):
    """A full-mode dependency (embedding key, judge model, live service) is unavailable."""

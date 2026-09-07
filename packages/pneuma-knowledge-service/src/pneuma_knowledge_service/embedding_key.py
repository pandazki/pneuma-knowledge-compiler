"""Does this deployment's embedding model need a key, and did anybody set it?

L2 is not optional equipment. A coding agent replaces the compile MODEL; it does not embed,
and no executor choice switches semantic indexing off. So a deployment whose
`EMBEDDING_MODEL` names a provider spec needs that provider's key, and the honest moment to
say so is startup — not the first `index` job, which fails at the first embed call with a
provider error nobody reads as "you never set the key".

A reminder, never a refusal: the library is still importable, L0 and L1 are unconditional
(I3), and canonical still compiles. What is missing is L2, and the one sentence that says
which setting and which variable is the whole feature.

Standard library only, and no `Settings` import: the scaffold generator (`scaffold/init.py`)
runs before any environment exists and loads this module by path, so the reminder the
generator prints and the reminder the stack logs are one text with one source.
"""

from __future__ import annotations

#: Spec prefix → (the environment variable that spec's client sends, the `Settings` field
#: that carries it). One row per provider the embedding side can name. `fake:<dim>` is
#: deliberately absent: it is the keyless spec, and a keyless spec needing a key would be a
#: contradiction rather than a finding.
_REQUIREMENTS: tuple[tuple[str, str, str], ...] = (
    ("openrouter:", "OPENROUTER_API_KEY", "openrouter_api_key"),
)

#: The setting that names the model, spelled once — it is half of what the reminder says.
EMBEDDING_SETTING = "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL"


def embedding_key_requirement(spec: str) -> tuple[str, str] | None:
    """`(env var, settings field)` the embedding spec needs, or None when it needs none.

    Pure, and the only place the mapping is written: `fake:384`, `scripted:` runs and an
    empty spec all answer None, which is why a test configuration produces nothing.
    """
    text = str(spec or "").strip()
    for prefix, env_var, field in _REQUIREMENTS:
        if text.startswith(prefix):
            return env_var, field
    return None


def missing_embedding_key(spec: str, key: str) -> str:
    """The variable whose absence will break L2, or `""` when there is nothing to say.

    `key` is whatever the deployment resolved for that variable; blank and absent are the
    same thing, because a variable set to whitespace is a variable nobody set.
    """
    requirement = embedding_key_requirement(spec)
    if requirement is None:
        return ""
    env_var, _field = requirement
    return "" if str(key or "").strip() else env_var


def embedding_key_reminder(spec: str, env_var: str) -> str:
    """The one sentence, named once: which setting, which variable, and what stops working."""
    return (
        f"{EMBEDDING_SETTING} is {spec!r}, which embeds through {env_var}, and {env_var} is "
        f"not set. Semantic indexing (L2) and semantic recall will fail at the first embed "
        f"call until it is: an embedding key is required for L2, and no compile executor "
        f"replaces it. Set {env_var} where this deployment states its environment (`.env`)."
    )


def embedding_key_notice(spec: str, key: str) -> str:
    """The reminder for this (spec, key) pair, or `""` when this deployment needs none."""
    env_var = missing_embedding_key(spec, key)
    return embedding_key_reminder(spec, env_var) if env_var else ""

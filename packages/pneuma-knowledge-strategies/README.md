# pneuma-knowledge-strategies

**English** | [简体中文](README.zh-CN.md)

Shipped strategies: ready-made **domain compile contracts as data**, plus a loader that does exactly two things — list what is available, read one.

## A starting point, not an answer

This project's stance lives in [`docs/guides/compile-contract.md`](../../docs/guides/compile-contract.md): a contract should be derived from your own material — look at the real data first, then decide what deserves recording and where it goes. A contract someone else wrote cannot know what counts as high-value or noise in your domain.

Why ship any, then? Because facing an empty file is the most expensive step of a cold start. A runnable, structurally complete contract lets you **see the system working first**, then rewrite it section by section against your own material. It is scaffolding, meant to be replaced; leaving it in production as-is means adopting someone else's domain judgement as your own.

**This package is not part of the framework.** It does not import `pneuma_knowledge_core` and never will; core and the service never import it either. Which contract is in effect is decided by the **application**, explicitly, at startup.

## Catalog

| Directory | skill_id | Version | What it is |
| --- | --- | --- | --- |
| `strategies/personal-knowledge/` | `personal-knowledge` | `v1` | The original personal-knowledge reference: evidence tiers, worked examples and counter-examples, frozen history volumes, first-class beginnings, a closing self-check. |
| `strategies/personal-knowledge/` | `personal-knowledge` | `v2` | `v1` plus two judgements: IM images and labelled caption/OCR evidence share one cited L0 block, with other native media explicitly unsupported; and an owner-dialogue source is the owner speaking about the library, so what it says about an existing claim corrects or supersedes that claim rather than filing a second one beside it. |

One contract per domain, deliberately. **Serving a different kind of user means adding a strategy — a new directory — not stacking versions of an existing one.** A version bump happens only when a contract's own judgement is revised.

## API

Data plus a loader, nothing else:

```python
from pneuma_knowledge_strategies import list_strategies, get_strategy, load_strategy_text

for s in list_strategies():
    print(s.skill_id, s.version, s.domain, s.summary)

s = get_strategy("personal-knowledge", "v2")
body = s.read_text()          # the contract body, verbatim
s.path_templates              # the contract's on-disk path templates
s.contract_rules              # extra contract clauses (prompt catalog keys)
text = load_strategy_text("personal-knowledge", "v2")   # equivalent shortcut
```

`Strategy` carries `skill_id` / `version` / `path_templates` / `contract_rules` alongside the body because those four fields plus the body are the contract's identity: a consumer hashes them together into the `Skill-Content-Hash` stamped on every canonical commit. Making callers retype them is how a provenance hash silently stops matching.

## Using one in an application

The framework will not choose a contract for you. The application converts a strategy into a `SkillVersion` and registers it at startup:

```python
from pneuma_knowledge_core.skill import SkillVersion, register_skill_base
from pneuma_knowledge_strategies import get_strategy

s = get_strategy("personal-knowledge", "v2")
register_skill_base(
    s.version,
    SkillVersion.from_parts(
        skill_id=s.skill_id,
        version=s.version,
        instructions=s.read_text(),
        path_templates=s.path_templates,
        contract_rules=s.contract_rules,
    ),
)
```

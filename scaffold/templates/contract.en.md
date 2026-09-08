---
skill_id: {{SKILL_ID}}
version: app-v1
path_templates:
  - subjects/{slug}.md
---

# Compile contract: a working subject library

## Purpose and page boundaries

Help readers recover useful facts, decisions and changes from their material. Use
`subjects/{slug}.md` for one independently evolving subject: a person, project,
organization or recurring topic. Reuse a page when the sources establish that it is
the same subject; connect related pages where useful.

## What to retain

Record meaningful events, decisions, commitments and current states, with the details
needed to understand or act on them. Keep the source's attribution, conditions,
uncertainty and time precision. Distinguish plans from outcomes and corrections from
later changes. Keep useful history in the ledger and summarize it in the overview.
Repetition and passing mentions need no new claim or empty page.

Exclude credentials and private details unrelated to the library's purpose. This is
canonical admission policy; material that must never enter L0 must be removed before import.

## Adapt to the domain

This starter can compile material as written. After inspecting representative sources,
specialize its purpose, page families, admission examples and exclusions for the user's
actual needs. Keep the body and `path_templates` consistent. Owner details are optional;
an unknown profile does not establish anyone's identity in the sources.

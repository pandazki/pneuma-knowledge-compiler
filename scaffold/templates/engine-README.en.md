# {{PROJECT_NAME}} engine

This directory is the versioned strategy of your library. The API key and this machine's
ports live in `../.env`; sources and runtime state live outside this Git repository.

| File | Decision |
|---|---|
| `compile/contract.md` | Purpose, subject boundaries, admission, authority and time |
| `engine.yaml` | Model roles, tool/call limits, overview bounds and index components |
| `intake/intake.yaml` | Segmentation of new source material |
| `recall/recall.yaml` | Retrieval breadth, evidence context and answer format/style |
| `persona/profile.yaml` | Optional declared owner details and locale provenance |
| `compile/challenge.yaml` | Optional coverage probe and compensation |
| `evolve/evolve.yaml` | Structural proposal triggers and draft lifetime |
| `prompts/overlays.yaml` | Framework prompt language and whole-clause replacements |

Start with the contract and inspect actual output before changing other knobs. The starter
keeps independent subjects separate and useful specifics in their ledgers; its overview is
a concise reading of that knowledge. No contract can make a valid citation prove a correct
interpretation. Check sources, pages and real questions together.

## Defaults and deliberate changes

`ranked` retrieves broadly and supplies bounded claims, derived episode summaries and raw
windows. `structured` separates answer text/kind/citations and reports invalid returned
citations. `ask --sources` reads exact cited L0 spans. `select` adds a bounded selection call;
`all` gives candidates to the answer under a character ceiling. Try overrides on representative
questions before changing defaults. Fast uses one final answer call; planning, glance,
components, selection or fallback can add calls. Deep can search and read repeatedly.

Keep `components` empty until the domain supports them. `people` requires a matching person
family and identity evidence, `time` adds source-time lookup, and `attention` observes business
consultations. The CLI's direct recall calls leave no consultation records. Coverage challenge
and automatic evolution are off because they add work and calls; a green coverage probe is
still model judgment. `evolve step` keeps a draft; explicit adoption is a separate action.

| Edit | Effect |
|---|---|
| Recall budgets, style, evidence strategy | Next invocation/question |
| Model roles or prompt overlays | Next CLI invocation; restart long-running services |
| Compile contract or challenge policy | Future compile work; existing claims are not recompiled |
| Evolve policy | Future proposal scheduling; adoption changes canonical structure |
| Chunking policy | New indexing; a derived rebuild replays kept semantic boundaries |
| Embedding model | Rebuild affected vectors; dimensions and embedding space must agree |

Re-importing identical sources normally deduplicates them. To compare full compilations,
use a fresh project with the same source inventory. Do not erase the original as the routine
way to change a contract. A derived rebuild recreates indexes from authorities, not new L3
judgments. Equal vector dimensions do not make different embedding models interchangeable.

System-detected locale is labelled `deployment_default`; it is not the owner's statement.
Set a locale field's provenance to `profile` only when declared. Blank biography, name and
dates remain unstated. Prompt `language` selects framework wording; it is separate from
source language and answer-language preferences.

Files are read on each CLI invocation. Precedence is process environment → engine files →
framework defaults. Use environment overrides for diagnosis and files for lasting policy:

```bash
git -C engine diff
git -C engine add -A
git -C engine commit -m 'Describe the actual strategy change'
```

These commands run from the project root. The Engine Console configures the same directory.
For deeper guidance, read the framework's `docs/guides/compile-contract.md`,
`docs/guides/recall-strategies.md`, and `scaffold/AGENT-GUIDE.md`.

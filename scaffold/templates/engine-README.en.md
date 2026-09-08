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

The default `select` retrieves broadly, then asks the recall model to choose evidence for the
question from claims, derived episode summaries, raw windows and enabled component results.
The answer still receives bounded evidence; selected provenance can open original passages
within the source-reading budget. This helps when relevant evidence ranks below the first
few hits. It cannot recover a fact missing from the candidate pool or guarantee a good choice.

Selection spends a model call and can increase tokens and latency. On timeout or malformed
output, the framework falls back to ranked evidence and records the degradation.
Use `ask '…' --evidence-strategy ranked` to compare the cheaper ranking-based selection on
representative questions; save that policy in `recall/recall.yaml` if it meets your needs.
`all` passes the candidate pool under a character ceiling. These policies take effect on the
next question; they do not recompile knowledge. Existing projects keep their explicit policy.

`structured` separates answer text/kind/citations and reports invalid returned citations.
`ask --sources` reads exact cited L0 spans. Fast uses one final answer call; planning, glance,
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
| the coding agent's installed skill | future compiles only — re-installed on apply, read at the agent's next start |

When `engine.yaml`'s `compile` names a coding agent (`agent:codex`, `agent:claude-code`)
rather than a model, the skill that agent reads is *generated from this directory* — the
contract, the prompt overlays, the language and the enabled components — and re-installed
whenever an apply moves any of them. It is never hand-written: `pkc skill verify` re-renders
it and reports anything that drifted, and `pkc skill install` puts it back. A session that is
already running keeps the words it started with until it restarts.

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

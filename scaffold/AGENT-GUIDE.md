# Guide for an agent building a knowledge library

**English** | [简体中文](AGENT-GUIDE.zh-CN.md)

Use the scaffold to build a library the user can inspect, question and maintain. Your job is
to decide how their material becomes useful knowledge and verify the result. A high benchmark
score, a large claim count and a green compile are each insufficient evidence of that.

## 1. Form an expectation before building

Read [README.md](README.md), then representative material spanning the source kinds, time
periods and subjects present. State what you expect a useful library to preserve and what
its readers will return to ask or do. Distinguish evidence in the sources from your own
expectation. A library can concern a team, domain or organization; never invent a personal
owner biography to satisfy a setup form.

Ask for missing information only when it changes a consequential decision you cannot infer.
Use existing authorization; do not make each reversible step a new approval gate. The demo
is optional and belongs in a separate project. Do not require a demo, data deletion, or a
fully bespoke contract before useful work can begin.

## 2. Preserve the material before optimizing it

Use the framework's [source contracts](../docs/reference/source-contracts.md) for structured
exports. Retain identities, timestamps, reply/thread relationships, media and labelled derived
representations. Do not flatten these into anonymous prose. Do not forge a supported provider
identity for an unsupported export; adapt its semantics explicitly and document any loss.
Markdown is sufficient for ordinary notes; `type: conversation` supports a limited speaker-line
grammar. Use JSON for transcripts where that grammar cannot preserve the structure.

Validate source counts, ordering and representative normalization before drawing conclusions
about the compiler. Keep observation time, event time and import time distinct. Unknown dates,
timezones and people stay unknown. Separate unrelated tenants. Remove material that must
never be stored or sent to the model before import; compile admission does not filter L0.

For evaluation, freeze input hashes and the evaluation protocol before building. Questions,
expected answers and gold evidence must not influence import, contract writing or compilation.
Keep a source-only audit separate from later question-based diagnosis. A model may still know
public benchmark material from training; procedural isolation is not proof of zero contamination.

## 3. Start with the contract, specialize with evidence

The generated contract is executable. It starts with one independently evolving subject per
`subjects/{slug}.md`; it is a baseline to adapt, not a universal ontology. A subject's future
use determines what detail matters: projects imply progress and obligations, decisions imply
rationale, events imply a timeline. Preserve useful facts in the ledger even when the overview
can omit them. A coarse summary is not a substitute for retained knowledge.

When the sources justify specialization, use the
[contract guide](../docs/guides/compile-contract.md). Keep these decisions explicit:

- Library purpose and intended future uses.
- Subject families, page boundaries, identity/alias criteria and matching `path_templates`.
- Admission and exclusion, including concrete examples from the domain.
- Authority, attribution, uncertainty, corrections versus changing state, and time precision.

Do not fill the contract with framework tool syntax or duplicate the architecture. Mechanics
belong to the framework; domain judgment belongs to the contract. Leave prompt overlays empty
until a specific model-visible problem requires one. Enable `people` only with a genuine
person family and identity-bearing sources; do not bind every subject to a person component.

## 4. Run the ordinary application and keep receipts

Generate a fresh project, inspect its contract and model roles, set the credential in `.env`,
and run `./start.sh`. It validates all inputs, then imports and drains the normal worker per
input file in filename order. Source bundles may expand into several natural source units.
For separate intake and worker operation use `ingest` then `compile`; the console worker is
an alternative queue consumer, not an additional compiler to run concurrently with the CLI.

Inspect `data/run-reports/`: input hashes, source IDs, complete job history, unresolved failures,
engine file hashes, answer time and degradation. A retry is another attempt, not an erased
failure. The CLI makes one extra attempt at unresolved compile work per drain; repeated drains
can add attempts, so record your retry limit before comparisons. Do not keep retrying until
a preferred library appears. Compile-token reports cover that model, not all model/embedding
costs. Use provider usage or explicit per-role accounting for total cost.

The normal path uses the framework's intake, worker, gates and recall. If an experiment needs
a custom harness, state precisely what it changes and preserve requests, versions and failures.
Do not hand-edit canonical knowledge to improve answers.

## 5. Accept the library at three levels

**Source integrity:** Were the expected materials imported faithfully, with their attribution,
order, time precision and media representation? A missing field here is not a reasoning failure.

**Knowledge fidelity:** Compare selected raw passages against ledger claims and overviews.
Check specific details, negation, plans versus outcomes, temporal relations, supersession and
omissions. Inspect small facts as well as attractive summaries. Gate checks establish provenance
addresses and structure, not that the cited text entails the claim. Closed volumes remain live
knowledge; an archive removes material from default retrieval. These are different operations.

**Usefulness:** Ask real questions, inspect `ask --sources`, and follow the answer's exact L0
citations even when retrieval supplied a compiled claim. Record answer/evidence degradation.
Use an explicit timezone-aware `--as-of` for historical questions; omitted means now. The
scaffold defaults to structured answers with separate answer text, kind and citations.

Locate the first failure before changing a model:

| Observation | Inspect / change first |
|---|---|
| The source lacks a fact or identity | Source adapter and normalization |
| L0 has it, but the canonical ledger omits or changes it | Contract, compile trace and model |
| The ledger is right, but the overview overstates it | Overview update and summarization |
| Correct evidence exists but never reaches the answer | Retrieval candidates, budgets and selection |
| The answer has the evidence but misreads it | Answer instructions and model |
| A success message hides failed work or invalid addresses | Framework implementation and reporting |

Change one responsible layer, preserve a concrete before/after example, then validate on
fresh material or a frozen test set. More context, more calls and a stronger model are
hypotheses to measure, not universal fixes.

## 6. Make changes maintainable

Keep strategy in `engine/` and commit intentional states; credentials and private material
stay outside version control. A contract edit governs future compiles, not old claims. Do not
sell a derived rebuild as recompilation: it restores indexes from authorities and replays
kept semantic boundaries. A different embedding model needs compatible dimensions and rebuilt
vectors; equal dimensions do not make two models' vectors interchangeable.

Keep the original library while evaluating a new contract in a fresh project. Use evolution
for an intentional restructuring, inspect its proposed diff, and adopt within the user's
authorization; `evolve step` keeps its draft by default. Do not use destructive reset as routine
onboarding or a substitute for migration reasoning.

Deliver the expectation, actual behavior, representative failures, changes, validation and
remaining uncertainty. Separate design limits, implementation defects, domain-contract choices
and model mistakes. A small, source-supported improvement is more useful than a broad claim
that the framework is now “better.”

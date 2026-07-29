# OPC 84d v2 evaluation probes

`evaluation-v2-truth.json` is the v2 evaluation truth asset.  It does not reuse
the rejected legacy manifest.  Every positive truth and negative control carries
an `evidence` array with an accepted group, source family, source id, authored
block ids, a verbatim anchor, and an observation date.  That metadata is for
auditability; the runtime evaluator continues to consume its established
`truth_id`, `value`, `status`, `question`, and `expected_truth_ids` contract.

## Accepted evidence map

| Evaluation boundary | Accepted anchor | Source family |
| --- | --- | --- |
| Four named read-only copies entered observation, not verification | G10 D29, `G10d29BatchDocSource`, blocks 01 and 06 | document library |
| The second replacement chain has its own confirmation but is not a combined pass | G26 D78, `G26d78ImSource`, message 04 | IM |
| A six-week oral extension has three conditions | G27 D80, `G27d80ExtensionMeetingSource`, turn 05 | meetings |
| Deletion confirmation/signature and payment remain open | G27 D81 mail 05 and G28 D84 mail 01 | email |
| Stop the project-wide platform; defer vendor approval; focus narrowly next cycle | G28 D82 blocks 02–03 and D84 block 04 | document library |

The initial-observation probe is deliberately dated **D29 / 2026-03-30**.  It
does not claim the four read-only copies existed on D28, and it does not turn
their receipt into a quality, attachment-readability, or completeness result.

Together these anchors exercise all four source families (`meetings`,
`document_library`, `im`, and `email`).  The extension-status retrieval case
crosses the D80 meeting conditions with the D84 email state; the platform/focus
case asks for the D82 decision alongside the D84 narrower direction from the
document library.  Every case's `source_families` is the union of the accepted
evidence families for its `expected_truth_ids`.  These cross-source probes are
intentional: they catch answers that recall one correct fragment while leaking an
incompatible conclusion from another source.

`as_of` describes the date intended by each retrieval question and keeps the
asset's chronology reviewable.  The evaluator currently scores against the
accepted current truth set; it does not select an historical corpus snapshot
solely from this field.  Therefore all factual, decision, commitment, and
constraint rows that participate in `current_only` remain marked `current`.

Negative controls reject five specific unsupported inferences: payment already
received, deletion confirmation/signature complete, project-wide platform
continuing, first-day material fully verified, and a combined pass for both
replacement chains.  This is deliberately a focused chronology/contradiction
suite, not a claim to cover every accepted authored sentence.

Before any live retrieval/evaluation, `load_v2_manifest()` fails closed unless
`qa/global.json` is `global_pass`, all 28 acceptance-freshness entries are
current, every G01–G28 deterministic report is `structural_pass` with no
findings, and the v2 asset identifies itself as `opc-84d-v2`.  Retrieval still
requires a user ingested from the frozen accepted corpus; this change neither
runs a real evaluation nor claims live retrieval quality.

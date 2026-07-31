"""compile: claim-level write mechanism + gate + mechanical event derivation.

architecture.md §1, §8. Pure functions; the canonical store goes through the
CanonicalStore port. Ports the Pneuma Compiler assets: claim-level citation/provenance, anchor
preflight + edit_claim/append_block (anchor_ops), mechanical Gate (gate), diff-derived
transitions (transitions). The runner drives a langchain tool loop over the claim-level
tools — there is NO whole-file write tool, and the model declares no transitions.

`rollover` is the one OTHER canonical write channel that lives here: size-triggered document
archiving with its own hard gate (`run_groom_gate`), reusing this package's block
segmentation, anchor assignment and shared gate checks so "what a claim is" is stated once.
It never runs inside a compile, and it changes neither compile's tools nor compile's gate.
"""

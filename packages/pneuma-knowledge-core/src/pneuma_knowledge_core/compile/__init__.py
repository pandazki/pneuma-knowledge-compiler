"""compile: claim-level write mechanism + gate + mechanical event derivation.

architecture.md §1, §8. Pure functions; the canonical store goes through the
CanonicalStore port. Ports the Pneuma Compiler assets: claim-level citation/provenance, anchor
preflight + edit_claim/append_block (anchor_ops), mechanical Gate (gate), diff-derived
transitions (transitions). The runner drives a langchain tool loop over the claim-level
tools — there is NO whole-file write tool, and the model declares no transitions.
"""

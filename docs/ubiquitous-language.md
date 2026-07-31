# Ubiquitous language

This file is the terminology authority for Pneuma Knowledge Compiler.

| Term | Definition |
|---|---|
| Source | An authoritative raw input such as a meeting, hierarchical note, IM conversation, email thread, or uploaded document. |
| Source contract | A versioned, provider-neutral input structure validated before normalization. |
| Provider adapter | An anti-corruption layer translating an external format into an official source contract. |
| Block | A stable paragraph-addressable slice of a source. |
| Canonical knowledge | Curated, versioned knowledge stored in a per-user Git repository and protected by compile gates. |
| Derived data | Rebuildable projections, lexical/vector indexes, annotations, manifests, and graph views. |
| Compile | The process that proposes, validates, salvages, and commits evidence-bearing changes to canonical knowledge. |
| Claim | The smallest identity-bearing knowledge statement with provenance and lifecycle. |
| Intake plan | The explicit treatment for semantic indexing and canonical compilation of a source. |
| Recall | Evidence-backed retrieval and answering over lexical, semantic, canonical, and raw access surfaces. |
| Briefing | A stable, reusable knowledge package for a sequence of related questions. |
| Live Context | A real-time feature that continuously retrieves and fuses relevant evidence from an incoming workstream, emitting zero or more mechanically gated context suggestions without requiring an explicit question. |
| Evolve | A forward-only strategy upgrade that rebuilds derived data without rewriting canonical history. |
| Strategy | A versioned domain policy defining relevance, privacy, document families, and compilation behavior. |
| Synthetic journey | Clearly labeled fictional data used to exercise the complete product workflow. |

## Vocabulary boundary

Only terms defined by this repository's public product contract may name product concepts. External product names, device-specific assumptions, unrelated application names, non-synthetic user identifiers, and foreign package prefixes must not appear in public artifacts.

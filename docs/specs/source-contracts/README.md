# Pneuma source contracts

The JSON Schemas in this directory are the public, provider-neutral input contracts for
Pneuma Knowledge Compiler. They are the single source of truth for source adapters.

| Contract | Canonical unit | Real adapter | Mock adapter |
|---|---|---|---|
| `meeting/v1` | one meeting transcript | Zoom WebVTT + recording metadata | canonical JSON |
| `document-library/v1` | one hierarchical library manifest | Obsidian vault directory | canonical JSON |
| `im/v1` | one instant-message archive | Slack JSON export | canonical JSON |
| `email/v1` | one email archive | RFC 5322 EML/mbox | canonical JSON |

Provider adapters are anti-corruption layers: they translate external formats into these
contracts and never leak provider fields into the compiler. The canonical JSON mock
adapter validates exactly the same schemas, so mock and real imports have constraint
parity.

## Invariants

1. `schema` is versioned and identifies exactly one contract.
2. Provider-native IDs remain stable inside the import so citations can be replayed.
3. Times are RFC 3339 timestamps with an explicit offset.
4. Owner identity is declared by the importer and is never inferred from message text.
5. Source text is immutable evidence. Corrections arrive as a new import.
6. Unknown optional metadata is allowed only inside a named `metadata` object.
7. Obsidian configuration, plugin code, dotfiles, and files outside the selected vault
   are never imported.

## Versioning

Adding an optional field is backwards-compatible inside `v1`. Renaming/removing a field,
changing identity semantics, or changing the citation unit requires a new schema version.

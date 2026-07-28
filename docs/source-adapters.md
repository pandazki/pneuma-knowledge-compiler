# Official source adapters

Pneuma Knowledge Compiler treats external formats as replaceable inputs, not domain
models. Every provider adapter translates into one of four versioned canonical contracts
before any content reaches the compiler.

| Source | Canonical contract | Real adapter | Mock adapter | Citation unit |
|---|---|---|---|---|
| Meeting | `pneuma.source.meeting/v1` | Zoom recording metadata + WebVTT | canonical JSON | meeting |
| Document library | `pneuma.source.document-library/v1` | Obsidian vault directory | canonical JSON | note |
| IM | `pneuma.source.im/v1` | Slack JSON export directory or ZIP | canonical JSON | conversation |
| Email | `pneuma.source.email/v1` | RFC 5322 EML directory/file or mbox | canonical JSON | thread |

The public JSON Schemas live in [`docs/specs/source-contracts`](specs/source-contracts).
Runtime models additionally enforce cross-record identity references, safe vault paths
and timezone-aware timestamps.

## Why these adapter shapes

- Zoom cloud recording transcripts are exposed as WebVTT transcript files.
- An Obsidian vault is a normal filesystem folder; properties are YAML frontmatter, and
  internal links can use wikilink or Markdown syntax.
- Slack exports use workspace metadata JSON plus per-conversation, per-day message JSON.
- Email input follows the RFC 5322 message format and MIME attachment conventions.

The implementation follows the official format descriptions:
[Zoom meeting APIs](https://developers.zoom.us/docs/api/meetings/),
[Obsidian properties](https://help.obsidian.md/properties),
[Obsidian internal links](https://help.obsidian.md/Linking%20notes%20and%20files/Internal%20links),
[Obsidian vaults](https://help.obsidian.md/Files%20and%20folders/Manage%20vaults),
[Slack export format](https://slack.com/help/articles/220556107-How-to-read-Slack-data-exports),
[Slack conversations.history](https://api.slack.com/methods/conversations.history),
[RFC 5322](https://www.rfc-editor.org/info/rfc5322/), and
[RFC 2045](https://www.rfc-editor.org/info/rfc2045/).

## API

Post a canonical contract to:

```text
POST /v1/users/{user_id}/sources/import
Content-Type: application/json
```

The response contains a list because a document library, IM archive or email archive
expands into its natural citation units. Every new unit is persisted to L0, then queued
for L1/L2 indexing and L3 compilation.

## Web import

The Web workbench exposes the same four canonical contracts as its primary import
surface. A user chooses Meeting, Document library, IM or Email, then uploads or pastes
one JSON contract. The client must:

1. parse JSON locally and reject an invalid document before any request;
2. verify that the contract `schema` matches the selected source kind;
3. submit the unchanged object to `POST /sources/import`;
4. render every returned source because one bundle may expand into several citation
   units.

The deprecated free-form conversation endpoint is not a product-facing import option.
Provider-native formats remain the CLI adapter boundary; the Web surface consumes their
provider-neutral canonical output.

## CLI

The provider CLI performs translation, canonical validation and ingestion:

```bash
# Canonical mock JSON
uv run python examples/import_source.py mock \
  examples/data/opc-demo/sources/meeting.json --user u-opc-lin

# Obsidian vault (configuration, plugins, hidden files and symlinks are ignored)
uv run python examples/import_source.py obsidian /path/to/vault \
  --user u-me --library-id my-vault --title "My vault"

# Slack export directory or ZIP
uv run python examples/import_source.py slack /path/to/slack-export.zip \
  --user u-me --owner-user-id U012345

# EML directory/file or mbox
uv run python examples/import_source.py email /path/to/mail \
  --user u-me --owner-address me@example.com

# Zoom WebVTT plus recording metadata JSON
uv run python examples/import_source.py zoom /path/to/transcript.vtt \
  --metadata /path/to/recording.json --user u-me \
  --owner-address me@example.com
```

Owner identities are explicit CLI arguments or canonical fields. Adapters never infer
ownership by reading message text.

## Source presentation metadata

Normalized sources keep citable text in the ordered block sequence. Their `meta` envelope
also retains the provider-neutral fields required to present the original source shape:

- meeting start/end, participants, agenda and segment speaker/timestamps;
- vault path, frontmatter, tags, links and document timestamps;
- IM members plus message timestamps, thread ids, edits and reactions;
- email sender/recipient headers, reply relationships and attachment descriptors.

Message and transcript bodies are not duplicated into metadata. The Web source viewer
joins each metadata envelope to its block by normalized order, so clicking a displayed
item still fetches the exact L0 block. Provider-specific optional fields remain nested
under `metadata` / `archive_metadata`.

## Synthetic OPC demo

`uv run python examples/seed_demo.py` resets `u-opc-lin` and imports four canonical mock
files. The fixture currently expands to:

- 1 meeting;
- 5 hierarchical notes;
- 3 IM conversations;
- 2 email threads.

It then runs the complete keyless pipeline: 11 L0 sources, 22 index/compile jobs, 11
canonical documents, 22 claims and 11 Git snapshots. All content is synthetic.

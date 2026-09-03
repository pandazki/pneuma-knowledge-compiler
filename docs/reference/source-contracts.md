# Source contracts (v1)

**English** | [简体中文](source-contracts.zh-CN.md)

The official input boundary is five versioned, provider-neutral JSON contracts — meeting, document library, IM, email, owner dialogue. Anything that speaks one of them can feed the system; converters from concrete provider formats live outside the contract (see [Importing](#importing)).

- One payload, one `schema` discriminator: `pneuma.source.meeting/v1`, `pneuma.source.document-library/v1`, `pneuma.source.im/v1`, `pneuma.source.email/v1`, `pneuma.source.owner-dialogue/v1`.
- Validation is strict (`extra="forbid"`): unknown fields are rejected, not ignored. The authority is the Pydantic model set in [`ingest/source_contracts.py`](../../packages/pneuma-knowledge-core/src/pneuma_knowledge_core/ingest/source_contracts.py); the JSON Schema files in [`source-contracts/`](source-contracts/) mirror it for wire-level tooling.
- **Every timestamp must carry an explicit timezone offset.** A naive datetime fails validation.
- Ids must be unique within their scope. Two contracts declare a closed identity set and resolve every reference against it: `meeting/v1` (segment speakers and owner ids ⊆ `participants`) and `im/v1` (conversation members and senders ⊆ `users`). `email/v1` normalizes `owner_addresses` but declares no roster; `document-library/v1` and `owner-dialogue/v1` declare no identity set at all — a dialogue carries `owner_id` / `steward_id` in its envelope and shows the compiler a `role`, never an id.
- Every payload envelope carries a free-form `metadata` object for provider extras. Below the envelope it varies by contract: `im/v1` carries one on conversations, messages and images, `email/v1` on threads and messages, `document-library/v1` on documents, while `meeting/v1` and `owner-dialogue/v1` carry none below the envelope.

**Expansion.** One payload is a bundle that expands into sources at natural reference boundaries: a meeting stays one source; a document library becomes one source per document; an IM archive one per conversation; an email archive one per thread; an owner dialogue is one statement and stays one source. Source ids are content-addressed (sha256), so re-importing identical content deduplicates instead of duplicating.

## `pneuma.source.meeting/v1`

| Field | Type | Notes |
|---|---|---|
| `schema` | literal | `pneuma.source.meeting/v1` |
| `provider` | literal | `zoom` \| `mock` |
| `meeting_id`, `title` | string | non-empty |
| `started_at` / `ended_at` | datetime / optional | tz-aware; end must not precede start |
| `timezone` | string, optional | e.g. `Asia/Shanghai` |
| `owner_participant_ids` | list of string | ⊆ `participants[].participant_id` |
| `participants[]` | object | `participant_id`, `display_name`, `email?` |
| `agenda` | list of string | optional, default `[]` |
| `segments[]` | object, ≥1 | `segment_id`, `speaker_id` (⊆ participants), `started_at` (tz-aware), `ended_at?`, `text` |
| `metadata` | object | free-form |

## `pneuma.source.document-library/v1`

| Field | Type | Notes |
|---|---|---|
| `schema` | literal | `pneuma.source.document-library/v1` |
| `provider` | literal | `obsidian` \| `mock` |
| `library_id`, `title` | string | non-empty |
| `documents[]` | object, ≥1 | ids and paths unique (paths case-insensitively) |
| `metadata` | object | free-form |

Each document: `document_id`, `path`, `title`, `content`, `frontmatter` (object), `tags` (unique), `links[]` (`target`, `label?`, `embedded`), `created_at?` / `modified_at?` (tz-aware), `metadata`. `path` must be a safe relative vault path — no absolute paths, no `..`, no dot-prefixed components.

## `pneuma.source.im/v1`

| Field | Type | Notes |
|---|---|---|
| `schema` | literal | `pneuma.source.im/v1` |
| `provider` | literal | `slack` \| `mock` |
| `archive_id` | string | non-empty |
| `owner_user_ids` | list of string | ⊆ `users[].user_id` |
| `users[]` | object | `user_id`, `display_name`, `email?`, `is_bot` |
| `conversations[]` | object, ≥1 | see below |
| `metadata` | object | free-form |

Each conversation: `conversation_id`, `conversation_type` (`channel` \| `dm` \| `group_dm`), `title`, `member_ids` (⊆ users), `messages[]` (≥1, ids unique), `metadata`. Each message: `message_id`, `sender_id` (⊆ users), `sent_at` (tz-aware), `text`, `thread_id?`, `edited_at?`, `reactions[]` (`name`, `count ≥ 1`), `images[]`, `metadata`.

**Image scope in v1.** Images are the first supported native-media type and currently exist only on IM messages. An image declares a unique `image_id`, a supported `mime_type` (`image/jpeg`, `image/png`, `image/webp`, `image/gif`), and an immutable `source`: either canonical base64 bytes or a public HTTPS URL, always paired with the expected SHA-256. Import verifies size, digest, and the bytes' image signature before placing the original in private S3-compatible L0 storage. Optional `derived[]` entries are explicitly labelled `caption` or `ocr` text and name their `producer`; they supplement the original and never replace it.

The image belongs to the message's ordinary normalized block. Consequently a claim keeps the existing citation form, such as `[cite: <source-id> ¶7]`, and that one locator resolves both the message text and its images. In `caption` compile mode the model receives labelled derived text only, and compilation fails loudly if any image has neither caption nor OCR. In `native` mode it also receives verified image content blocks. `auto` uses the active model profile and falls back to `caption` if image capability is unknown. Fast recall applies the same caption/native distinction to images overlapping its selected raw windows, so an image fact can still be answered with the original block citation even when the compile contract did not elevate it into a canonical claim. Audio, video, generic files, meeting media and email attachment bodies are not native-media inputs in this schema version.

Frozen knowledge-base snapshots server-side-copy every referenced object into the snapshot tenant before becoming ready. An image-bearing `prebuilt/` library likewise ships each original at `media/sha256/<first-two>/<sha256>` beside `l0.jsonl.gz`; restore verifies digest, size and signature, writes it under the target tenant, and retargets the L0 manifest. Missing media rejects the restore before canonical or L0 rows are written.

## `pneuma.source.email/v1`

| Field | Type | Notes |
|---|---|---|
| `schema` | literal | `pneuma.source.email/v1` |
| `provider` | literal | `rfc822` \| `mock` |
| `archive_id` | string | non-empty |
| `owner_addresses` | list of string | normalized (trimmed, casefolded), unique |
| `threads[]` | object, ≥1 | thread ids unique; message ids unique **across all threads** |
| `metadata` | object | free-form |

Each thread: `thread_id`, `subject`, `messages[]` (≥1), `metadata`. Each message: `message_id`, `sent_at` (tz-aware), `from` (`{address, display_name?}`, address normalized), `to[]`, `cc[]`, `subject`, `text`, `in_reply_to?`, `references[]`, `attachments[]` (`filename`, `content_type`, `size_bytes ≥ 0`, `content_id?`), `metadata`.

## `pneuma.source.owner-dialogue/v1`

What the library's owner said to the steward, as an ordinary source. The owner acts on the library only by speaking, so a correction, an instruction or an addition arrives as evidence like any other evidence — L0 verbatim, L1/L2 unconditional, cited `[cite: <source-id> ¶n]` exactly as a chat message is, and reaching canonical only through an ordinary compile and the citation gate. There is no owner write path, no citation grammar of its own and no gate rule of its own.

| Field | Type | Notes |
|---|---|---|
| `schema` | literal | `pneuma.source.owner-dialogue/v1` |
| `provider` | literal | `console` \| `mock` |
| `dialogue_id` | string | non-empty |
| `owner_id` | string | the owner's id in the application's own scheme |
| `steward_id` | string, optional | the steward's id, when the application names one |
| `turns[]` | object, ≥1 | `turn_id` (unique), `role` (`owner` \| `steward`), `said_at` (tz-aware, non-decreasing), `text` (non-blank); **at least one turn's `role` is `owner`** |
| `metadata` | object | free-form |

**At least one turn must be the owner's, and it must say something.** The standing of this contract is that the subject the library is about spoke for themselves — that is what the normalizer labels, what the compile task's per-source line names, and what earns the payload full canonical treatment. A dialogue of steward turns alone is a document the steward wrote about the owner, and compiling it as the owner's own statement would let steward-written text become the owner's canonical knowledge. A blank owner turn meets the rule as a formality and nothing more: the dialogue is still materially steward-only, and an empty turn cannot become a block anything can cite. So a blank turn of EITHER role is refused outright, naming the turn and its role, rather than filtered away — a payload that declares a turn nobody spoke believes something this contract does not. Both are refused at the contract, and the import form disables submit until a non-blank owner turn is written.

**Order is meaning, so it is validated rather than repaired.** Every other contract sorts what it is given — a provider archive's order is an artefact of the export. A dialogue's order IS its content: a sentence that qualifies the one before it stops qualifying it once the two are swapped. A payload whose `said_at` goes backwards is therefore rejected, not sorted.

**Normalization.** One block per turn, labelled by ROLE (`Owner:` / `Steward:`, from the prompt catalog). `owner_id` / `steward_id` are the application's own ids and stay in the source's `meta` envelope beside the turn ids, rejoined to blocks in normalized order like every other contract's parallel metadata — they never appear in the text a model reads. Sections are cut by the subject's calendar day, and the statement's own day becomes `meta.occurred_on`. The intake proposal is full canonical treatment with full semantic indexing: this is the one material whose author is the subject the library is about, and a statement the compile never reads is a correction that never lands.

**The kind is stated by the framework, the judgement by the contract.** The blocks read like a transcript and are not one, so the compile task's per-source line names the kind — the owner speaking to this library directly, their own words, not a record of an event. What the statement DESERVES — an `edit_claim`, a `supersede_claim`, a new page — is the compile contract's judgement and is deliberately absent from that line.

## Invariants and versioning

- **Source text is immutable evidence.** A correction arrives as a new import, never as an edit to what was already ingested.
- **Owner identity is declared by the importer** (`owner_participant_ids` / `owner_user_ids` / `owner_addresses` / `owner_id`), never inferred from message bodies.
- **Versioning**: adding optional fields inside `v1` is backward-compatible; renaming or removing fields, changing identity semantics, or changing the citable unit requires a new schema version.
- The `meta` envelope keeps provider-neutral presentation fields (meeting times/participants/agenda, vault paths/frontmatter/tags/links, IM members/threads/edits/reactions, mail addresses/reply chains/attachment descriptions) — **but body text is never copied into metadata**; readers rejoin metadata to blocks in normalized order, so every item resolves to an exact L0 block.
- Provider adapters are an anti-corruption layer, and the `mock` (canonical JSON) adapter validates the exact same schema — a mock import exercises the same constraints as a real one. The Obsidian adapter never imports vault configuration, plugin code, dotfiles, symlinks, or anything outside the vault.

Upstream formats the shipped adapters were written against: Zoom meeting transcripts, Obsidian properties/internal links/vaults, Slack exports and `conversations.history`, RFC 5322 (mail), RFC 2045 (MIME).

## Importing

- **HTTP**: `POST /v1/users/{uid}/sources/import` with the bare contract payload as the body. The service materializes declared images before normalization. The response reports the matched `contract_schema` and one entry per expanded source (see [http-api.md](http-api.md)).
- **Programmatic**: `parse_source_contract(payload)` validates. Image-bearing callers first materialize images through `materialize_contract_images(...)`, then pass that result as `materialized_images` to `normalize_source_contract(...)`; text-only contracts normalize directly.
- **From real provider exports**: `scripts/ops/import_source.py` converts and imports in one step — `--provider {mock, obsidian, zoom, slack, email}` covering canonical JSON, an Obsidian vault, a Zoom VTT transcript, a Slack export zip, and RFC-822 mail.

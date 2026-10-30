# Fold attention in the personal edition

**English** | [简体中文](fold-attention.zh-CN.md)

Status: experimental integration. The Fold skill has preliminary judgment evaluations, not
production quality guarantees. This feature adds an independent consumer to the personal
edition; it changes no ingestion, compile, gate, canonical lane or derived rebuild behavior.

## Purpose

The board supports long-chain reflection and future planning over a knowledge library that
lags behind life. Root items are persistent projects or themes; concrete events are supporting
detail unless unusually consequential. A cited reflection connects the period's meaning,
direction changes, cross-cutting tensions and questions for the next phase. Observations and
inferences stay distinct: a planned pivot needs a recorded goal or reason; silence never proves
inactivity or a personal failing. Previous reflections are supplied to the next round, with
provenance retained. The model can reorganize earlier task-level roots without claiming completion.

## Boundary and execution

Each personal engine supervises a separate `pkc_personal.attention.worker` process. A library-local
file lock permits one attention worker. The process reads committed Git objects using
`git --no-optional-locks show`, never working-tree files, and owns only
`<library>/attention/attention.sqlite3`. A separate PostgreSQL connection reads dated L0 Owner
turns through the time projection, with transaction read-only enforced by PostgreSQL and a
15-second statement timeout. Every join and query is bound to this library tenant. Collection
identity comes from completed kept observation lines, without acquiring the collection writer lock. Its polling, model failures and backoff are separate
from the knowledge job queue. Engine shutdown cancels the sidecar and its active executor;
a parent monitor handles an abruptly killed engine. Shared machine resources and provider
quota remain shared: independence does not promise zero resource contention.

The worker uses the library's selected Codex/Claude Code backend or its API recall model.
Coding-agent calls run in a temporary directory without the library's Steward skill. Codex
uses read-only sandboxing with shell, unified exec, JavaScript execution, apps and multi-agent
features disabled, web search disabled, and user config/rules ignored. Claude uses an empty
tool set, empty strict MCP configuration and no local setting sources. No compile executor,
`pkc draft`, canonical adapter write method or task-execution capability is provided. Calls
have a 180-second deadline; a batch gets at most two validation repairs. This integration
requires CLI support for these flags and fails closed if an installed CLI rejects them.

Attention's user ID is the library bound to the serving engine, never a request-selected tenant.
The console only embeds it for that engine's own profile. Routes reject nonlocal hosts and
cross-origin writes. The tray embeds only local engine pages and grants them no Tauri capabilities.

## Triggers and kept records

Default settings: enabled, 300-second fixed batch window, five changed knowledge versions,
300-second minimum invocation interval, six-hour quiet review. Both the window and count can
trigger a run; continuous input cannot move the window start. All calls, including explicit
review and notes, respect the minimum interval. A quiet review is emitted only when there is
no pending knowledge. Its signal states that external collection coverage is unknown.

The durable observation cursor is separate from the pending document set. A restart retains
both. A run consumes only its captured documents on acceptance; new commits arriving during
a call are observed next poll. Recent changes are considered first on bootstrap. At most 16 documents enter a packet, each
carrying its last commit time (not a claim about when its underlying events happened). Each prompt excerpt is
bounded to 16,000 characters and marked truncated when applicable; full supplied documents
are retained as evidence. Remaining documents stay pending. This initial integration consumes
canonical Markdown, excluding archived paths and contract machinery. The separate dated landscape covers original agent-session Owner turns, including material
not yet compiled; other channels remain unknown. After rewritten Git history it re-observes the live document set.

The landscape defaults to 14 days, configurable from 7 to 90. Original source dates determine
placement, never ingest/compile dates. Native turn IDs deduplicate incremental exports. Counts
measure recorded involvement, not work hours; a zero is missing observations. At most 20,000
turns are read, with truncation declared. The model receives up to 96 temporally distributed
first/last Owner-turn samples across the top ten projects, each capped at 1,200 characters and
linked to its exact source block. The complete daily aggregate is supplied separately. Missing
time projection/DB coverage produces an explicit unavailable landscape, not a fabricated river.

The pinned Fold kernel checks budgets, identity, operations, patches, annotations and retries.
New items must cite supplied canonical or L0 references; all new references are checked against
supplied evidence or existing admitted references. This checks provenance, not semantic entailment.
Silence does not mechanically lower weights: judgment may lower, keep or increase them under
Fold's time-signal rules. A no-change check is a saved frame without a fabricated item update.

SQLite transactions atomically save the accepted Fold snapshot, trigger, receipt, evidence,
head, reflection, landscape and judgment SHA-256. Reflection blocks require nonempty text
and at least one reference resolving to supplied or previously admitted evidence. Frames are append-only records of actual attention decisions,
not knowledge authority and not reconstructed by `rebuild_derived`. Historical projections
retain their original time. An optimistic generation check prevents a late model response
from overwriting an Owner note. Failures retain the previous board and pending inputs, with
exponential retry from five minutes to six hours. Failed provider output is not exposed in UI.

## Surfaces

The personal engine serves one implementation at `/home/attention/view`, embedded in the
920-point tray (650px board viewport) and console. Settings are shared per library.
The initial view is the theme atlas; the river is an optional perspective, not a prescribed
default. Controls and dates lead directly into the graphic. Cited reflection appears once below,
without introductory slogans or repeated design rationale.

- **Project river**: original source-time involvement across the selected period, stable project
  colors, explicit observation gaps and weekly totals. It reconstructs recorded activity, not prior judgments.
- **Attention atlas**: proportional project/theme areas and actual unallocated budget; details
  and child themes can be explored without making the root a task list.
- **Living field**: the original Fold C WebGL2 drop shader and layout solver, with Canvas2D
  fallback, bounded transitions, reduced-motion handling and quieter threads as small beads.
- **Review mosaics**: 64-cell maps of each actually saved review, on a shared scale.
- **Thread lines**: stable identities through saved reviews, renamed themes and changing shares;
  diagonal joins appear only for explicitly recorded merges.
- **Give & take**: balanced released/gained attention across adjacent reviews, including free
  space, on a common scale. No invented causal pairing of a donor and recipient.

Each theme exposes its reason, pinned evidence, supporting details and Owner notes. Reflection
paragraphs link to their saved evidence. Notes are Fold feedback only and do not execute tasks
or implicitly enter canonical. Source samples may be excerpts; recorded evidence stays as supplied.

The fixed time machine steps, scrubs and plays saved frames, pages into earlier records, and
returns to now. Historical frames preserve their original interpretation and landscape read-only;
no attention history is invented before enablement. This is independent of the console's canonical
snapshot picker. Settings expose six visual forms, look-back period, batching, minimum interval
and quiet review. Updated horizon applies to the next review. Disabling automatic review retains
history; explicit review still works. UI reads never invoke a model or imply an item was read.

## Upstream and verification

The vendored kernel is from the Owner's Fold repository, commit
`2ac7f10b98920a1e07f87a99fd485778f2bcad3f`, upstream file SHA-256
`e8865faa01506c67fd27c88524d8fa607dd3bb0ef9acbd380defac811b744e46`.
Developer comments/docstrings were removed or translated, and trailing whitespace was trimmed.
Runtime behavior is preserved by the AST pin test.
The complete upstream Fold v2 guide is packaged unchanged as `fold-v2.txt`; a bilingual host
contract adapts transport and judgment purpose to this bounded retrospective evidence packet.
The C shader/layout is vendored from `prototype/variants/c-field.mjs` at the same upstream revision.
These contracts are experimental and hashed per accepted frame.
There is no runtime dependency on another application checkout. Upgrading requires explicit
review of the upstream contract and integration tests, not an automatic repository pull.

Keyless tests cover debounce, quiet review, recovery, immutable history, dirty-tree safety,
failures, bounded backlog, concurrent knowledge and notes, budget repair, provenance and
cross-library isolation, original-date aggregation, duplicate export removal, bounded retrospective
sampling, read-only tenant-scoped SQL, cited reflections and six-view preferences. Browser checks
exercise all views, history, evidence, failed-note recovery, zoom and both renderers. They do not establish judgment quality on the Owner's real material.

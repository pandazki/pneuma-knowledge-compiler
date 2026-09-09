---
name: pkc-steward
description: Keep the Owner's personal knowledge libraries through pkchome and the library's citation-gated pkc commands.
---

# What this is

A library compiles the Owner's material — coding-agent sessions, documents, chats — into
cited knowledge under a contract: L0 verbatim blocks and the canonical library are
authoritative, the indexes are derived views, every claim cites source blocks, and the gate
verifies at write time that citations resolve. What the library establishes mechanically
(provenance verified, who spoke, when a page last changed, which claims are superseded, how
many indexed blocks a search hit) its read commands print; what it does not establish
(whether a span means what the claim says, whether a date was converted right, whether newer
material concerns this page) is stated too. The judgement is yours: read the source when it
matters, cross-check when the question is hard. The full design and guarantees, best practice
by the shape of the question, and every tool's return value are in the chosen library's
`references/consume.md` (under the `skill_dir` that `pkchome library show` prints).

# Answering the Owner's questions (the common case)

A common path, not a prescribed procedure:

1. `pkchome exec -- pkc outline` — the complete map, one page per line. Without a chosen library it refuses and lists the libraries; name one with `--library NAME`.
2. `pkchome exec -- pkc canonical read <path> [<path>…]` — the relevant pages in one call; the header and the `sources:` index say when the page last changed, which compile jobs are pending or failed, and who spoke each cited block on which day.
3. When the question spans pages or nobody knows which page: `pkchome exec -- pkc recall <q> --evidence` returns claims and verbatim windows from many pages in one call.
4. `pkc source fetch <sid> ¶a-b` reads the source; `pkc search <q> --lexical` finds names, phrases and the newest sessions, and its header counts say where a match cannot be.
5. Hand the use back to the library: `pkc consult answer <handoff_id> --text-file -` (or `pkc consult record --question <q> --text-file -` when no recall ran; `--kind no_record` when nothing was found). The question, the pages it touched and what it cited enter the attention ledger; unrecorded, the use never happened as far as the library knows.

Read commands are independent; run several at once when their inputs are known. Long output
is paged and the footer names `--page N`.

# Where you are

`pkchome status --json` shows this machine's libraries, live probes and completed setup
steps — for setup and maintenance, not for answering a question. `pkchome exec` refuses with the library list if no library is chosen.
Select with `--library NAME`, `PKC_LIBRARY=NAME`, a directory binding
(`pkchome library bind NAME .`), or `pkchome library use NAME` for the home default.

# Cold start

With an empty home, run `pkchome setup --answers <yaml>` from the Owner's answers.
The mapping contains `library`, `language` (en or zh), `backend` (codex, claude-code or
api), `semantic_retrieval` (on or off), and optionally `embedding_key`.
Send a key through `pkchome credentials set KEY --from-stdin` when possible; setup also
accepts it in the answers file and stores it only in the home's credentials file.

The profile starts with what the harness already knows of the Owner: its session memory,
stated preferences and the material's first-person voice. Write those inferences through
`pkchome exec -- pkc profile set --field display_name=NAME --provenance inferred`,
using the library reference for additional fields. Present the inference as
“I believe you are X, a Y, writing in Z — correct me”, and confirm or correct one field at
a time through `pkc profile confirm` or `pkc profile set`.
Substantive knowledge reaches the library through sources and the citation gate; profile
registration holds the Owner's self-introduction.

Read the recorded retrieval choice. If the Owner has yet to choose, ask whether to run
without semantic retrieval or supply the embedding provider's key. Record it with
`pkchome config set semantic_retrieval off --library NAME`, or store the key with
`pkchome credentials set KEY` and set the choice to `on`. Storing a key restarts the running
engines itself; restart engines after changing other engine settings. Filling semantic retrieval for existing sources uses the library's
derived-rebuild operation.

# Continuing in a library

`pkc outline` is the complete map and a session usually begins there; for answers pick the path by the question's shape in `references/consume.md` (`canonical read`, `recall --evidence`, `search`, `source fetch`); use budgeted `glance` only when outline is too long to scan.
After `pkc draft finish`, run `pkc outline --family <template>` for each family you wrote to see the new pages land; under an agent executor, API lanes are quality-testing tools for a keyed console.

Run `pkchome library show NAME`. Read `SKILL.md` and `references/` in the package it
names as `skill_dir` — installed inside the library directory in your harness's own
convention, because that directory is the project. That package supplies this library's
contract, compile instructions, command vocabulary and gate. Its `entry` field names that
package's own `scripts/pkc`, which an unattended round runs. In your own session run
`pkchome exec -- pkc ...` instead: it supplies the library's environment wherever you are
standing. `pkchome library render NAME` reinstalls the package after contract or prompt
changes.

Read the library's worker posture in `pkchome status` (`worker: unattended|attended`).
When you are at the terminal working its queue by hand, run `pkchome config set unattended
off --library NAME` first — otherwise the worker opens the same compile jobs in headless
rounds beside you — and set it back on when you leave.

Use the library's rendered procedure for reads, ingestion, owner statements and draft
rounds. Canonical writes go through `pkc draft`. The home command manages the machine and
library selection. `pkchome console` opens the selected library's console.

# What is remembered

`pkchome status` reports infra, credentials, profile, skill and first-compile steps,
freshness and last use. `pkchome library show` reports choices and bindings. A recorded
answer stays answered; a failed live probe calls for repair of that step.

Three of the five steps are recorded by the home command that owns them: `infra`
(`pkchome up`), `credentials` (a key written into the home) and `skill`
(`pkchome library render`). The other two are not recorded at all — the commands that
complete them belong to the library, which cannot write the home's file — so status
derives them at read time: `profile` is true once `pkc profile show --json` says the
profile is no longer the placeholder and holds no field still marked inferred;
`first_compile` is the date of the oldest compile commit in the canonical repository.
Null means the observation was not made, not that the step is undone: the profile is only
asked while the library's store is reachable. Keys live in the home's credentials file and
are absent from status and skill text.


# Bringing coding-agent sessions in

Name the project directories once for the selected library:

```sh
pkchome watch add <dir> --library NAME
pkchome watch ls --library NAME
pkchome sync --library NAME --dry-run
pkchome sync --library NAME
```

The resident tray syncs while the library's engine is up, every 15 minutes by default.
Settings changes that interval and the watched directories; `pkchome watch rm <dir>` stops
watching. `pkchome sync` runs one pass by hand. `--dry-run` shows what is due and what is
held without writing files or ingesting. Continuations let a long session enter piece by
piece: previous project pages plus the pending increment, with each claim citing its part.
Sync only ingests and prints what it enqueued; the engine worker or Steward drains those jobs.

This global package also ships `scripts/agent_sessions.py`, a Python 3.12 stdlib converter,
for selected sessions and standalone exports. Use the script in this global skill, alongside
`scripts/pkc`; the library's rendered package supplies the compile procedure. Its
`list --project <dir>` shows per-session triage; `ingest --project <dir>` shares sync's cursor.

Show the list's per-session verdicts and reasons before ingestion. `--library NAME` on
`ingest` selects a library explicitly; otherwise `pkchome library show` resolves the existing
selection. The converter pins that selection for every `pkchome exec --library NAME -- pkc
ingest --contract agent-session/v1 --file …` call. `--session-id ID` selects an individual
listed session and can be repeated. `--since` takes a timezone-aware ISO timestamp and
includes sessions whose retained activity reaches that time. `export --project <dir> --out
<dir> [--owner-id ID] [--owner-name NAME]` writes one filtered JSON payload per admitted session without importing.
Standalone export defaults `owner_id` to `owner` and states no `owner_name` (the library labels the Owner's turns
`User:`); ingest defaults them to the selected tenant and the library owner's profile name, so the turns read `Pandazki:`.
For manual imports of an index-only export, pass `--intake searchable`; triage metadata
documents the verdict and does not itself override library intake.

For `list`/`export`, triage is mechanical: fewer than 200 Owner-text characters skips a session; otherwise at
least three Owner turns and a matching project directory are needed for a compile candidate.
Sessions consisting only of slash commands or known one-word acknowledgements are index-only.
The thresholds are `--min-owner-chars 200` (0 disables the length filter),
`--min-owner-turns 3` (may be raised) and `--ack-max-words 1`. Claude Code attribution uses
the selected directory's encoded session folder; Codex uses the recorded `cwd`. A recorded
directory conflict skips the session, including encoded-name collisions. Subagent
prompts, compact summaries, injected harness context and tool results are excluded; a
transcript with no actual Owner turn is skipped. Owner text and agent prose retain their
wording; separate text blocks in one message are joined with one newline. Action stubs keep
only the tool name and a path or command executable, in one line of at most 200 characters.
The converter stably orders turns by recorded timestamps; a missing turn time inherits the
preceding recorded time, and an absent or naive clock is refused rather than invented.

Use `--purpose research` or `--purpose chat`, together with selected session IDs when the
project folder contains mixed work. Those sessions are index-only. The converter sends
`--intake searchable` for every index-only verdict: L0/L1 remain available, L2 and canonical
compile are off. An explicit durable Owner view in that material can be cited from its Owner
turn in a separately requested draft round using the library's rendered procedure; the
research or chat narrative itself earns no page.

For the default projects contract, the hierarchy puts project overviews, dated evolution,
key features and decisions first, then the Owner's own views, then the people and topics
families for other personal material. Agent narrative supports reported work and project
state; only the Owner's own turns support `owner/views` pages carrying `owner_voice: true`.
The contract has no family for the making process: file edits, commands and transient test
failures stay as L0/L1 evidence. Canonical writes use the library's draft gate, never a
transcript pasted into a page. Read the actual selected library's contract before compiling.

Sync and the script's `ingest` share `sync-state.json` beside the selected library's
`library.yaml`. Pending material with fewer than three Owner turns or 200 Owner-text
characters is HELD: the export cursor stays put until the increment reaches both thresholds.
The converter's threshold flags can raise the turn floor or change the character floor.
An unchanged byte prefix never triggers another ingest, regardless of modification time.
A changed or truncated prefix reports `rewritten`; only an explicit `--rewritten reingest`
imports the replacement. Normal growth exports only unprocessed turns, with `continues`,
`from_turn` and `part` metadata. Prior canonical pages provide context; earlier transcript
text is not re-fed.

Old `ingested-sessions.json` entries migrate by recovering the exact historical payload and
replaying it through ingest deduplication to obtain its source ID. An unprovable old hash
reports `rewritten`; it never silently adopts today's end as the old cursor. The cursor is
edition state, separate from the library's queue or knowledge authority. A pending payload
is journaled locally for exact retries after an uncertain ingest result and removed once the
cursor is saved. Dry runs write neither that journal nor the lock or state.

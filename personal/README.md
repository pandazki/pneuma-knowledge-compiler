# PKC personal

[简体中文](README.zh-CN.md)

> Install the pkc personal knowledge library: run
> `curl -fsSL https://raw.githubusercontent.com/pandazki/pneuma-knowledge-compiler/main/personal/install.sh | sh`,
> then follow the instructions it prints last.

That sentence is for a coding agent, not for a terminal: paste it into Codex or Claude Code
and the agent installs the edition, reads the skill it installs, and continues from there.

One person's citation-backed knowledge libraries on one machine. `pkchome` manages a home
(`~/.pkc`, or `PKC_HOME`), shared Docker middleware and independently chosen libraries.
The installed library supplies `pkc`, including every canonical write through its draft gate.

## What the installer does

`install.sh` is idempotent — re-run it whenever. In order:

1. **`uv`** — installed from the official script when missing; `~/.local/bin` is put on PATH
   for the run.
2. **`pkc-personal`** — `uv tool install --force` from the pinned release. `PKC_RELEASE=<ref>`
   installs another ref; `PKC_SOURCE=<dir>` installs a local checkout of this directory.
3. **the `pkc` launcher** — written beside `pkchome` in the same bin directory
   (`exec pkchome exec -- pkc "$@"`). A `pkc` there that is not ours is refused, never
   replaced.
4. **the skill** — `pkchome skill install --force` for every harness whose directory exists
   (`~/.codex`, `~/.claude`).
5. **Docker** — a `docker info` probe. On failure it says where Docker Desktop or OrbStack
   comes from and stops with exit 3; nothing done above is undone, so a re-run continues.
6. **the console page** — `pkchome console install`. The wheel carries the built page only
   when it was built inside this repository, so otherwise it is downloaded from the
   `personal-console-v<version>` release and verified against the published sha256 before
   anything is written. Never fatal: an offline machine keeps everything above, and
   `pkchome console` fetches the page the first time it is opened.
7. **the desktop app** — with `PKC_DESKTOP=1` once a build is published; otherwise one line
   saying `pkchome tray` will tell where to get it.

Every step prints one `ok:` or `skip:` line, and the last lines name the installed
`SKILL.md` and the two commands to run next. `--quiet` prints only errors and that block.

## Commands

```
pkchome setup [--answers <file>] [--non-interactive] [--no-skill]
pkchome up | down | restart | console [install] | tray
pkchome status [--json] [--library <name>]
pkchome onboarding [--library <name>]
pkchome library create <name> [--from <name>] [--language en|zh] [--contract personal-projects|personal-knowledge|<path>] [--backend …]
pkchome library ls | show [<name>] | use <name> | bind <name> [<dir>] | unbind [<dir>] | render [<name>]
pkchome config get|set <key> [<value>] [--library <name>]
pkchome credentials set KEY [--from-stdin] [--no-verify]
pkchome env [--export] [--library <name>]
pkchome exec [--library <name>] -- <command…>
pkchome skill install [--backend codex|claude-code|all] [--force]
```

`register` and `forget` are v2 placeholders. `down` keeps middleware data.

The optional [PKC desktop tray](desktop/README.md) shows machine and library health,
searches with citations, and changes settings through `pkchome`. Install `PKC.app` in
`~/Applications` or `/Applications`, then run `pkchome tray`; if it is absent, the command
prints the release page. For development, use `cd personal/desktop && pnpm install`, then
`pnpm tauri dev`; build installers with `pnpm tauri build`. The tray observes your home
without an engine and uses each running engine's `/home/status` for detailed health.

Setup answers: `library: notes`, `language: en`, `backend: codex`,
`semantic_retrieval: off`; an optional `embedding_key` goes only to credentials; an optional
`owner:` mapping states profile fields the Owner has already given (`display_name`,
`occupation`, `role`, `industry`, `bio` — any of `pkc profile`'s fields), written as theirs.
A key for
the configured embedding provider is probed against it before it is stored — a rejected key
changes nothing (no file written, no engine restarted, the previous key kept), and
`--no-verify` stores one unchecked when the machine is offline. Setup
needs a terminal or `--answers`; `--no-skill` skips installation into detected harnesses.

Setup does not leave the profile blank. It reads what the machine already states about its
Owner — the account's full name, the system timezone, the interface language (the `language`
answer wins over it) — and writes those with `inferred` provenance, which `pkchome status`
refuses to count as a settled profile until the Owner confirms each one.
`pkchome onboarding` prints what is left to do: the inferred fields with their values and the
commands that confirm or correct them, the registration questions still unanswered — asked in
the Owner's own language — and the retrieval choice while it is undecided. Setup prints that
same block; the command is there for a Steward who arrives later — and when setup could not
write the inferred fields, `onboarding` writes them itself and says `seeded: <fields>` on its
first line, so the confirmation step is never missing from the list.

`config get|set` reads and writes one recorded choice per library (or the home defaults with
no `--library`): `backend`, `language`, `semantic_retrieval`, `embedding`, `unattended`, and
`model` / `reasoning_effort` — which model this library's compile and evolve rounds run and
how hard it thinks, instead of inheriting whatever your own global harness configuration
says. Codex honours both (`reasoning_effort` is one of `minimal`, `low`, `medium`, `high`,
`xhigh`); Claude Code honours the model only, because its CLI has no effort flag. Empty
leaves each to the harness. Changing either restarts the library's engine, because a
launcher reads its settings when it starts.

Choose a library with `--library`, `PKC_LIBRARY`, the nearest `.pkc` file in the current
directory or an ancestor, or the home current selection, in that order. No selection is an
exit-2 refusal. `env` intentionally prints secrets for your shell; status never does.

## Projects and coding-agent sessions

New libraries use the bilingual `personal-projects` contract: project overview, dated
evolution, key features and decisions, then the Owner's own views, with people and topics
for other personal material. Select the earlier contract with
`pkchome library create notes --contract personal-knowledge`, or pass a custom contract path.
`--from NAME` still inherits that library's contract unless `--contract` overrides it.

Say once what the library's scope is; the tray syncs the Claude Code and Codex sessions
inside it while the library's engine is running:

```sh
pkchome watch add /path/to/momo --library notes
pkchome watch add ~/Codes --recursive --library notes
pkchome watch add --all --library notes
pkchome watch ls --library notes
pkchome sync --library notes --dry-run
pkchome sync --library notes --json
pkchome watch rm /path/to/momo --library notes
pkchome watch rm --all --library notes
pkchome config set sync.interval_minutes 15
pkchome config set sync.enabled on
pkchome config set sync.exclude '/private/tmp/**,~/scratch/**'
pkchome config get sync.exclude
pkchome config set sync.min_owner_turns 5
pkchome config set sync.min_owner_chars 200
pkchome config set sync.ack_max_words 1
```

Setup answers can include `watch: [/path/to/momo]`. Each library records its own
`watch: [{path, recursive, harnesses: [claude-code, codex], since?}]` in `library.yaml`.
`watch add` accepts `--harnesses codex claude-code` and a timezone-aware `--since` to select
sessions with retained activity at or after that boundary.

An entry takes one of three scope forms. A directory is one exact project, as before.
`--recursive` makes it a prefix: every project at or below it, compared by path components,
so `/a/b` never admits `/a/bc`. `--all` records the literal `all` — every project either
harness has a session for, enumerated from the harness roots themselves rather than from a
list of directories, because opening the library to four hundred projects is a configuration
and not four hundred `watch add` calls. `watch rm <dir>` and `watch rm --all` remove by the
same key.

A scope that wide also reaches thousands of dead scratch directories, so `sync.exclude`
holds glob patterns matched against the resolved project directory, defaulting to
`/private/tmp/**`, `/tmp/**`, `/private/var/**` and `/var/folders/**`. `config set
sync.exclude` appends one pattern or a comma-separated list; an empty value clears them all.
Two exclusions are mechanical rather than patterns the Owner can remove: the home, and every
library's own directory — its engine, its canonical repository and its rendered package. A
project whose directory no longer exists is counted as `project_missing` and listed nowhere,
because under `all` there are thousands of them.

The Steward's own sessions are skipped entirely, neither indexed nor compiled. A session that
ran `pkc` or `pkchome`, or that stood inside the home or a library, is work ON the library,
and a library that ingested it would be compiling its own output. Those count as
`skipped_steward`.

The tray defaults to a 15-minute interval; Settings edits the interval, switch and watch list.
Dashboard shows the last sync and held count, with a “Sync now” button.

Sync only sends new parts through `pkchome exec --library NAME -- pkc ingest`. It never
compiles itself: ingest enqueues ordinary index/compile jobs, and the engine worker or
Steward drains them. Reports show scanned, new, increments, held, unchanged, rewritten,
ingested, skipped, skipped_steward and project_missing, with per-session details. Held
counts are separate from the library's queue; unchanged held sessions count in both fields.

The global skill also ships the stdlib `scripts/agent_sessions.py`: `list --project <dir>`
shows whole-session triage, `export --project <dir> --out <dir> [--owner-id ID]` writes
filtered JSON, and `ingest --project <dir> [--library NAME]` shares sync's incremental
cursor. `--session-id ID` selects particular sessions; `--purpose research|chat` makes those
index-only. Export defaults Owner identity to `owner`; ingest uses the selected tenant.
Manual imports of index-only exports need `--intake searchable`; metadata does not set intake.

Each pending increment needs three Owner turns and 200 Owner-text characters by default;
`sync.min_owner_turns` (floor 3), `sync.min_owner_chars` and `sync.ack_max_words` state what
this home asks for. Below either threshold an increment is HELD without advancing the
exported cursor, so later growth accumulates.
The converter's `--min-owner-turns`, `--min-owner-chars` and `--ack-max-words` still configure
its manual triage (turn floor 3, character floor 0, default acknowledgement limit 1 word).
Once the numeric thresholds are met, only slash commands/known acknowledgements and explicit
research/chat receive index-only treatment. Subagents and directory conflicts are excluded.
Owner words and agent prose remain verbatim; tools become bounded stubs, with arguments,
results, reasoning and injected harness context excluded. `list`/`export` retain their
whole-session rules: below the character threshold skips, below the turn floor is index-only.

`sync-state.json` beside `library.yaml` stores source IDs, the exported turn cursor and a
verified file prefix. Unchanged bytes never re-ingest because of mtime. Normal growth emits
only new turns with `continues`, `from_turn` and `part` metadata; previous canonical pages
supply context and claims cite their own part. Prefix changes or truncation report
`rewritten`; explicitly use `pkchome sync --rewritten reingest` to admit replacements.
Old `ingested-sessions.json` entries migrate by recovering their exact historical payload
and obtaining its source ID through ingest deduplication; an unprovable hash is reported,
never silently treated as today's end. Pending payloads are journaled for exact retries
following a crash or lost response. `--dry-run` writes nothing, including no lock or journal.
All of this is edition state; canonical still changes only through the library's draft gate.

## Where things live

```
~/.pkc/                     the home (PKC_HOME moves it)
  config.yaml               install, infra ports, defaults
  credentials               KEY=value, mode 0600 — never echoed by status or skill text
  current                   the library a session lands in when nothing else chooses
  infra/, run/, data/       the generated compose file, engine pids and logs, the volumes
  libraries/<name>/         library.yaml, engine/, canonical/, skill/
~/.local/bin/               pkchome (uv tool) and the pkc launcher beside it
~/.codex/skills/pkc-steward/, ~/.claude/skills/pkc-steward/    the global skill
```

## Uninstall

```sh
pkchome down                 # stop the middleware first; the data volumes stay
uv tool uninstall pkc-personal
rm -f ~/.local/bin/pkc
rm -rf ~/.codex/skills/pkc-steward ~/.claude/skills/pkc-steward
rm -rf ~/.pkc                # only when the libraries should go too
```

## Development

From the containing worktree, with `uv run --project personal`:

```sh
uv run --project personal pkchome setup --answers answers.yaml --no-skill
uv run --project personal pkchome library create notes --language en --backend codex
uv run --project personal pkchome exec -- pkc jobs
uv run --project personal pytest personal/tests -q
```

This is a standalone uv project with its own environment and committed lockfile. Its only
runtime library dependencies are the core and service distributions; edition contracts and
global skill texts ship as its own assets.

The console page is a built artifact, never source: an engine serves it from the wheel's own
`pkc_personal/console/dist`, from `PKC_CONSOLE_DIST` (a local build, for development), or from
`~/.pkc/console/<version>/dist` — the copy `pkchome console install` downloads from the
`personal-console-v<version>` release and verifies against its published sha256.
In this repository `scripts/personal_console_dist.sh` builds that directory and
`scripts/personal_console_release.sh` publishes it as one version's release asset.
`pkchome status` says which of the three this machine has.

Current seam limits: engine startup refuses a library version without worker tenant
filtering; a retrieval choice is recorded but only takes effect when the library exposes
`semantic_retrieval`; an engine decides at start whether it serves the console, so a page
fetched after the engine started is served from the next `pkchome restart`.

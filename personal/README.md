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
6. **the desktop app** — with `PKC_DESKTOP=1` once a build is published; otherwise one line
   saying `pkchome tray` will tell where to get it.

Every step prints one `ok:` or `skip:` line, and the last lines name the installed
`SKILL.md` and the two commands to run next. `--quiet` prints only errors and that block.

## Commands

```
pkchome setup [--answers <file>] [--non-interactive] [--no-skill]
pkchome up | down | restart | console | tray
pkchome status [--json] [--library <name>]
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
`semantic_retrieval: off`; an optional `embedding_key` goes only to credentials. A key for
the configured embedding provider is probed against it before it is stored — a rejected key
changes nothing (no file written, no engine restarted, the previous key kept), and
`--no-verify` stores one unchecked when the machine is offline. Setup
needs a terminal or `--answers`; `--no-skill` skips installation into detected harnesses.

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

Name project directories once; the tray syncs their Claude Code and Codex sessions while
the library's engine is running:

```sh
pkchome watch add /path/to/momo --library notes
pkchome watch ls --library notes
pkchome sync --library notes --dry-run
pkchome sync --library notes --json
pkchome watch rm /path/to/momo --library notes
pkchome config set sync.interval_minutes 15
pkchome config set sync.enabled on
```

Setup answers can include `watch: [/path/to/momo]`. Each library records its own
`watch: [{path, harnesses: [claude-code, codex], since?}]` in `library.yaml`.
`watch add` accepts `--harnesses codex claude-code` and a timezone-aware `--since` to select
sessions with retained activity at or after that boundary. Paths select exact projects.
The tray defaults to a 15-minute interval; Settings edits the interval, switch and watch list.
Dashboard shows the last sync and held count, with a “Sync now” button.

Sync only sends new parts through `pkchome exec --library NAME -- pkc ingest`. It never
compiles itself: ingest enqueues ordinary index/compile jobs, and the engine worker or
Steward drains them. Reports show scanned, new, increments, held, unchanged, rewritten,
ingested and skipped, with per-session details. Held counts are separate from the library's
queue; unchanged held sessions count in both fields.

The global skill also ships the stdlib `scripts/agent_sessions.py`: `list --project <dir>`
shows whole-session triage, `export --project <dir> --out <dir> [--owner-id ID]` writes
filtered JSON, and `ingest --project <dir> [--library NAME]` shares sync's incremental
cursor. `--session-id ID` selects particular sessions; `--purpose research|chat` makes those
index-only. Export defaults Owner identity to `owner`; ingest uses the selected tenant.
Manual imports of index-only exports need `--intake searchable`; metadata does not set intake.

Each pending increment needs three Owner turns and 200 Owner-text characters. Below either
threshold it is HELD without advancing the exported cursor, so later growth accumulates.
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

Current seam limits: engine startup refuses a library version without worker tenant
filtering; a retrieval choice is recorded but only takes effect when the library exposes
`semantic_retrieval`; the console is served only when a built artifact is installed under
`pkc_personal/console/dist`.

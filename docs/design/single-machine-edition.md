# The personal edition — an application over the library

**English** | [简体中文](single-machine-edition.zh-CN.md)

Status: design. Builds on [coding-agent-mode.md](coding-agent-mode.md) (the door, the skill,
the backends) and [steward-owner-visitor.md](steward-owner-visitor.md) (the roles).

## 1. The library and its applications

Pneuma Knowledge Compiler is a **library**: `pneuma-knowledge-core` and
`pneuma-knowledge-service` — the domain, the four levels, the door, the gate, the API
application, the worker loop, the `pkc` command and the adapters. Everything that installs
it and puts a face on it is an **application**. Until now there were two: the scaffold
project (its own stack, its own `.env`, its own processes) and the console web (`apps/web`,
a SPA over the API, started by a project's compose `console` profile).

This page adds the third: the **personal edition** — one person, one machine, a coding
agent as the whole interface, a tray icon as the glance, the console web when wanted. It is
an application in the strict sense the other two are, and it takes the strict form of one:

| | Scaffold project | Console web | Personal edition |
|---|---|---|---|
| lives at | wherever `init.py` wrote it | `apps/web/` | `personal/` (a future repository of its own) |
| depends on the library as | a workspace path or the framework repo | the API over HTTP | one line: `pneuma-knowledge-service @ git+…@<tag>` |
| infrastructure | one stack per project | none of its own | one stack per machine, under `~/.pkc` |
| libraries | one | whichever tenant the URL names | any number, tenants on one stack |
| the agent's entry | the skill installed into the project | — | one skill installed into the harness |
| processes | `app.py up`, `server.py`, `worker.py` | nginx | `pkchome up`: the middleware and one engine process |
| distribution | generated | a Docker image / a `dist` | git releases: a package and a desktop app |

The principle: **the library is one thing, an application is another, and the personal
edition is only ever a consumer of the library.** It imports two packages, it reads no file
of the framework repository, it copies no template out of `scaffold/`, it forks no source of
`apps/web`. What it needs from the library and the library does not yet offer is added to
the library as a library feature (§11), never as a private path.

## 2. Roles and motivations (the additions)

The roles are the frame's. The edition adds one Owner motivation about the install, one
about the glance, and keeps the three cold-start motivations the coding-agent page
introduced:

| | Motivation |
|---|---|
| O13 | **Start once, keep forever.** Set the machine up one time — infrastructure, a key, a name — and never answer the same question again, in any later session, in any directory |
| O14 | **One sentence to install.** The Owner already has a coding agent; pasting one sentence into it is the whole install, and the agent does the rest |
| O15 | **See it without asking.** Whether the library is up, whether the last compile landed, whether a key expired — visible at a glance from the menu bar, and fixable from there |
| S10 | **Know what is already here.** A Steward started anywhere finds the machine's libraries, checks what still works, and continues the right one instead of proposing a new one |
| S11 | **Bring what it already knows.** The Steward runs in the harness the Owner has used for months; its memory of the Owner is the profile's first draft, and the Owner corrects rather than fills in |

## 3. Stories

- **3.1 One sentence (v1).** The Owner has Codex (or Claude Code) and Docker. They paste
  the README's one sentence into the harness. The agent runs the installer; the installer
  installs `uv` if missing, installs the personal package from the release tag, installs the
  harness-level skill for every harness it finds, probes Docker, and ends its output with
  the agent's next step. The agent reads the skill, runs `pkchome status` — nothing — and
  `pkchome setup`: ports probed, `~/.pkc/config.yaml` written, the middleware and the engine
  started, the first library created (`pkchome library create notes`), and the two questions
  a cold start has (who the Owner is, in the form *"I believe you are X, a Y, writing in Z —
  correct me"*, and whether to run without semantic retrieval or with a key). Ten minutes,
  two questions, one sentence typed.
- **3.2 Weeks later, another directory (v1).** *"Add these meeting notes to my library."*
  `pkchome status` lists `notes` (stack up, engine up, key present, skill fresh, last used
  Tuesday); the Steward ingests into it. No setup, no question.
- **3.3 Two libraries (v1).** *"Keep the client work separate."* `pkchome library create acme
  --from notes` copies the engine's contract as a starting point; `pkchome library use acme`
  makes it current, or `pkchome library bind acme .` binds it to this directory so a session
  opened here lands in it. Tenants are isolated by I1 on one stack.
- **3.4 The stack went away (v1).** Docker restarted, ports moved, the machine slept. The tray
  icon turns amber before anyone asks: its own probes say Docker is down or a port is dark,
  without an engine to ask. `pkchome status` says exactly which probe failed; `pkchome up`
  re-creates what the config names; the data volumes come back untouched.
- **3.5 Init is remembered (v1).** Every step the setup completed — stack, key, profile,
  skill, first compile — is recorded per library; a Steward that finds a step done never
  redoes it and never asks its question again.
- **3.6 The console is there whenever the engine is (v1).** `pkchome up` starts each
  library's engine process, and every engine serves the console web at its own port;
  `pkchome console` opens the browser on the current library's. The console's top bar switches libraries by name and shows the
  home's health; the Owner lens's Steward view runs in the library's directory.
- **3.7 From the tray to the page (v1).** The Owner types a question into the tray panel.
  The fast lane answers with citations; a click on a citation opens the console on that
  document. With the engine down, the panel offers to start it instead of an empty result.
- **3.8 Settings without a terminal (v1).** The tray's settings pane changes the current
  library, pastes an embedding key (never echoed), flips semantic retrieval, picks the
  backend, sets launch-at-login. Each control is one `pkchome` command underneath.
- **3.9 A project joins the home (v2).** A scaffold project can `pkchome register <dir>` so
  `pkchome status` lists and probes it beside the home's own libraries; it keeps its own
  stack and `.env`.

## 4. Rulings

1. **The personal edition is an application, in `personal/`.** The directory is laid out as
   the root of a repository it will one day be: its own `pyproject.toml`, its own `README`,
   its own tests, the desktop app beside the package. Its dependency rule is a test, not a
   sentence: the Python under `personal/` imports nothing but `pneuma_knowledge_core`,
   `pneuma_knowledge_service` and third parties, and no file under `personal/` names a path
   into `scaffold/`, `apps/`, `examples/` or `packages/` (`tests/test_open_source_hygiene.py`).
2. **`pkc` is the library's; `pkchome` is the edition's.** The Steward's vocabulary — the
   door, the readers, `owner say`, `ingest`, `profile`, `archive`, `skill` — is the library's
   command and gains nothing here. What only a personal machine needs is a second command,
   `pkchome`: setup, up, down, status, library, config, credentials, the harness-level skill,
   the console, the tray. The personal package declares no `pkc` script of its own — the
   library's is the only `pkc` in the installed environment. What the edition adds is the way
   in: `pkchome exec -- <command…>` runs any command under the environment assembled from the
   home (§4.5), and the installer writes a `pkc` launcher beside `pkchome` that is exactly
   `pkchome exec -- pkc "$@"`; the global skill's shim is the same line. Zero subcommands,
   zero flags added to `pkc`; the text the skill teaches is the library's text.
3. **One home per machine, `~/.pkc` (`PKC_HOME`).** It holds state and configuration —
   never a source, a claim, or a record. A second machine starts with an empty home; a library
   moved by copying its directory is complete without it. The library knows no home: the
   variable is the edition's, not a `PNEUMA_KNOWLEDGE_*` setting.
4. **One infrastructure per machine, N tenants.** Postgres, Qdrant, Meilisearch and RustFS
   run once, from a compose file `pkchome up` generates out of `config.yaml`; data volumes
   live under `~/.pkc/data/`. A library is a tenant on that stack, isolated by I1 as every
   tenant is; its canonical repository lives under `~/.pkc/libraries/<name>/canonical/`.
5. **The edition assembles the environment; the library reads only the environment.**
   Precedence, lowest to highest: framework defaults → `~/.pkc/config.yaml` → the library's
   engine directory → `~/.pkc/credentials` for keys the engine may not hold → the process
   environment. One function, `home_environment(library)`, produces the `PNEUMA_KNOWLEDGE_*`
   variables (and `PNEUMA_KNOWLEDGE_TENANT`, `PNEUMA_KNOWLEDGE_ENGINE_DIR`) that the `pkc`
   entry, the engine process and the per-library skill render all use. The library's
   `get_settings` sees a process environment and nothing else, exactly as in a project.
6. **Credentials are provided once and never copied.** `~/.pkc/credentials` (mode 0600)
   holds `KEY=value`; no library directory and no engine ever receives a key. A key present in
   the process environment wins for that one process.
7. **Choices are recorded, and a recorded choice is never asked again.** Per library:
   `semantic_retrieval`, the embedding spec, the backend; per home: the defaults a new library
   inherits. The Steward reads them from `pkchome status` before it opens its mouth.
8. **The library is chosen, not guessed.** Tenant resolution: `--library` on `pkchome`, or
   `--user` on `pkc` → `PKC_LIBRARY` in the environment → a `.pkc` binding in the working
   directory or an ancestor → `~/.pkc/current`. With none of these `pkchome exec` refuses
   before the library's `pkc` runs, and lists the libraries; it never picks one for the Owner.
9. **The skill is global and the contract is not.** The harness-level `pkc-steward` skill is
   the edition's own text (`personal/skill/`, en + zh): where you are, the cold start, how to
   continue in a library, what is remembered. It names no contract, because it serves every
   library on the machine. Each library gets its own package — contract, compile
   instructions, CLI, gate, the same hash stamped as `Executor-Skill` — installed by the
   library's own `pkc skill install` INTO the library directory, in the harness's own
   convention (`.agents/skills/pkc-steward` for Codex, `.claude/skills/pkc-steward` for
   Claude Code, with the `pkc:start` router block in `AGENTS.md` / `CLAUDE.md` beside them).
   It goes there and not into a directory of the edition's own naming because **the library
   directory is the project a harness stands in for this library**: the engine process is
   started there, the unattended worker hands the round that directory as its project, and
   the round's task names the shim as `<project_dir>/<manifest.skill_dir>/scripts/pkc`. A
   package rendered anywhere else is a path the round does not have, and the round is a
   no-op. The global skill's first move in a library is still to read that package where
   `pkchome library show` says it is.
10. **One engine process per library.** The library's process model is one engine directory
    per process: the contract it registers, the models and wording its engine directory
    states, are process-wide. So `pkchome up` starts the middleware once and then, per
    library, one process that runs the library's API application and worker loop together
    (pid and log under `~/.pkc/run/<name>.*`, port in `library.yaml`), serving the console web
    at that port. Its worker drains only its own tenant (§11.7), so two engines on one
    Postgres never compile each other's jobs under the wrong contract. Under an agent executor
    the worker leaves compile jobs for `pkc draft open` unless the library's unattended
    posture is on. `pkchome down` stops what `pkchome up` started and nothing else. Folding N
    libraries into one process is a later library feature (per-tenant engine directories),
    not an edition trick.
11. **The tray is a client and observes on its own.** The desktop app reads `~/.pkc` and the
    engine's API; it holds no state of its own and writes nothing but its window geometry.
    It probes shallowly by itself — the Docker daemon, the four ports, the engine pid — so
    that a dead engine is a colour on the icon and not a blank; it layers the engine's deep
    status (queue, failures, per-library health) when the engine answers. Every action it
    offers is one `pkchome` command run as a subprocess, found where `config.yaml` records
    the install. The status it renders is `pkchome status --json`, the same document the
    Steward and the console read.
12. **The console is served, not forked.** The engine process serves the console web's
    built `dist` — obtained as an artifact (built from `apps/web` inside this repository,
    downloaded from a release once the edition has its own) and never imported as source.
    Whatever the console needs to know about a home (the library list by name, the health
    page) is a console feature behind one optional endpoint, `/home/status`: with a host that
    answers it the top bar shows the switcher and the health page; without one, the console
    renders as it does today, byte for byte.
13. **The default contract is the edition's asset.** A library created without `--contract`
    gets `personal-knowledge`, a contract shipped under `personal/contracts/` for one person's
    notes, meetings, chats and mail. It was seeded once from the library's reference strategy
    of the same name and is the edition's from then on: the edition never reads
    `pneuma-knowledge-strategies` at run time, and the two may drift.

## 5. The home

```
~/.pkc/
  config.yaml            install: {pkchome, pkc, version}; infra: {compose_project, data_dir, ports: {postgres, qdrant, meili, rustfs}};
                         defaults: {backend, language, semantic_retrieval, embedding}
  credentials            KEY=value, mode 0600 (OPENROUTER_API_KEY …)
  current                the library name a session lands in when nothing else chooses
  registry.json          (v2) scaffold projects registered with `pkchome register`
  infra/
    docker-compose.yml   generated from config.yaml by `pkchome up`; regenerated when config changes
  run/                   <name>.pid, <name>.log per library engine
  data/                  postgres, qdrant, meili, rustfs volumes
  libraries/<name>/
    library.yaml         tenant id, created, engine port, choices {semantic_retrieval, embedding, backend},
                         steps {infra, credentials, profile, skill, first_compile}, last_used, bindings
    engine/              the engine directory (its own git repository), from the library's templates
    canonical/           the canonical git repository
    .agents/skills/      the installed package, in the chosen harness's own convention (`.claude/skills/` under Claude
                         Code): pkc-steward/{SKILL.md, references/, scripts/pkc} and skill-version.json beside it
    AGENTS.md            the `pkc:start` router block (CLAUDE.md under Claude Code) — the library directory is the project
```

`library.yaml` is the init state the frame asked for: a step is written when the command
that owns it completes (`pkchome up` → `infra`; a key into `credentials` → `credentials`;
`pkc profile confirm` → `profile`; `pkchome library render` → `skill`; the first
`pkc draft finish` → `first_compile`), and `pkchome status` reads them back beside a live
probe of each.

## 6. Commands

```
pkchome setup [--non-interactive --answers <f>]   config.yaml, ports probed, infra + engine up, first library, the two questions
pkchome up | down | restart                       the machine's middleware and the engine process
pkchome status [--json] [--library <name>]        everything probed: docker, four services, engine, queue, and per library: key, engine dir, canonical, skill fresh, steps done, last used
pkchome library create <name> [--from <name>] [--language …] [--contract <path>]
pkchome library ls | show [<name>] | use <name> | bind <name> [<dir>] | unbind [<dir>] | render [<name>]
pkchome config get|set <key> [<value>] [--library <name>]   home defaults or a library's choices (semantic_retrieval, backend, embedding)
pkchome credentials set KEY [--from-stdin]        writes ~/.pkc/credentials (0600); never echoes
pkchome env [--library <name>]                    the assembled environment, for a shell or a script
pkchome exec [--library <name>] -- <command…>     run a command under that environment; `pkc` resolves to the library's
pkchome skill install [--backend codex|claude-code|all] [--force]   the harness-level skill; auto-detects the harnesses present
pkchome console                                   opens the browser on the engine's console
pkchome tray                                      launches the desktop app if installed, else says where to get it
pkchome register <dir> | forget <dir>             (v2)
```

`pkc <anything>` is the library's command, run through the edition's launcher (§4.2).
`pkchome setup` is the only interactive command, and only when a terminal is attached; the
Steward runs it with `--answers` from what the Owner said.

`pkchome status --json` is a contract three readers share — the Steward, the console's
health page, the tray. Its shape: `home` (path, version), `docker` (reachable), `services`
(four, each `{port, up}`), `libraries` (each `{name, current, engine: {pid, up, port, uptime}, queue: {pending, failed,
last_compile_at}, key, engine_dir, canonical_head, skill_fresh, steps, last_used}`).

## 7. The global skill

`pkc-steward`, installed into `~/.codex/skills/pkc-steward/` or `~/.claude/skills/pkc-steward/`
(marker-stamped, `--force`-guarded, the library's installer over the edition's package). Its
text is the edition's, in `personal/skill/` (en + zh), and it holds no contract. Sections:

- **Where you are.** `pkchome status` first, always by mechanism rather than by
  instruction: `pkchome exec` refuses with the library list when no library is chosen, so a
  session that skipped the status lands on the refusal.
- **Cold start.** The two questions, and how the Steward answers the first itself: it writes
  the profile from what it already knows of the Owner (`pkc profile set … --provenance
  inferred`, coding-agent-mode §5.8) and asks the Owner to correct it, one field at a time;
  it records the retrieval choice the Owner made (`pkchome config set semantic_retrieval …`
  or `pkchome credentials set`, coding-agent-mode §5.9).
- **Continuing in a library.** Read the library's own package (`pkchome library show` names
  the path); from there the round, the door and the postures are the library's rendered text.
- **What is remembered.** Steps and choices; the Steward does not ask what `pkchome status`
  already answers.

The per-library package is the project skill's `references/` plus a one-page `SKILL.md`
binding them to the library by name — the same renderer, the same `Executor-Skill` hash a
project's Steward carries.

## 8. The one sentence

The README carries one sentence, for the agent and not for the person:

> Install the pkc personal knowledge library: run `curl -fsSL <release-url>/install.sh | sh`,
> then follow the instructions it prints last.

`install.sh` is the mechanism the sentence triggers. It is idempotent and it does, in order:
`uv` (install if missing) → `uv tool install` of the personal package at the release tag →
`pkchome skill install` for every harness whose directory exists (`~/.codex`, `~/.claude`) →
a Docker probe (`docker info`; on failure it prints where Docker Desktop or OrbStack comes
from and stops, without pretending) → optionally the desktop app from the same release. Its
last lines are addressed to the agent reading them: which `SKILL.md` was installed, to run
`pkchome status`, and that setup is the next command. Those lines exist because the harness
that ran the installer may not reload its skills within the session that ran it.

## 9. The tray

A Tauri 2 application under `personal/desktop/`, shipped as a `dmg` / `exe` on the same
release. It is a client (§4.11) and it is judged on feel:

- **A popover, not a window.** On macOS a panel anchored to the menu-bar icon (`NSPanel`),
  no title bar, dismissed on focus loss; on Windows and Linux a frameless window positioned
  at the tray. The panel's UI is bundled with the app and loads from disk; opening it costs no
  network round trip.
- **State first, then updates.** A poller in the Rust side runs from launch: it reads
  `~/.pkc`, probes Docker, the four ports and the engine pid, and asks `/home/status` when the
  engine answers. The panel renders the last known state the instant it opens and receives
  changes as events. A spinner on open is a defect.
- **Observation without the engine.** The icon's colour comes from the shallow probes, so the
  engine dying changes the icon. The deep status (queue, failures, per-library health) is an
  overlay on top when available.
- **Three panes.** Dashboard (the status document, the last compiles, a retry on a failed
  job); search (the fast lane with citations, each opening the console on the document; with
  the engine down, a start button); settings (current library, embedding key through a secret
  field, semantic retrieval, backend, launch at login — each one `pkchome` command).
- **Actions are `pkchome`.** Start, stop, restart, switch, set — the app runs the command
  `config.yaml` records and shows its output on failure. It never touches `~/.pkc` directly.
- Optional: a global shortcut for search (Tauri's global-shortcut plugin); launch at login
  through the autostart plugin.

## 10. The console over the home

A library's engine process is one FastAPI application: the library's `create_app(settings)`
with the edition's routes added — `/home/status` (the status document of the whole home),
`/home/libraries` (every library with its engine's port, so switching is a navigation),
`/home/actions/*` (the same `pkchome` verbs the tray uses) — and the console's `dist`
mounted at `/` with the SPA fallback. The console's part is small and generic: a
`useHome()` probe of `/home/status` that, when it answers, replaces the raw user-id switcher
with the library list by name and adds a health page; `apps/web` gains this as its own
feature and the project shape is unaffected.

## 11. What the library opens

Each is a library feature with a project-shape use of its own, added to the library so the
edition never needs a private path:

1. **Settings from an explicit environment.** `get_settings` already reads the process
   environment and the engine directory; the edition needs nothing more than a documented
   way to run it under an assembled environment (§4.5). Confirm `.env` discovery does not
   leak in from the working directory when `PNEUMA_KNOWLEDGE_ENV_FILE` is unset.
2. **One-process engine.** `create_app(settings)` and the worker's `run_forever()` runnable
   in one event loop, with a clean stop; the worker takes its settings from the same object.
3. **Templates as package data.** The engine, profile and contract templates the scaffold
   reads from `scaffold/templates/` move into the service package (`engine/templates/`) and
   the scaffold reads them from there; the compose generation the scaffold's `init.py`
   computes becomes a library function both callers use.
4. **The per-library skill package.** `render_skill_package` already renders per
   (contract × wording × components × backend); the edition needs a `pkc skill render --out
   <dir>` that writes the package without installing it into a project, and the
   `Executor-Skill` hash unchanged.
5. **The retrieval knob and the profile provenance.** coding-agent-mode §5.8 and §5.9, as
   written there; both are library behaviour the project shape also wants.
6. **A static mount seam.** `create_app` accepts an optional static directory for a console
   `dist` (the project shape keeps nginx; the edition uses this).
7. **A worker tenant filter.** `PNEUMA_KNOWLEDGE_WORKER_TENANTS` (comma-separated; empty means
   every tenant, today's behaviour): the worker claims only those tenants' jobs. Two engines on
   one Postgres are then two workers that never touch each other's queue.

## 12. Invariants

- **I1.** Libraries are tenants; every command resolves one tenant before it runs, and
  refuses rather than defaults. The worker drains per tenant as it always has.
- **I2 / I7.** The home holds no authority and no record: the canonical repository and L0 are
  where they were; the skill packages are derived and re-rendered.
- **I3–I6.** Untouched.
- **The dependency direction is one-way and tested.** `personal/` → the two library packages
  and the console's artifact; nothing in `packages/`, `apps/` or `scaffold/` imports or reads
  `personal/`, and `personal/` reads nothing of theirs.
- **Mechanism over persuasion.** "Choose a library first" is a refusal, not a sentence in
  the skill; "do not ask again" is a step recorded by the command that did the work; the
  dependency rule is a hygiene test.
- **Secrets.** `credentials` is 0600, outside every git repository (the engine is a
  repository; the home is not), never copied into a library, never in a rendered skill, never
  in the tray's state.

## 13. Order of work

1. **The library's seams** (§11.1–11.4, 11.6, 11.7): environment-only settings confirmed, the
   one-process engine, templates as package data with the scaffold on them, `pkc skill
   render --out`, the static mount.
2. **The edition's package**: `personal/` with `pyproject.toml`, `home_environment`, tenant
   resolution and `pkchome exec` with its refusal; `pkchome library …`, `library.yaml`;
   `pkchome up|down|restart|status` with the generated compose and the engine process;
   `pkchome config|credentials|env`; `pkchome setup`; the default contract; the hygiene test.
3. **The retrieval knob and the profile provenance** in the library (§11.5).
4. **The global skill** and `pkchome skill install`; the per-library package rendered on
   `library create`.
5. **The installer** (`install.sh`) and the README sentence; a real cold start on this
   machine with Codex, from an empty home to a first compile, recorded like the acceptance run.
6. **The console over the home**: `/home/*` routes, the `dist` mounted, the console's
   `useHome()` switcher and health page.
7. **The tray**: the Tauri app, the poller, the three panes, the release build.
8. End-to-end: the one sentence on a clean home, through the tray, to a page in the console.

## 14. Boundaries

- One machine. Sharing a home between machines, or a stack between machines, is not designed.
- The home is not a backup: `pkchome down` keeps data, but nothing here copies it elsewhere.
- Docker stays a requirement; a Docker-free stack of lighter adapters is a later page.
- An AI that cannot run a command line (a chat app) has no face here; a read-only MCP face
  is a later page.
- Kimi, the evolve door and single-shot agent roles stay where coding-agent-mode left them.

## 15. Coding-agent sessions as material

The Owner's ruling orders the knowledge by subject: first **the project itself** — its
purpose, audience, top-level design, evolution, key features and milestones; second **how
the Owner thinks about those projects**, evidenced by the Owner's own inputs; last the
detailed making process. Most of a coding-agent transcript is the agent's output. Some
sessions are research, chat or other tasks rather than project work. A folder or transcript
never enters the compiler as-is.

Three mechanisms implement that order:

1. **Source contract and normalizer.** The library owns `pneuma.source.agent-session/v1`:
   identified Owner `say` turns, agent `narrative` turns and bounded `action` stubs, with
   project attribution and timezone-aware, non-decreasing timestamps. At least one non-blank
   Owner turn is required. Tool inputs and outputs are not source text; an action is a
   one-line description of at most 200 characters, not a command result or proof of success.
2. **Intake triage before ingest.** The edition's converter offers compile only for a
   matched project with at least three Owner turns. Its defaults are `--min-owner-turns 3`,
   `--min-owner-chars 200`, and `--ack-max-words 1`. Under 200 Owner-text characters means
   **skip**, including otherwise eligible sessions; 0 disables that length filter. The
   turn threshold may be raised, not lowered below the library's three-turn floor. A
   session below the turn threshold, without a matched project, or containing only slash
   commands/known acknowledgements gets `canonical_treatment: none`. The existing CLI
   expresses this as `--intake searchable`, so it also requests no L2; L0/L1 remain
   unconditional for admitted sessions. Subagent task prompts are excluded rather than
   attributed to the Owner; a transcript left without Owner turns is skipped. Research/chat
   sessions selected with `--purpose research|chat` receive the same index-only treatment.
   These are mechanical eligibility tests, not a semantic claim that every eligible
   session contains knowledge worth compiling.
3. **Compile contract and Owner-voice pages.** For new libraries, `personal-projects`
   updates the default stated in §4.13. Its edition-owned bilingual contract orders
   `projects/{slug}/overview.md`, `evolution.md`, `features/{slug}.md` and
   `decisions/{slug}.md`, followed by `owner/views/{slug}.md`, then `memory/people/{slug}.md`
   and `memory/topics/{slug}.md`. Overview definitions and summaries explain the project;
   evolution entries carry dates. The `owner/views/{slug}.md` path template declares
   `owner_voice: true` (a `path`/`owner_voice` mapping), as does its creation template; the
   library gate enforces that path declaration and checks for the Owner's own speech. Agent
   narrative supports reported work and project state, never the Owner's views. The making
   process gets no canonical family: edits, commands and transient test failures stay
   retrievable and citable in L0/L1 under those subject pages. Research/chat produces no
   canonical page unless the Owner states a durable view; such a turn can support a view
   during a separately requested draft round. `--contract personal-knowledge` remains a
   shipped alternative, and `--contract <path>` still accepts a custom contract.

The provider converter stays **outside the PKC library**. It is the Steward's tool,
`personal/skill/scripts/agent_sessions.py`, installed with the edition's global skill and
using only Python 3.12's standard library. The Owner names directories; the Steward runs
`list --project <dir>`, shows the per-session verdicts, then runs `ingest --project <dir>`.
`--session-id` selects particular sessions in a mixed project folder; `--since` filters by
retained activity at or after a timezone-aware timestamp. `export --project <dir> --out
<dir> [--owner-id …]` writes one filtered contract payload per admitted session. Export's
Owner id defaults to `owner`; ingest uses the selected library tenant unless overridden.
Claude Code attribution comes from the encoded project directory under `~/.claude/projects`;
Codex attribution comes from rollout `cwd` under `~/.codex/sessions`. A recorded directory
conflict skips the session, including encoded-name collisions. Manual imports of index-only
exports need `--intake searchable`; triage metadata alone does not override library intake.

The converter retains Owner words and agent prose verbatim, joins text blocks within a
message with one newline, drops tool results, reasoning, compact summaries and injected
harness context, and reduces actions to a tool name plus a path or command executable
(arguments are omitted). It stably orders recorded timestamps without changing their
instants; a missing turn timestamp inherits the preceding recorded timestamp, while no
usable clock is an error. It never scans project source code or passes a whole transcript
through ingestion. Tests use synthetic provider records only.

Ingest resolves the edition's existing library selection, pins it on each `pkchome exec
--library <name> -- pkc ingest --contract agent-session/v1 --file …` call, and tracks only
successful payload hashes and session identities in
`~/.pkc/libraries/<name>/ingested-sessions.json` (`PKC_HOME` applies). This is discardable
**edition state**, not authority or a kept knowledge record. Atomic writes and a per-library
import lock protect it. Unchanged payloads are skipped on rerun, changed sessions become
new immutable source material, and failed imports remain retryable. `ingest --dry-run`
changes neither sources nor that state. No converter operation writes canonical.

## 16. Application-owned increments and resident sync

The Owner's ruling is that growing external material is the personal edition's problem.
A long-running coding session must enter from its previous result plus its pending
increment; a file's modification time cannot decide that the whole session is new again.
The library remains unaware of watches, transcript cursors and tray schedules. What it
sees is exactly the `agent-session/v1` payload handed to `pkc ingest`. This section replaces
§15's whole-payload import tracking with one shared incremental mechanism, including the
converter's manual `ingest` command.

`library.yaml` owns `watch: [{path, harnesses: [claude-code, codex], since?}]`. Paths are
resolved absolute directories, selected exactly as in §15, and `since` is an optional
inclusive, timezone-aware retained-activity boundary for a session's first import. It does
not discard turns from an admitted session or from a pending increment. `pkchome watch
add <dir> [--library NAME] [--harnesses codex claude-code] [--since ISO]`, `watch ls` and
`watch rm <dir>` maintain that list; removal preserves the cursor. Setup answers may include
`watch: [dirs]`. Libraries have independent watches and cursors even for the same directory.

`~/.pkc/libraries/<name>/sync-state.json` owns per-session `{provider, session_id, file,
source_ids, exported_turns, last_turn_id, last_at, prefix_hash, held}`. The session key includes
provider, session identity and project; a same-file identity change is also a rewrite.
`file_size` bounds the last observed SHA-256 prefix; `exported_bytes` records the byte
boundary of the last successful export. These are different boundaries when material is
held. State contains no transcript text. The cursor rules are mechanical:

- Same complete-file size and prefix hash: unchanged, with no ingest, whatever mtime says.
  An unchanged held session still reports its held counts. The counters overlap deliberately:
  `unchanged` measures observations and `held` measures sessions still awaiting enough input.
- Growth with the old prefix intact: compare retained turns against the verified exported
  prefix, including previously held material. Readers remove event mirrors and excluded
  material; multiset subtraction preserves repeated real speech and handles delayed
  timestamps without losing or repeating earlier turns. New part turn IDs continue the
  exported count; each payload retains timestamp order. An unfinished final JSONL record waits
  for completion; a valid final record needs no trailing newline. This mechanism never reads mtime.
- Below either triage threshold: record `held: {owner_turns, chars}` and the observed prefix,
  leaving `exported_turns`, `exported_bytes`, `last_turn_id`, `last_at` and `source_ids` alone.
  Defaults are three Owner turns and 200 Owner-text characters per pending increment.
  The converter's existing threshold flags still apply to its manual `ingest` entry.
  Once both numeric thresholds are met, the same triage decides full compile eligibility
  versus index-only admission (commands/acknowledgements, or explicit research/chat).
  Subagents and project conflicts are excluded. Missing directories and parse/import errors
  are reported as skipped/error rows; failed imports remain retryable.
- At threshold: export only new turns as a new immutable source. `metadata` carries
  `from_turn` (the first retained turn ID), `part` (one-based), and for a continuation
  `continues` (the immediately preceding source ID). Advance the export cursor only after
  ingest returns one source ID. The application contract teaches reading the earlier part's
  canonical pages first, without re-reading its transcript; claims cite their own part.
- A changed or truncated observed prefix, or a changed retained history, reports `rewritten`
  without replacing the cursor. `--rewritten reingest` explicitly admits the replacement
  when eligible. It starts a fresh turn cursor, retains the source-ID history, and marks
  `rewritten` instead of asserting `continues`.

Old `ingested-sessions.json` entries are absorbed once: recover a complete historical file
prefix whose converted payload has the exact recorded hash, then replay that payload through
ordinary ingest deduplication to obtain the existing source ID. This creates no new source
or job when that source is present. The one-time search can be expensive for a long file.
An old hash that cannot be reproduced (rewritten transcript, unknown old conversion options
or Owner ID) reports `rewritten`; migration never guesses that today's end was the old end.
The original legacy record is retained, while migrated keys leave the new state's legacy map.

`pkchome sync [--library NAME] [--dry-run] [--json] [--rewritten report|reingest]` executes
one pass and reports `{scanned, new, increments, held, unchanged, rewritten, ingested,
skipped}` plus per-session outcomes. Text mode names source IDs and compile jobs enqueued.
An immediate second pass enqueues nothing. An advisory lock at `run/<name>.sync.lock`
refuses concurrent writers and releases on process death. Dry runs create no files, update
no cursor and call no ingest; migration is shown as due. Before an ingest, the exact payload
is atomically journaled under `sync-pending/` with a hash and proposed cursor in sync state.
A crash or lost response replays those same bytes through library deduplication before any
new growth is considered, even if the watch was removed. The journal is deleted only after
the returned source ID and cursor are saved.

The tray is still a client (§4.11). Its Rust poller requests `/home/actions/sync` separately
for every watched library with a live engine, an elapsed interval and no running sync.
`config.yaml` owns `sync: {interval_minutes: 15, enabled: true}`; `pkchome config set
sync.interval_minutes N` and `sync.enabled on|off` edit these home-wide settings. The
engine action detaches `pkchome sync --library <this> --json`, pinned to its own home and
library. `/home/status` includes each library's `sync` observation and a top-level `sync`
for the serving library: `{last_run_at, last_result, watching, next_due}`, plus `running`,
current `held` count and a numeric `next_due_ms` for scheduling without client date parsing.
The due time is derived from the recorded last pass and the current interval; a never-run
watch is immediately due. The poller also spaces action attempts by the interval so stale
status or failed launches cannot trigger a retry on every health poll. Settings exposes the
interval, enable switch and watched directories via `pkchome watch`; Dashboard shows
“watching N dirs · last sync … · held M” and “Sync now”. The tray never opens transcripts.

Sync **does not compile**. Ingest writes L0 and enqueues the library's ordinary index/compile
jobs; the unattended engine worker or the Steward drains them through the existing gates.
The framework's queue accounting is a separate matter: `held` is pending external material,
`ingested` is a count of acknowledged source parts in this pass, and neither is a job count
or a claim that compilation completed. No library package, console app or scaffold change
is involved in this mechanism.

# pneuma-knowledge scaffold — the project generator

**English** | [简体中文](README.zh-CN.md)

The scaffold is a **generator**: one entry script that asks a handful of questions (or takes
them all at once from a file), then produces a complete, self-contained knowledge-base
project in a directory of your choosing — your data, your contract, your own middleware
stack on auto-probed free ports.

```bash
./init.py --demo                           # zero interaction, zero keys: a project that
                                           #   already HAS a compiled library, started for you
./init.py                                  # interactive: guided, step by step, with a
                                           #   bundled demo dataset offered at every fork
./init.py --answers my.toml --target DIR   # one command: for coding agents and CI
./init.py --print-schema                   # the commented answers-file template
```

**Just want to see what a finished knowledge base looks like?** `./init.py --demo` generates a
real project into a fresh temporary directory, brings up its stack and browser UI, and loads
the library of [`examples/opc`](../examples/opc/README.md) — 191 sources, 28 canonical
documents, every claim drillable back to the exact source passage — with **no API key at all**
(`--target DIR` to choose where, `--no-start` to generate without starting docker). It is an
ordinary generated project that happens to arrive with a library, so anything you learn there
transfers directly to your own.

Both modes run the same generator; the interactive flow simply collects the same answers a
file would carry. No question in the flow requires prior knowledge: every step introduces
what the thing is for, offers a sensible default (Enter accepts), and echoes what you chose.
Ports, compose project names, tenant ids — anything a newcomer has no opinion about — are
decided automatically and echoed, never asked.

Want an AI to build the library with you? Hand `AGENT-GUIDE.md` to your coding agent
(Claude Code / Codex / Cursor all work) and paste it this line:

```
请阅读 scaffold/AGENT-GUIDE.md 并按它引导我，用我自己的数据建一个知识库。我是新手，请一步步来。
```

## What gets generated

```
my-kb/
  engine/            # YOURS — the engine, its own git repository: model roles, chunking,
                     #   answering, the compile contract, the owner profile, prompt overlays
  .env               # YOURS — the key and this machine's infrastructure (gitignored)
  my-data/           # YOURS — material (.md files; pre-filled when you chose the demo dataset)
  README.md          # generated in your language, states these boundaries
  AGENTS.md          # tells any coding agent the same boundaries + where the guides live
  app.py             # machinery — runtime driver (never edit)
  start.sh           # machinery — end-to-end demo runner (never edit)
  docker-compose.yml # machinery — per-project middleware stack (never edit)
  server.py          # machinery — the API entrypoint of the browsing layer (never edit)
  worker.py          # machinery — the compile worker of the browsing layer (never edit)
```

The machinery files are verbatim copies of `templates/` — upgrading them is regenerating a
project (or copying the newest templates over); everything you authored lives outside them.

Then, inside the generated project:

```bash
cd my-kb
$EDITOR .env       # fill OPENROUTER_API_KEY (skipped only if you didn't enter it)
./start.sh         # stack → ingest → compile → cited demo answers → library glance

docker compose --profile console up -d --wait   # and to work in a browser: the library,
                                                #   the material, the Engine Console
```

## What this directory contains

| Path | What it is |
|---|---|
| `init.py` | the generator — the only entry point |
| `templates/` | machinery copied verbatim + language-variant templates (contract skeleton, profile, project README/AGENTS) |
| `example/` | the bundled demo dataset (a fictional indie developer's two weeks), its filled demo contract, demo questions |
| `AGENT-GUIDE.md` | the flow a coding agent follows to build a library with a user |

## Where the judgement lives

Everything the compile model is allowed to judge is written in the generated project's
`engine/compile/contract.md`. The full practice of writing one — type → implied-usage derivation, subject
granularity, the acceptance loop — is in
[docs/guides/compile-contract.md](../docs/guides/compile-contract.md), the sole authority
on the subject.

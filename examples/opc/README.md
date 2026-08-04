# OPC — a complete, agent-built knowledge base

**English** | [简体中文](README.zh-CN.md)

This directory is exactly what the scaffold flow produces: a knowledge-base project for one synthetic owner — 林舟 (Lin Zhou), an indie developer building a change-evidence product called Seamlog — compiled from 190 pieces of his material into 29 canonical documents and 754 cited claims. The library ships with the project; you can open it in a browser in about a minute, without an API key.

## Where this came from

The library was built by an **autonomous agent** (Claude Opus 5 running in Claude Code) that started from a pristine copy of [`scaffold/`](../../scaffold/), followed [`AGENT-GUIDE.md`](../../scaffold/AGENT-GUIDE.md), and received exactly two inputs: the material in `my-data/` and a three-sentence owner self-introduction. It read all 190 files, derived the [`contract.md`](contract.md) from what it read, compiled, judged the result against the [acceptance loop](../../docs/guides/compile-contract.md#5-the-acceptance-loop), and spent its one allowed revision when the first build violated a rule the material itself states. The full record is in [`build-record/`](build-record/): the verbatim task book that started it, its build log, and its complete conversation transcript.

Treat this build as a **reference line, not a ceiling**: it is what one agent generation produced on one day. Point a stronger agent at the same data and the same guide, and your library may well come out better — the contract judgement is where agents differ.

## Try it

**1. Browse — no API key**

```bash
cp .env.example .env
./app.py up && ./bootstrap.py
docker compose --profile web up -d --build api web   # first image build takes a few minutes
```

Open <http://127.0.0.1:24173>. Everything is drillable: 190 sources verbatim, the compile history (170 commits), every claim's citations back to the exact source passage, and a real frozen archive volume that a rollover produced during the build.

**2. Ask — needs a key**

Put an OpenRouter key into `.env` (`OPENROUTER_API_KEY`), then either ask from the CLI or restart the api container so the web recall lanes pick it up:

```bash
./app.py ask '第一条证据链现在卡在什么条件上？' --sources
docker compose --profile web up -d api                # web Q&A with the key
```

**3. Recompile with your own parameters — needs a key, costs real money**

Edit `contract.md` (or swap the model in `.env`), then rebuild from the same material. The reference build took ~21M tokens with `gpt-5.6-luna`:

```bash
./app.py down --volumes && rm -rf data/
./app.py up && ./app.py init
./app.py ingest my-data && ./app.py compile
```

`./demo.sh` wraps all three stages in an interactive menu.

## The corpus

`my-data/` is 84 days of one person's working life, fully synthetic (no real people, brands or credentials): 18 meetings and 48 IM conversations as transcripts, 81 notes and 43 mail threads as documents. Its defining trait — and the reason it makes a good test of this framework — is that half of its information is **negative facts**: what was not approved, not signed, not confirmed, not found. A compiler that flattens "proposed" into "decided" turns this corpus into fiction; the shipped contract exists to prevent exactly that.

## Reproduce it with your own agent

The whole point of this example is that you can. Give a coding agent the scaffold, the two guides ([contract](../../docs/guides/compile-contract.md), [AGENT-GUIDE](../../scaffold/AGENT-GUIDE.md)) and `my-data/`, and let it walk the same road — `build-record/TASKBOOK.md` is the exact instruction that started the reference build. Expect a library of a similar shape, not an identical one: the families and calibers it derives are its judgement.

## What's next

- Write a contract for **your** domain: [docs/guides/compile-contract.md](../../docs/guides/compile-contract.md)
- Build your own project from your own data: [`scaffold/`](../../scaffold/README.md)
- Understand the machine underneath: [docs/architecture.md](../../docs/architecture.md)

## Files

| File | What it is |
|---|---|
| `app.py`, `start.sh`, `docker-compose.yml` (middleware part) | byte copies of `scaffold/templates/` — the replay story is literal |
| `contract.md`, `profile.yaml` | the agent's authored contract and the owner profile |
| `my-data/` | the synthetic corpus, in scaffold ingest format |
| `prebuilt/canonical.bundle`, `prebuilt/l0.jsonl.gz` | the two authorities from the build: the compiled canonical library (git bundle) and the verbatim L0 source rows its citations bind to (source ids are system-assigned, so a re-ingest could never reproduce them) |
| `bootstrap.py` | keyless restore: canonical bundle + L0 dump + derived rebuild |
| `server.py`, `Dockerfile.web`, `nginx.conf`, compose `web` profile | the browsing layer — this example's one divergence from the plain scaffold |
| `build-record/` | task book, build log, full agent transcript |

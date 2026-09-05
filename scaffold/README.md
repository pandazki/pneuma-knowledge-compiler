# Build a knowledge library from your sources

**English** | [简体中文](README.zh-CN.md)

Pneuma compiles raw material into a maintained library of subjects and claims, with references
back to the original passages. The scaffold generates the application that owns your sources,
compile contract and runtime. Start here as a user of the framework; you do not need to read
its implementation first.

The default path is **preserve sources → compile by subject → inspect evidence and usefulness**.
L0 stores source material, L1/L2 support retrieval, and L3 is the maintained canonical library.
A successful compile establishes mechanical validity, not faithful interpretation or complete
coverage. Keep those two acceptance questions separate.

## Start with your material

Prerequisites: Python, `uv`, Docker and a model API key. Run from this directory:

```bash
./init.py                                  # interactive; Enter starts an empty project
./init.py --print-schema                    # all answers-file options
./init.py --answers answers.toml --target /path/to/my-kb
```

A minimal `answers.toml`:

```toml
language = "en"
project_name = "my-kb"
[data]
mode = "path"
path = "/absolute/path/to/material"
```

Omit `[data]` to put material into the generated `my-data/` later. Owner information is
optional. The generated `engine/compile/contract.md` is a usable, domain-neutral starting
contract, with one independently evolving subject per `subjects/{slug}.md`. Read a few
representative sources and specialize it when the intended use calls for a better layout.

Inside the generated project:

```bash
$EDITOR .env                               # put credentials here only
./start.sh                                 # validate → start → ingest/compile each input file
./app.py glance
./app.py ask 'A real question about this material' --sources
```

Inputs are processed in filename order. Name files to express the intended replay order.
Use [source-contract JSON](../docs/reference/source-contracts.md) when material carries
participant identities, message timestamps, threads or media. Markdown is a convenience
adapter for notes and simple transcripts, not a substitute for those fields. The importer
validates the whole inventory before writing; it preserves Markdown frontmatter and does
not turn an imprecise date into an invented clock time. See the generated README for syntax.

Every build/import, queue drain and answer writes a private receipt under `data/run-reports/`.
Check input hashes, imported source IDs, job history, failures and answer degradation. The
reported compile-model token count is not the total cost of indexing, retrieval and answering.

## Understand and improve the result

1. Read the source, its subject page and the cited passage together. Check attribution,
   dates, qualifiers, changes and omissions; a valid address can still support the wrong claim.
2. Ask questions implied by real future use. If an answer is wrong, locate the first failure:
   import, compilation, retrieval, context selection, or final interpretation.
3. Change the responsible layer. A contract change governs future compiles; it does not
   recompile old sources, and a derived-index rebuild does not rewrite canonical knowledge.

For agent-assisted work, start with [AGENT-GUIDE.md](AGENT-GUIDE.md). Read the
[contract guide](../docs/guides/compile-contract.md) when specializing admission and page
boundaries, the [recall guide](../docs/guides/recall-strategies.md) when changing answer
assembly, and the [architecture](../docs/architecture.md) when changing the framework.

## Optional demonstration

```bash
./init.py --demo                            # separate temporary project; prebuilt library, no key
./init.py --demo --target /path/to/demo --no-start
```

The demo restores a compiled example for browsing. Its deterministic vectors support a
keyless demonstration; they are not a quality baseline for semantic retrieval. Build your own
library in a separate project with real embeddings. There is no demo-reset prerequisite.

## Generated project boundaries

| Path | Purpose |
|---|---|
| `engine/` | Versioned strategy: contract, model roles, intake, recall, profile and overlays |
| `.env` | Credentials and this machine's isolated middleware ports; never versioned |
| `my-data/` | Your inputs, or use the external directory selected during generation |
| `data/` | Private runtime state and run receipts |
| `README.md`, `AGENTS.md` | The project's usage and agent instructions |
| `app.py`, `start.sh`, `server.py`, `worker.py`, `docker-compose.yml` | Generated runtime machinery; change the framework templates to improve it |

This directory contains the generator (`init.py`), its `templates/`, an optional fictional
example (`example/`), and the agent guide. Replacing machinery must preserve the user's
`engine/`, credentials and data.

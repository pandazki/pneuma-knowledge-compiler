# Documentation

**English** | [简体中文](README.zh-CN.md)

| Page | What it gives you |
|---|---|
| [Personal edition](../personal/README.md) | installation, library selection, project-session sync, Steward and voice entry points |
| [Web console](../apps/web/README.md) | current interface, development modes and synthetic screenshots |
| [guides/evaluating-libraries.md](guides/evaluating-libraries.md) | distinguish provenance validity, answer quality and coverage |
| [design/structure-lens.md](design/structure-lens.md) | six structural dimensions, page-level checks and repair rounds |
| [architecture.md](architecture.md) | the design stance, how the data flows, and the invariants the code enforces |
| [guides/compile-contract.md](guides/compile-contract.md) | how to write the contract that decides what becomes canonical |
| [guides/evolution.md](guides/evolution.md) | how a schema change is proposed, reviewed and adopted |
| [guides/recall-quality.md](guides/recall-quality.md) | how to find the layer that lost a fact when an answer comes back wrong |
| [guides/recall-strategies.md](guides/recall-strategies.md) | what `ranked`, `select` and `all` trade against each other |
| [design/evidence-scoring.md](design/evidence-scoring.md) | scored selection, uncertainty telemetry, source-time admission and paired synthetic measurements |
| [reference/source-contracts.md](reference/source-contracts.md) | the six input contracts: meeting, document library, IM, email, owner dialogue and agent session |
| [reference/http-api.md](reference/http-api.md) | every route, its parameters and its response shape |
| [reference/configuration.md](reference/configuration.md) | every setting, its default, and what changing it costs |
| [reference/observability.md](reference/observability.md) | the trace spans each lane emits and what each one covers |
| [reference/deployment.md](reference/deployment.md) | containers, middleware, and the operations that rebuild derived state |
| [design/voice-call.md](design/voice-call.md) · [implementation](design/voice-call-implementation.md) | voice design decisions and a self-contained architecture/implementation reference with sequence diagrams, retrieval, context, vocabulary and latency controls |
| [design/engine-console.md](design/engine-console.md) | the engine directory: one deployment's strategy as a versioned unit |
| [design/index-components.md](design/index-components.md) | the component protocol: business structure over canonical, and how to write one |
| [design/steward-owner-visitor.md](design/steward-owner-visitor.md) | the roles above the library, the record an answer leaves, and the access ledger over those records |
| [design/archive.md](design/archive.md) | the archive: retiring a document or a source from every default retrieval without deleting it, through a proposal the Owner confirms |
| [design/coding-agent-mode.md](design/coding-agent-mode.md) | a coding agent as the Steward: roles, motivations, stories, and the CLI door it compiles through |
| [design/single-machine-edition.md](design/single-machine-edition.md) | The personal edition: an application over the library — `pkchome` and `~/.pkc`, one infrastructure per machine, libraries as tenants, one sentence to install, a tray, the console served |

The repository [README](../README.md) has the synthetic demo and starting paths.

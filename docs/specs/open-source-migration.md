# Public release contract

Status: accepted from the maintainer brief on 2026-07-28.

This specification is the single source of truth for the first public release of Pneuma Knowledge Compiler. Public product strategy, naming, sample data, visual identity, and release evidence are defined entirely inside this repository.

## 1. Architecture parity

The public repository preserves the complete executable topology:

- a pure domain package with ports, compile, ingest, recall, persona, skill, and evolve contexts;
- a service package with FastAPI routes, adapters, worker, settings, wiring, datasets, and integration tests;
- a React/Vite operating UI;
- PostgreSQL, Qdrant, Meilisearch, per-user Git canonical storage, Docker, and GKE deployment assets;
- examples, ADRs, observability, upgrade, mock seed, import, and rebuild workflows.

Generated caches, local environments, runtime data, and unpublished Git history are not architecture and are excluded.

## 2. Public language

| Surface | Contract |
|---|---|
| Repository | `pneuma-knowledge-compiler` |
| Core distribution | `pneuma-knowledge-core` |
| Core Python module | `pneuma_knowledge_core` |
| Service distribution | `pneuma-knowledge-service` |
| Service Python module | `pneuma_knowledge_service` |
| Web package | `pneuma-knowledge-web` |
| Tenant key | `user_id` / `UserId` |
| Environment prefix | `PNEUMA_KNOWLEDGE_` |
| Built-in fallback strategy | `personal_knowledge_v1` → `personal_knowledge_v3` |
| Complete application example | `examples/opc` |

Public identifiers are canonical. Compatibility aliases for retired or external product vocabulary are forbidden.

## 3. Product invariants

- **I-1 User isolation:** every store, index, queue, API path, and canonical repository is isolated by `user_id`.
- **I-2 Authority split:** canonical content and raw sources are authoritative; projections, lexical/vector indexes, annotations, and manifests are derived and rebuildable.
- **I-3 Reachability:** raw retrieval and lexical retrieval remain available regardless of deeper compilation treatment.
- **I-4 Provenance:** claims, chunks, lexical hits, and structure maps share the same `source_id + paragraph span` addressing system.
- **I-5 Stable assembly:** stable instructions and knowledge context never receive request-time timestamps; volatile question and time context live in the human turn.
- **I-6 Evaluation isolation:** expected answers, rubrics, and scoring evidence never enter compile or recall inputs.
- **I-7 Synthetic honesty:** bundled personas and journeys are labeled synthetic and never presented as real customer evidence.

## 4. Strategy separation

The framework packages ship mechanisms plus a neutral personal-knowledge fallback. The
fictional AI-Native solo developer strategy, Chinese prompt wording, profile, schema
matrix, data and evaluation truth live under `examples/opc` and are registered at that
application's startup boundary.

The generic v1 → v2 → v3 upgrade path remains executable so architecture-level evolve
and rebuild behavior is preserved without requiring an application domain.

## 5. UI replacement

The UI:

- belongs recognizably to the Pneuma family without copying a sibling surface;
- uses a dark, high-contrast operating canvas, Pneuma orange as a controlled signal color, precise technical typography, and authored graph/trace motifs;
- supports first-class day and night modes: a porcelain wayfinding atlas and a midnight enamel control room, with identical route semantics and evidence hierarchy rather than a simple color inversion;
- keeps familiar task affordances, visible state, keyboard focus, responsive behavior, reduced-motion support, and meaningful empty/error/loading states;
- shows synthetic status wherever bundled demonstration data could be mistaken for real user data.

The emitted app shell includes the Impeccable direction contract. `DESIGN.md` is documented from the shipped interface, not invented before implementation.

## 6. Verification gates

A release candidate is accepted only when all gates pass after the final edit:

1. vocabulary outside the public Pneuma product contract is absent from file paths, source, docs, deployment, fixtures, compressed presets, and rendered UI;
2. core and service tests pass, including real-backend integration tests when Docker services are available;
3. Python lint/type checks configured by the project and the Web TypeScript/Vite build pass;
4. deterministic mock data runs through ingest, compile, projection, recall, and UI consumption;
5. desktop and mobile browser flows cover profile, sources, ingest, process, recall/ask, library, graph, history, evolve, and both day/night themes;
6. the e2e report links screenshots, command evidence, known skips, and zero-console-error/network-failure observations.

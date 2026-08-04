# apps/web

**English** | [简体中文](README.zh-CN.md)

The bilingual web workbench over the HTTP API: walk the whole pipeline — materials, compile jobs, the canonical library with per-claim citations, three retrieval lanes, evolution review — with every step drillable back to its evidence.

## Run

```bash
docker compose -f ../../infra/docker-compose.yml up -d --wait
bash ../../scripts/dev-api.sh        # API on 127.0.0.1:18000
bash ../../scripts/dev-worker.sh     # compile worker (when you want jobs to run)
pnpm install && pnpm dev             # Vite on :5173, proxies /v1 and /healthz
```

```bash
pnpm run build    # tsc -b && vite build — run before committing web changes
pnpm test         # node --test tests/*.test.mjs (pure-logic tests, no browser)
```

The only environment variable is `VITE_API_BASE` (empty = same-origin via the dev proxy). For a fully packaged deployment (nginx + API + worker + seeded demo data, no API key), see [`examples/opc/`](../../examples/opc/).

## Shape

React 18 + Zustand + Radix + Tailwind v4. No react-router: `src/App.tsx` maps view names to lazy components, and the Zustand store syncs selection to `location.hash` — deep links and back/forward work (`#/evolve/evolve-task/<id>`).

The shell carries the tenant switcher, the snapshot picker (HEAD / frozen KB snapshots / canonical history, read-only mode stamped when pinned), a zh/en locale toggle (full dictionaries under `src/i18n/`) and the Paper/Lightbox theme toggle. Views, grouped as the sidebar presents them:

| Group | Views |
|---|---|
| Front matter | overview (system map with live counts) |
| Materials | sources (catalog, galleys, L0 fetch), ingest (contracts + documents, preview-first) |
| Process | process (trigger + job queue), history (compile timeline, per-claim diffs) |
| Retrieval | recall (rag / fast / deep-SSE), ask (briefings), live_context (SSE + WS, gate ledger) |
| Canon | library (documents, claim badges, citations, neighborhood), graph (structure health + snapshot compare) |
| Evolution | evolve (draft review: rationale, file diffs, dropped anchors, adopt/drop) |
| Back matter | components (the design-system gallery) |

## Design rules

The design authority is [`DESIGN.md`](DESIGN.md); its executable forms are two files — [`src/styles/tokens.css`](src/styles/tokens.css) (every color lives here; components use zero hex/rgb literals; derived shades via `color-mix` only) and [`src/index.css`](src/index.css) (prose typography, scroll-region conventions, native-control resets). The short version:

- Two themes, independently tuned, not inversions: light "Paper", dark "Lightbox".
- One accent (the blue pencil) for links, selection, focus and footnote numbers; status is conveyed in text and ink shades, not traffic-light colors.
- Editorial feel: near-square corners, fade/2–4px motion only, hairline dividers, serif reading faces (LXGW WenKai first) with sans UI and mono machine text.
- The `components` view is the gallery of the ~35 primitives under `src/ui/` — check there before building a new one.

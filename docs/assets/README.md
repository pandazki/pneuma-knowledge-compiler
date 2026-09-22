# Documentation screenshots

**English** | [简体中文](README.zh-CN.md)

These are captures of the current `apps/web` interface, rendered with **entirely invented data** from [docs_fixtures.mjs](../../scripts/dev/docs_fixtures.mjs). Harbor Notes, its sources, claims, history and conversation are synthetic examples. They are not a real library, a completed agent run or evidence of answer quality.

| Capture | What it shows |
|---|---|
| `library-{en,zh}-{light,dark}.png` | Canonical reader, claim anchors and source references |
| `history-{en,zh}-{light,dark}.png` | Two fictional commits and their per-claim changes |
| `steward-{en,zh}-{light,dark}.png` | Synthetic chat in the Steward view and the voice entry point; no call starts |

## Reproduce

From the repository root, with Node, pnpm and the web dependencies installed:

```sh
cd apps/web && pnpm install && pnpm exec playwright install chromium
cd ../..
node scripts/dev/capture_docs.mjs
# Alternatively, use an installed Chrome binary with a fresh temporary profile:
DOCS_BROWSER_CHANNEL=chrome node scripts/dev/capture_docs.mjs
```

The script owns an isolated Vite server on `127.0.0.1:4179`; set `DOCS_SCREENSHOT_PORT` if needed. It creates fresh browser contexts, supplies only the declared fixture API responses, intercepts the Steward WebSocket, blocks outgoing application requests, and rejects unknown API routes and mutations. It never opens a personal home or reads library data. No real backend, agent or model is contacted. No screenshot is edited to hide private content after capture.

The script checks application errors and writes `screenshots.json` with the viewport and file inventory. Review every generated image before publishing. Old screenshots that showed the retired Graph navigation have been replaced.

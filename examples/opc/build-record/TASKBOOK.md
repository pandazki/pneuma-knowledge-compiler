# 任务书原文（维护者 → 重建代理，2026-09-01）

> 本文件逐字保存了启动 2026-09-01 这次重建时，维护者发给执行代理
> （Claude Opus 5 / Claude Code）的完整指令。配合 BUILD-LOG.md、
> trace/compile.log 与 use-side/session.json 一起读，就是这一轮的全部记录。
>
> 启动第一轮（2026-08-03 的干净房间构建）的那份任务书，随它记录的那一轮一起
> 被这一份取代——发行前不背兼容包袱。第一轮真正留下来的东西是那份契约，
> 它仍是这座库的宪法，就在 engine/compile/contract.md。

---

# Task I — rebuild the OPC example on the current framework, and teach what is new

Worktree and rules: as in `TASK-A1-consultations.md`. Branch `feat/steward-owner-visitor`
(Task H has landed — read its report commit range first). The example is `examples/opc/` —
read its README (both languages), `app.py`, `bootstrap.py`, `contract.md`, and
`build-record/TASKBOOK.md` before anything. The example is a scaffold-born project for one
synthetic owner (林舟 / Seamlog, 190 sources in `my-data/`); its prebuilt library and
build-record are what developers actually open. It is stale by four feature waves:
supersession/overview landed mid-way, and it predates index components in production use,
consultations/visitor classes/the lens UI, owner-dialogue/v1, live context (#11/#13), and
cost visibility (Task H).

## What "rebuild" means here

A REAL rebuild of the library from `my-data/` on this branch's framework, with the new
mechanisms ON, and the example's documentation updated so a developer who opens it sees —
and is told about — what the framework now does. The original build burned ~21M tokens
(`gpt-5.6-luna`); expect the same order. Use the example's own machinery (`app.py up/init`,
its compose, its ports) — NOT the lynx dev bench; the two stacks must not share tenants,
collections or ports. The `.env` goes into `examples/opc/.env` from the repo root's
(git-ignored, never committed, never printed).

## Deliverables

1. **Engine/config refresh**: the example's engine directory / env enables
   `people,time,attention`; the new knobs (attention half-life/window/evidence chars,
   model pricing from Task H) are STATED with the example's real values; engine.yaml and
   contract hash pins re-recorded per the example's own conventions.
2. **Contract refresh** (`contract.md`): one pass, judgement only where the new mechanisms
   need it — the owner-dialogue sentence (correct/supersede citing the statement), what
   this library's definitions/summaries should say (the overview slots), anything the
   scaffold templates gained since. Do not rewrite the judgement that built a good
   library; extend it.
3. **The build**: `app.py init` over the same 190 sources. Monitor to completion; the
   worker drains compile + projection jobs. Record gate rejections / repairs as the
   original build-record did.
4. **Exercise the use-side, as part of the record**: after the build, run a scripted
   session against the example's own API — a handful of `business` consultations (real
   questions about Seamlog), one `audit`, several `silent`; one `owner-dialogue/v1`
   correction from 林舟 that lands as a supersession; one live-context WS session with a
   short synthetic conversation (eager). The consultations ledger, the access stats, the
   spend report (Task H) and the corrected page are then REAL artifacts a developer can
   open in the browser, not claims in a README.
5. **Prebuilt + bootstrap**: regenerate the prebuilt library so keyless `bootstrap.py`
   restores the NEW library, and reshape the restore itself wherever the new mechanisms
   make the old shape awkward — the owner's ruling (2026-09-01, verbatim): "整体上你不用
   考虑旧版的兼容～ 我们还没 release 呢". No pre-release compatibility burden anywhere in
   this task: replace rather than accommodate.
6. **Build record**: a new `build-record/` run (task book, build log, cost accounting —
   Task H's spend endpoint gives the answering side; compile cost from what H made
   inspectable). The OLD record is REPLACED outright — same ruling; keep only what the
   new record itself wants to cite.
7. **README (both languages)**: a "What this example now shows" section walking the
   developer through: the lens switch (owner cockpit vs reading room), asking as each
   class and seeing the consultation ledger fill, the access card and usage panel, the
   owner statement → supersession page, live context over a transcript, and where the
   money went. Follow the repo's narrative rules: 精炼准确, no scores flexing, no
   commands to the reader.
8. Suites: the repo's suites stay green (`uv run pytest`, hygiene, web untouched by this
   task unless the example's web profile needs a version bump — say so if it does).

## Discipline

- Synthetic data only — the corpus IS synthetic; keep it that way in every new artifact.
- The example's compose/ports only; never the lynx dev bench's stack or tenants.
- Commit in slices that mirror the deliverables; do not push.
- Money: this is a real spend on the order of the original build. Track it as you go
  (Task H makes that visible); if the projected total exceeds ~1.5× the original
  build's, STOP and report rather than pressing on.

## Reply with

The build's shape (sources → documents → claims, rejections/repairs), total cost split
compile vs answering, what bootstrap restores, the use-side artifacts created, README
sections added, and anything this book or the example's machinery got wrong against the
current framework.

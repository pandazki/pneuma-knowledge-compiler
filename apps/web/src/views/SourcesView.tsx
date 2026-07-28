import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Database,
  FileText,
  GitBranch,
  GitCommitHorizontal,
  Layers,
  Loader2,
  Quote,
  X,
} from "lucide-react";
import { useApp } from "@/lib/store";
import { Button, Chip, EmptyState, Eyebrow } from "@/components/ui";
import { fmtTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import * as api from "@/lib/api";

/** Digestion status of a source: live background-job progress (async ingest → index →
 * compile) first, then the settled digested state. Ingest only enqueues now, so a fresh
 * source spends ~a minute in 索引中/编译中 before 已消化 — surfacing that (instead of a static
 * 待编译) is the difference between "working" and "looks stuck". */
function DigestChip({ s, job }: { s: api.SourceSummary; job?: api.JobSummary }) {
  if (job && (job.status === "queued" || job.status === "claimed")) {
    const running = job.status === "claimed";
    const label = job.kind === "index" ? (running ? "索引中" : "待索引") : running ? "编译中" : "排队中";
    return (
      <Chip dotColor="var(--color-open-question)" title={`${job.kind} · ${job.status}`}>
        {running && <Loader2 size={11} className="animate-spin" />} {label}
      </Chip>
    );
  }
  if (s.digested_at) {
    return (
      <Chip dotColor="var(--color-verified)" title={`digested ${s.digested_at}`}>
        已消化
      </Chip>
    );
  }
  if (s.intake_plan?.canonical_treatment === "none") {
    return <Chip title="canonical_treatment=none">不编译</Chip>;
  }
  return (
    <Chip dotColor="var(--color-open-question)" title="尚未编译进 canonical">
      待编译
    </Chip>
  );
}

/** Two knobs of the IntakePlan, rendered as chips (architecture.md §4). */
function PlanChips({ plan }: { plan: api.IntakePlan | null }) {
  if (!plan) return <Chip>无 intake plan</Chip>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Chip title="canonical_treatment">treatment · {plan.canonical_treatment}</Chip>
      <Chip title="semantic_indexing">semantic · {plan.semantic_indexing}</Chip>
    </span>
  );
}

export function SourcesView() {
  const { currentUser, sourceFocus, selection, loadUserDataset } = useApp();
  // A cross-view jump can land here as a `source` selection (溯源动线 落点): select that
  // source once the list loads, and — with a block — scroll it into view + highlight.
  const sourceSel = selection?.kind === "source" ? selection : null;
  const [sources, setSources] = useState<api.SourceSummary[]>([]);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [compiling, setCompiling] = useState(false);
  const [compileNote, setCompileNote] = useState<string | null>(null);
  const [jobs, setJobs] = useState<api.JobSummary[]>([]);

  // source_id → its most-advanced active (queued/claimed) job, so the chip shows the live
  // stage: prefer a claimed job (running) over queued, and index (the earlier stage) so a
  // source reads 索引中 while its index job runs even though its compile job is also queued.
  const activeJobBySource = useMemo(() => {
    const rank = (j: api.JobSummary) =>
      (j.status === "claimed" ? 10 : 0) + (j.kind === "index" ? 1 : 0);
    const m: Record<string, api.JobSummary> = {};
    for (const j of jobs) {
      if (j.status !== "queued" && j.status !== "claimed") continue;
      for (const sid of j.source_ids) {
        if (!m[sid] || rank(j) > rank(m[sid])) m[sid] = j;
      }
    }
    return m;
  }, [jobs]);

  const pendingCount = sources.filter(
    (s) => !s.digested_at && s.intake_plan?.canonical_treatment !== "none",
  ).length;

  async function onCompile() {
    if (!currentUser) return;
    setCompiling(true);
    setCompileNote(null);
    try {
      const res = await api.compile(currentUser);
      setCompileNote(
        res.enqueued.length
          ? `已入队 ${res.enqueued.length} 个 compile job（需 worker 在跑）`
          : "没有待编译的 source",
      );
      setReloadKey((k) => k + 1);
      await loadUserDataset();
    } catch (e) {
      setCompileNote(`入队失败：${(e as Error).message}`);
    } finally {
      setCompiling(false);
    }
  }

  // Load the source list whenever the user changes (or a compile refresh is requested).
  useEffect(() => {
    if (!currentUser) {
      setSources([]);
      setListState("ready");
      return;
    }
    let live = true;
    setListState("loading");
    api
      .listSources(currentUser)
      .then((rows) => {
        if (!live) return;
        setSources(rows);
        setListState("ready");
        setSelectedId((prev) => {
          const sel = sourceSel?.id;
          if (sel && rows.some((r) => r.source_id === sel)) return sel;
          const focus = sourceFocus?.sourceId;
          if (focus && rows.some((r) => r.source_id === focus)) return focus;
          if (prev && rows.some((r) => r.source_id === prev)) return prev;
          return rows[0]?.source_id ?? null;
        });
      })
      .catch((e: Error) => {
        if (!live) return;
        setListError(e.message);
        setListState("error");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser, reloadKey]);

  // Poll background jobs while any are active so the per-source chip advances
  // 索引中 → 编译中 → 已消化 without a manual refresh; when work drains, reload the source
  // list once so digested_at settles. Idle → no polling.
  useEffect(() => {
    if (!currentUser) {
      setJobs([]);
      return;
    }
    let live = true;
    let timer: number | undefined;
    let hadActive = false;
    const tick = async () => {
      try {
        const js = await api.listJobs(currentUser);
        if (!live) return;
        setJobs(js);
        const active = js.some((j) => j.status === "queued" || j.status === "claimed");
        if (hadActive && !active) setReloadKey((k) => k + 1); // work finished → refresh sources
        hadActive = active;
        if (active) timer = window.setTimeout(tick, 2500);
      } catch {
        if (live) timer = window.setTimeout(tick, 4000);
      }
    };
    void tick();
    return () => {
      live = false;
      if (timer) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser, reloadKey]);

  // A Recall hit (or other jump) focuses a specific source.
  useEffect(() => {
    if (sourceFocus && sources.some((r) => r.source_id === sourceFocus.sourceId)) {
      setSelectedId(sourceFocus.sourceId);
    }
  }, [sourceFocus, sources]);

  // A `source` selection (citation / 消化来源 jump) selects that source once it exists in
  // the list. Keyed on id+block so re-clicking the same badge with a different block
  // re-focuses; a manual list click in between still sticks (deps don't re-fire).
  useEffect(() => {
    if (sourceSel && sources.some((r) => r.source_id === sourceSel.id)) {
      setSelectedId(sourceSel.id);
    }
  }, [sourceSel?.id, sourceSel?.block, sources]);

  if (!currentUser) {
    return (
      <EmptyState
        icon={<Database size={28} />}
        title="未选择用户"
        hint="在右上角选择一个 user_id 以查看其 sources。数据可用 examples/rag_e2e.py 灌入。"
      />
    );
  }
  if (listState === "error") {
    return (
      <EmptyState icon={<Database size={28} />} title="加载 sources 失败" hint={listError} />
    );
  }
  if (listState === "ready" && sources.length === 0) {
    return (
      <EmptyState
        icon={<Database size={28} />}
        title="该用户暂无 source"
        hint="用「增量实验」面板添加一段对话，或运行 examples/rag_e2e.py。"
      />
    );
  }

  // A source jump whose id is not in this user's list (expired / deleted): keep the
  // 溯源意图 alive with a clear empty state instead of silently opening some other source.
  const selectedMissing =
    !!sourceSel &&
    sourceSel.id === selectedId &&
    listState === "ready" &&
    !sources.some((s) => s.source_id === sourceSel.id);
  // Highlight range for the detail pane: a `source` selection's block wins, else a Recall
  // focus. Both only apply to the source actually open.
  const detailHighlight =
    sourceSel && sourceSel.id === selectedId && sourceSel.block != null
      ? { start: sourceSel.block, end: sourceSel.block }
      : sourceFocus && sourceFocus.sourceId === selectedId
        ? { start: sourceFocus.blockStart, end: sourceFocus.blockEnd }
        : null;

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      {/* left rail: source list */}
      <aside className="max-h-56 w-full flex-none overflow-y-auto border-b border-border bg-card md:max-h-none md:w-80 md:border-b-0 md:border-r">
        <div className="sticky top-0 z-10 border-b border-border-subtle bg-card px-3 py-3">
          <div className="flex items-center gap-2">
            <Eyebrow>Sources · {sources.length}</Eyebrow>
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              disabled={compiling || pendingCount === 0}
              onClick={onCompile}
              title="把未消化的 source 入 compile 队列（幂等）"
            >
              {compiling ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <GitBranch size={13} />
              )}
              编译{pendingCount > 0 ? ` (${pendingCount})` : ""}
            </Button>
          </div>
          {compileNote && (
            <div className="mt-1.5 flex items-start gap-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
              <CheckCircle2 size={11} className="mt-0.5 flex-none text-[var(--color-success)]" />
              {compileNote}
            </div>
          )}
        </div>
        {sources.map((s) => (
          <button
            key={s.source_id}
            onClick={() => setSelectedId(s.source_id)}
            className={cn(
              "w-full border-b border-border px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring",
              selectedId === s.source_id ? "bg-accent" : "hover:bg-accent",
            )}
          >
            <div className="flex items-center gap-2 text-xs">
              <FileText size={13} className="flex-none text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate font-medium">{s.title}</span>
              <span className="ml-auto font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                {s.block_count} blk
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Chip>{s.kind}</Chip>
              <Chip>{s.source_class}</Chip>
              <DigestChip s={s} job={activeJobBySource[s.source_id]} />
            </div>
            <div className="mt-1.5 font-mono text-[length:var(--text-2xs)] text-muted-foreground">
              {fmtTime(s.created_at)}
            </div>
          </button>
        ))}
      </aside>

      {/* detail */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {selectedMissing ? (
          <EmptyState
            icon={<FileText size={28} />}
            title="原文已不可用"
            hint="可能已过期或被删除——溯源链接指向的 source 不在当前快照中。"
          />
        ) : selectedId ? (
          <SourceDetail
            key={selectedId}
            userId={currentUser}
            sourceId={selectedId}
            highlight={detailHighlight}
          />
        ) : (
          <EmptyState icon={<FileText size={28} />} title="选择一个 source" />
        )}
      </div>
    </div>
  );
}

function SourceDetail({
  userId,
  sourceId,
  highlight,
}: {
  userId: string;
  sourceId: string;
  highlight: { start: number | null; end: number | null } | null;
}) {
  const { model, jump } = useApp();
  const [detail, setDetail] = useState<api.SourceDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [verbatim, setVerbatim] = useState<{ label: string; text: string } | null>(null);
  const blockRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // The first matching compiled claim makes the source → claim → Git path tangible in
  // one viewport. This is derived from the exported projection, never invented UI data.
  const provenance = useMemo(() => {
    if (!model) return null;
    for (const doc of model.dataset.documents.documents) {
      for (const claim of doc.claims) {
        const citation = claim.citations.find((c) => c.source_id === sourceId);
        if (!citation) continue;
        const patches = doc.document_id
          ? model.patchesByDocId.get(doc.document_id) ?? []
          : model.patchesByPath.get(doc.path) ?? [];
        const patch =
          [...patches].reverse().find((p) => p.sources_consumed.includes(sourceId)) ??
          patches[patches.length - 1] ??
          null;
        return { doc, claim, citation, patch };
      }
    }
    return null;
  }, [model, sourceId]);

  useEffect(() => {
    let live = true;
    setState("loading");
    setVerbatim(null);
    api
      .getSource(userId, sourceId)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        setState("ready");
      })
      .catch((e: Error) => {
        if (!live) return;
        setError(e.message);
        setState("error");
      });
    return () => {
      live = false;
    };
  }, [userId, sourceId]);

  // Scroll the focused block range into view once the detail is loaded.
  useEffect(() => {
    if (state !== "ready" || !highlight || highlight.start == null) return;
    const el = blockRefs.current.get(highlight.start);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [state, highlight, detail]);

  const inHighlight = useMemo(() => {
    if (!highlight || highlight.start == null) return () => false;
    const start = highlight.start;
    const end = highlight.end ?? highlight.start;
    return (idx: number) => idx >= start && idx <= end;
  }, [highlight]);

  async function onFetchSection(path: string[]) {
    setVerbatim({ label: path.join(" / ") || "(root)", text: "…" });
    try {
      const { text } = await api.fetchLocator(userId, sourceId, { section: path });
      setVerbatim({ label: path.join(" / ") || "(root)", text });
    } catch (e) {
      setVerbatim({ label: path.join(" / ") || "(root)", text: `L0 fetch 失败：${(e as Error).message}` });
    }
  }

  if (state === "loading") {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
        <Loader2 size={18} className="animate-spin" /> 加载 source…
      </div>
    );
  }
  if (state === "error" || !detail) {
    return <EmptyState icon={<FileText size={28} />} title="加载详情失败" hint={error} />;
  }

  return (
    <div>
      {/* header */}
      <div className="border-b border-border bg-card px-5 py-4">
        <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
          <FileText size={15} /> {detail.title}
        </div>
        <div className="mt-1 break-all font-mono text-[length:var(--text-2xs)] text-muted-foreground">
          {detail.source_id} · {detail.mime} · {fmtTime(detail.created_at)}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Chip>{detail.kind}</Chip>
          <Chip>{detail.source_class}</Chip>
          <PlanChips plan={detail.intake_plan} />
        </div>
        {detail.intake_plan?.rationale && (
          <div className="mt-2 text-[length:var(--text-2xs)] leading-4 text-muted-foreground">
            {detail.intake_plan.rationale}
          </div>
        )}
      </div>

      {/* verbatim L0 fetch result */}
      {verbatim && (
        <div className="border-b border-border bg-[var(--color-surface-muted)] px-5 py-3">
          <div className="mb-1 flex items-center gap-2 text-[length:var(--text-2xs)] font-medium text-muted-foreground">
            <Quote size={12} /> L0 verbatim · {verbatim.label}
            <button
              className="ml-auto inline-flex items-center rounded-sm p-0.5 hover:bg-accent"
              aria-label="关闭"
              onClick={() => setVerbatim(null)}
            >
              <X size={12} />
            </button>
          </div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[length:var(--text-2xs)] leading-5">
            {verbatim.text}
          </pre>
        </div>
      )}

      {provenance && (
        <section className="pneuma-provenance-route" aria-label="证据线路">
          <div className="pneuma-provenance-heading">
            <span>PROVENANCE ROUTE</span>
            <strong>来源 → Claim → Git</strong>
          </div>
          <div className="pneuma-provenance-strip">
            <article className="pneuma-provenance-card pneuma-registration-frame">
              <div className="pneuma-provenance-stage">01 · SOURCE SPAN</div>
              <div className="pneuma-provenance-id">
                {sourceId.slice(0, 8)} · ¶{provenance.citation.from}–{provenance.citation.to}
              </div>
              <p>
                {provenance.citation.snippet ||
                  detail.blocks
                    .filter(
                      (block) =>
                        block.index >= provenance.citation.from &&
                        block.index <= provenance.citation.to,
                    )
                    .map((block) => block.text)
                    .join(" ")}
              </p>
            </article>
            <div className="pneuma-provenance-connector" aria-hidden>
              <ArrowRight size={14} />
            </div>
            <article className="pneuma-provenance-card pneuma-registration-frame">
              <div className="pneuma-provenance-stage">02 · CANONICAL CLAIM</div>
              <div className="pneuma-provenance-id">
                {provenance.doc.path} · {provenance.claim.anchor ?? "no-anchor"}
              </div>
              <p>{provenance.claim.text}</p>
              {provenance.doc.document_id && (
                <button
                  type="button"
                  onClick={() =>
                    jump({ kind: "document", id: provenance.doc.document_id! }, "library")
                  }
                >
                  <BookOpen size={12} /> 打开 Canonical
                </button>
              )}
            </article>
            <div className="pneuma-provenance-connector" aria-hidden>
              <ArrowRight size={14} />
            </div>
            <article className="pneuma-provenance-card pneuma-registration-frame">
              <div className="pneuma-provenance-stage">03 · COMPILE / GIT</div>
              {provenance.patch ? (
                <>
                  <div className="pneuma-provenance-id">
                    {provenance.patch.patch_id.slice(0, 10)} ·{" "}
                    {provenance.patch.job_id?.slice(0, 8) ?? "no-job"}
                  </div>
                  <p>
                    {provenance.patch.documents?.find(
                      (entry) => entry.document_id === provenance.doc.document_id,
                    )?.change_type ?? "modified"}{" "}
                    · {provenance.patch.lineage.model ?? "model unavailable"}
                  </p>
                  {provenance.doc.document_id && (
                    <button
                      type="button"
                      onClick={() =>
                        jump({ kind: "document", id: provenance.doc.document_id! }, "history")
                      }
                    >
                      <GitCommitHorizontal size={12} /> 查看版本记录
                    </button>
                  )}
                </>
              ) : (
                <p>该 claim 尚无可用的 Git patch 记录。</p>
              )}
            </article>
          </div>
        </section>
      )}

      {/* structure map */}
      {detail.structure.sections.length > 0 && (
        <div className="border-b border-border px-5 py-4">
          <div className="mb-2 flex items-center gap-1.5 text-[length:var(--text-2xs)] font-medium text-muted-foreground">
            <Layers size={12} /> 结构地图 · 点击节点做 L0 直取
          </div>
          <div className="flex flex-wrap gap-1.5">
            {detail.structure.sections.map((sec, i) => (
              <Chip
                key={i}
                onClick={() => onFetchSection(sec.path)}
                title={`blocks ${sec.start_block}–${sec.end_block}`}
              >
                {sec.path.join(" / ") || "(root)"}{" "}
                <span className="font-mono text-muted-foreground">
                  ¶{sec.start_block}–{sec.end_block}
                </span>
              </Chip>
            ))}
          </div>
        </div>
      )}

      {/* blocks full text */}
      <div className="px-5 py-4">
        <div className="mb-2 text-[length:var(--text-2xs)] font-medium text-muted-foreground">
          BLOCKS · {detail.blocks.length}
        </div>
        <div className="space-y-2">
          {detail.blocks.map((b) => (
            <div
              key={b.index}
              ref={(el) => {
                if (el) blockRefs.current.set(b.index, el);
                else blockRefs.current.delete(b.index);
              }}
              className={cn(
                "grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 border-l-2 py-1 pl-2 text-sm",
                inHighlight(b.index)
                  ? "border-[var(--color-accent)] bg-[var(--color-surface-muted)]"
                  : "border-transparent",
              )}
            >
              <span className="pt-0.5 text-right font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                ¶{b.index}
              </span>
              <span className="min-w-0 break-words leading-6">{b.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

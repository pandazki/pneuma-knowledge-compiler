import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Sparkles,
  GitBranch,
  FileText,
  Loader2,
  Package,
  Layers,
  Check,
  X,
  AlertTriangle,
  RefreshCw,
  Clock,
  ChevronRight,
  ChevronDown,
  Boxes,
  Wand2,
  ArrowRight,
} from "lucide-react";
import { useApp } from "@/lib/store";
import { Button, Chip, EmptyState, Eyebrow } from "@/components/ui";
import { fmtTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import { extractClaimLabel } from "@/lib/claim";
import { ClaimLabelBadge } from "@/components/ClaimView";
import { ApiError } from "@/lib/api";
import * as api from "@/lib/api";

/* --------------------------------------------------------------- status + ttl helpers */

/** status chip label + dot token. draft = amber (awaiting review), adopted = verified,
 * aborted = danger, the rest read as neutral/info. */
function statusMeta(status: string): { label: string; color: string } {
  switch (status) {
    case "draft":
      return { label: "草案", color: "var(--color-open-question)" };
    case "adopted":
      return { label: "已采纳", color: "var(--color-verified)" };
    case "dropped":
      return { label: "已放弃", color: "var(--color-text-tertiary)" };
    case "expired":
      return { label: "已过期", color: "var(--color-text-tertiary)" };
    case "aborted":
      return { label: "已中止", color: "var(--color-danger)" };
    case "no_change":
      return { label: "无变化", color: "var(--color-info)" };
    default:
      return { label: status, color: "var(--color-text-tertiary)" };
  }
}

/** ms until a draft's review window closes (created_at + TTL − now); null when undatable. */
function ttlRemainingMs(createdAt: string | null): number | null {
  if (!createdAt) return null;
  const created = new Date(createdAt).getTime();
  if (isNaN(created)) return null;
  return created + api.EVOLVE_DRAFT_TTL_HOURS * 3600_000 - Date.now();
}

function fmtTtl(ms: number): string {
  if (ms <= 0) return "已超评审窗口";
  const h = Math.floor(ms / 3600_000);
  const m = Math.floor((ms % 3600_000) / 60_000);
  return h > 0 ? `剩 ${h}h${m}m` : `剩 ${m}m`;
}

/* ---------------------------------------------------------------- lightweight line diff */

type DiffRow = { type: "same" | "add" | "del"; text: string };

/** Minimal LCS line diff — no third-party lib. O(n·m) over line arrays; canonical doc
 * bodies are claims-sized so this stays cheap. Produces a unified +/− row stream. */
function lineDiff(oldStr: string, newStr: string): DiffRow[] {
  const A = oldStr.split("\n");
  const B = newStr.split("\n");
  const n = A.length;
  const m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      rows.push({ type: "same", text: A[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: "del", text: A[i] });
      i++;
    } else {
      rows.push({ type: "add", text: B[j] });
      j++;
    }
  }
  while (i < n) rows.push({ type: "del", text: A[i++] });
  while (j < m) rows.push({ type: "add", text: B[j++] });
  return rows;
}

function DiffBlock({ oldBody, newBody }: { oldBody: string; newBody: string }) {
  const rows = useMemo(() => lineDiff(oldBody, newBody), [oldBody, newBody]);
  const adds = rows.filter((r) => r.type === "add").length;
  const dels = rows.filter((r) => r.type === "del").length;
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2 text-[length:var(--text-2xs)] text-muted-foreground">
        <span className="text-[var(--color-verified)]">+{adds}</span>
        <span className="text-[var(--color-danger)]">−{dels}</span>
      </div>
      <div className="overflow-x-auto rounded-sm border border-border">
        <pre className="min-w-max font-mono text-[length:var(--text-2xs)] leading-5">
          {rows.map((r, k) => (
            <div
              key={k}
              className="flex border-l-2 pl-1.5 pr-3"
              style={{
                borderColor:
                  r.type === "add"
                    ? "var(--color-verified)"
                    : r.type === "del"
                      ? "var(--color-danger)"
                      : "transparent",
                background:
                  r.type === "same" ? "transparent" : "var(--color-surface-muted)",
              }}
            >
              <span
                className="mr-2 w-3 flex-none select-none text-center"
                style={{
                  color:
                    r.type === "add"
                      ? "var(--color-verified)"
                      : r.type === "del"
                        ? "var(--color-danger)"
                        : "var(--color-text-tertiary)",
                }}
              >
                {r.type === "add" ? "+" : r.type === "del" ? "−" : " "}
              </span>
              <span className="whitespace-pre-wrap break-words">{r.text || " "}</span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- skill panel (top) */

/** origin → human label for the 量身定制 pack matrix. */
function originLabel(origin: string | null): string {
  switch (origin) {
    case "matrix":
      return "matrix";
    case "derived":
      return "derived";
    case "evolved":
      return "evolved";
    default:
      return origin || "—";
  }
}

function SkillPanel({
  userId,
  onTriggered,
  reloadKey,
}: {
  userId: string;
  onTriggered: () => void;
  reloadKey: number;
}) {
  const [skill, setSkill] = useState<api.SkillInfo | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [note, setNote] = useState<{ kind: "ok" | "warn" | "err"; text: string } | null>(null);

  useEffect(() => {
    let live = true;
    setState("loading");
    api
      .getSkillInfo(userId)
      .then((s) => {
        if (!live) return;
        setSkill(s);
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
  }, [userId, reloadKey]);

  async function onTrigger() {
    setTriggering(true);
    setNote(null);
    try {
      await api.triggerEvolve(userId);
      setNote({ kind: "ok", text: "已入队 evolve 任务——worker 跑完后草案会出现在下方列表。" });
      onTriggered();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // 已有待评审草案或排队中的 evolve（single-flight）。
        setNote({ kind: "warn", text: e.message });
        onTriggered(); // refresh so the existing draft/task is visible
      } else {
        setNote({ kind: "err", text: `触发失败：${(e as Error).message}` });
      }
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div className="border-b border-border bg-card px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <Sparkles size={13} className="text-[var(--color-accent)]" />
          <Eyebrow>量身定制 · 当前生效 skill</Eyebrow>
        </div>
        <Button variant="primary" size="sm" onClick={onTrigger} disabled={triggering}>
          {triggering ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
          触发 evolve
        </Button>
      </div>

      {state === "loading" && (
        <div className="mt-3 flex items-center gap-2 text-[length:var(--text-sm)] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> 加载 skill…
        </div>
      )}
      {state === "error" && (
        <div className="mt-3 text-[length:var(--text-sm)] text-[var(--color-danger)]">
          加载 skill 失败：{error}
        </div>
      )}
      {state === "ready" && skill && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Layers size={12} /> version{" "}
              <span className="font-mono text-foreground">{skill.version}</span>
            </span>
            <span className="inline-flex items-center gap-1">
              base <span className="font-mono text-foreground">{skill.base_version}</span>
            </span>
            <span className="inline-flex items-center gap-1 font-mono">
              #{skill.content_hash.slice(0, 10)}
            </span>
            <span className="inline-flex items-center gap-1">
              <Boxes size={12} /> {skill.packs.length} packs
            </span>
          </div>

          {skill.packs.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {skill.packs.map((p, i) => (
                <div key={p.pack_id ?? i} className="rounded-sm border border-border bg-background p-2.5">
                  <div className="flex items-center gap-1.5">
                    <Package size={12} className="flex-none text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate font-mono text-[length:var(--text-xs)] text-foreground">
                      {p.pack_id ?? "—"}
                    </span>
                    <Chip className="flex-none">{originLabel(p.origin)}</Chip>
                  </div>
                  {p.extra_path_templates.length > 0 && (
                    <div className="mt-1.5 flex flex-col gap-0.5">
                      {p.extra_path_templates.map((t, k) => (
                        <span
                          key={k}
                          className="truncate font-mono text-[length:var(--text-2xs)] text-muted-foreground"
                          title={t}
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {skill.path_templates.length > 0 && (
            <div>
              <div className="mb-1 text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground">
                路径模板家族 · {skill.path_templates.length}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {skill.path_templates.map((t, i) => (
                  <Chip key={i} className="font-mono">
                    {t}
                  </Chip>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {note && (
        <div
          className="mt-3 flex items-start gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-[length:var(--text-xs)]"
          style={{ background: "var(--color-surface-muted)" }}
        >
          {note.kind === "ok" ? (
            <Check size={13} className="mt-0.5 flex-none text-[var(--color-success)]" />
          ) : (
            <AlertTriangle
              size={13}
              className="mt-0.5 flex-none"
              style={{
                color: note.kind === "err" ? "var(--color-danger)" : "var(--color-open-question)",
              }}
            />
          )}
          <span className={cn(note.kind === "err" && "text-[var(--color-danger)]")}>{note.text}</span>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------- adopt confirm */

function AdoptDialog({
  onConfirm,
  onCancel,
  busy,
}: {
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel, busy]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label="采纳 evolve 草案"
    >
      <div
        className="absolute inset-0 bg-[var(--color-scrim,rgba(0,0,0,0.45))]"
        onClick={() => !busy && onCancel()}
        aria-hidden
      />
      <div
        className="relative w-full max-w-md rounded-sm border border-border bg-popover text-popover-foreground"
        style={{ boxShadow: "var(--shadow-overlay)" }}
      >
        <div className="flex items-center gap-1.5 border-b border-border px-4 py-3 text-[length:var(--text-sm)] font-medium">
          <GitBranch size={14} /> 采纳这份草案？
        </div>
        <div className="px-4 py-4 text-[length:var(--text-sm)] leading-6 text-foreground">
          将把该 evolve 分支<strong className="font-medium">机械合并到主线并重建索引（L3）</strong>。
          合并写在 git 上——如结果不理想，可通过 git 历史回滚。此操作会入队后台任务，稍后生效。
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" size="sm" onClick={onConfirm} disabled={busy}>
            {busy && <Loader2 size={13} className="animate-spin" />} 确认采纳
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------- task detail */

function TaskDetail({
  userId,
  taskId,
  onDecided,
}: {
  userId: string;
  taskId: string;
  onDecided: () => void;
}) {
  const [detail, setDetail] = useState<api.EvolveTaskDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [openFiles, setOpenFiles] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [acting, setActing] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  // claim-prefix vocabulary from the store's dataset meta (same data flow as the other views).
  const claimLabels = useApp((s) => s.model?.dataset.claimLabels);

  const load = useCallback(() => {
    let live = true;
    setState("loading");
    api
      .getEvolveTask(userId, taskId)
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
  }, [userId, taskId]);

  useEffect(() => load(), [load]);

  async function onAdopt() {
    setActing(true);
    setActionErr(null);
    try {
      await api.adoptEvolveTask(userId, taskId);
      setConfirming(false);
      onDecided();
      load();
    } catch (e) {
      setActionErr(`采纳失败：${(e as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  async function onDrop() {
    setActing(true);
    setActionErr(null);
    try {
      await api.dropEvolveTask(userId, taskId);
      onDecided();
      load();
    } catch (e) {
      setActionErr(`放弃失败：${(e as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  if (state === "loading") {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
        <Loader2 size={18} className="animate-spin" /> 加载任务…
      </div>
    );
  }
  if (state === "error" || !detail) {
    return <EmptyState icon={<GitBranch size={28} />} title="加载任务失败" hint={error} />;
  }

  const meta = statusMeta(detail.status);
  const s = detail.summary;
  const isDraft = detail.status === "draft";
  const ttl = isDraft ? ttlRemainingMs(detail.created_at) : null;
  const adoptedEntries = s ? Object.entries(s.adopted_by_document) : [];

  return (
    <div className="min-w-0">
      {/* header */}
      <div className="border-b border-border bg-card px-6 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Chip dotColor={meta.color}>{meta.label}</Chip>
          <span className="font-mono text-[length:var(--text-sm)] text-foreground">{detail.task_id}</span>
          {ttl != null && (
            <span className="inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-muted-foreground">
              <Clock size={11} /> {fmtTtl(ttl)}
            </span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--text-2xs)] text-muted-foreground">
          <span>创建 {fmtTime(detail.created_at)}</span>
          {detail.decided_at && <span>决定 {fmtTime(detail.decided_at)}</span>}
          {detail.base_ref && (
            <span className="font-mono">base {detail.base_ref.slice(0, 10)}</span>
          )}
          {detail.branch && <span className="font-mono">branch {detail.branch}</span>}
        </div>
        {detail.detail && (
          <div className="mt-2 text-[length:var(--text-sm)] text-foreground">{detail.detail}</div>
        )}

        {isDraft && (
          <div className="mt-3 flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={() => setConfirming(true)} disabled={acting}>
              <Check size={13} /> 采纳
            </Button>
            <Button variant="outline" size="sm" onClick={onDrop} disabled={acting}>
              {acting ? <Loader2 size={13} className="animate-spin" /> : <X size={13} />} 放弃
            </Button>
          </div>
        )}
        {actionErr && (
          <div className="mt-2 text-[length:var(--text-xs)] text-[var(--color-danger)]">{actionErr}</div>
        )}
      </div>

      <div className="max-w-3xl space-y-7 px-6 py-6">
        {/* 1 · mechanical summary */}
        <section>
          <Eyebrow>机械摘要</Eyebrow>
          {s ? (
            <>
              <div className="mt-2 grid grid-cols-3 gap-3">
                <StatCell label="新建文档" value={s.new_documents} />
                <StatCell label="搬移 claim" value={s.moved_claims} />
                <StatCell label="合并 claim" value={s.merged_claims} />
              </div>
              {adoptedEntries.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1.5 text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground">
                    各新文档收编条数
                  </div>
                  <div className="flex flex-col gap-1">
                    {adoptedEntries.map(([path, count]) => (
                      <div
                        key={path}
                        className="flex items-center gap-2 rounded-sm border border-border px-2.5 py-1.5 text-[length:var(--text-xs)]"
                      >
                        <FileText size={12} className="flex-none text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate font-mono">{path}</span>
                        <span className="flex-none font-mono text-muted-foreground">
                          {count} 条
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="mt-2 text-[length:var(--text-sm)] text-muted-foreground">本任务无机械摘要。</div>
          )}
          {detail.rationale && (
            <div
              className="mt-3 rounded-sm px-3 py-2.5 text-[length:var(--text-sm)] leading-6 text-foreground"
              style={{
                borderLeft: "2px solid var(--color-accent)",
                background: "var(--color-surface-muted)",
              }}
            >
              <div className="mb-1 flex items-center gap-1.5 text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground">
                <Sparkles size={11} className="text-[var(--color-accent)]" /> 提案证据 · rationale
              </div>
              {detail.rationale}
            </div>
          )}
        </section>

        {/* 2 · dropped anchors */}
        {detail.dropped.length > 0 && (
          <section>
            <Eyebrow>合并 / 丢弃的 claim · {detail.dropped.length}</Eyebrow>
            <div className="mt-2 flex flex-col gap-1.5">
              {detail.dropped.map((d) => {
                const labeled = extractClaimLabel(d.text, claimLabels);
                return (
                <div
                  key={d.anchor}
                  className="rounded-sm px-3 py-2 text-[length:var(--text-xs)]"
                  style={{
                    borderLeft: "2px solid var(--color-danger)",
                    background: "var(--color-surface-muted)",
                  }}
                >
                  <div className="flex items-center gap-2 text-[length:var(--text-2xs)] text-muted-foreground">
                    <span className="font-mono">c:{d.anchor}</span>
                    <span className="min-w-0 truncate font-mono">{d.old_path}</span>
                  </div>
                  <div className="mt-1 leading-5">
                    {labeled && (
                      <>
                        <ClaimLabelBadge label={labeled.label} />{" "}
                      </>
                    )}
                    <span
                      className="line-through"
                      style={{ color: "var(--color-text-secondary)" }}
                    >
                      {labeled ? labeled.rest : d.text}
                    </span>
                  </div>
                </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 3 · changed files diff drill-down */}
        {detail.changed_files.length > 0 ? (
          <section>
            <Eyebrow>变更文件 · {detail.changed_files.length}</Eyebrow>
            <div className="mt-2 flex flex-col gap-1.5">
              {detail.changed_files.map((f) => {
                const open = openFiles.has(f.path);
                const created = f.old_body === "";
                const removed = f.new_body === "";
                return (
                  <div key={f.path} className="rounded-sm border border-border">
                    <button
                      onClick={() =>
                        setOpenFiles((prev) => {
                          const next = new Set(prev);
                          if (next.has(f.path)) next.delete(f.path);
                          else next.add(f.path);
                          return next;
                        })
                      }
                      className="flex w-full items-center gap-2 px-2.5 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {open ? (
                        <ChevronDown size={13} className="flex-none text-muted-foreground" />
                      ) : (
                        <ChevronRight size={13} className="flex-none text-muted-foreground" />
                      )}
                      <FileText size={12} className="flex-none text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate font-mono text-[length:var(--text-xs)]">{f.path}</span>
                      {created && (
                        <span className="flex-none text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-[var(--color-verified)]">
                          created
                        </span>
                      )}
                      {removed && (
                        <span className="flex-none text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-[var(--color-danger)]">
                          removed
                        </span>
                      )}
                    </button>
                    {open && (
                      <div className="border-t border-border px-2.5 py-2.5">
                        <DiffBlock oldBody={f.old_body} newBody={f.new_body} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ) : (
          isDraft && (
            <section>
              <Eyebrow>变更文件</Eyebrow>
              <div className="mt-2 text-[length:var(--text-sm)] text-muted-foreground">
                本草案无文件级差异，或分支已不可读。
              </div>
            </section>
          )
        )}
        {!isDraft && detail.changed_files.length === 0 && (
          <div className="text-[length:var(--text-xs)] text-muted-foreground">
            任务已决定，分支已回收——仅保留上方机械摘要，文件级差异不再可用。
          </div>
        )}
      </div>

      {confirming && (
        <AdoptDialog onConfirm={onAdopt} onCancel={() => setConfirming(false)} busy={acting} />
      )}
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-sm border border-border bg-card p-3 text-center">
      <div className="text-[length:var(--text-2xl)] font-light text-foreground">{value}</div>
      <div className="mt-0.5 text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- the view */

export function EvolveView() {
  const currentUser = useApp((s) => s.currentUser);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);

  const [tasks, setTasks] = useState<api.EvolveTaskSummary[]>([]);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // Short bounded poll after a trigger, until a new draft materializes from the worker.
  const pollLeft = useRef(0);

  const selectedTaskId = selection?.kind === "evolve-task" ? selection.id : null;

  // load task list per user + on refresh
  useEffect(() => {
    if (!currentUser) {
      setTasks([]);
      setListState("ready");
      return;
    }
    let live = true;
    setListState("loading");
    api
      .listEvolveTasks(currentUser)
      .then((rows) => {
        if (!live) return;
        setTasks(rows);
        setListState("ready");
      })
      .catch((e: Error) => {
        if (!live) return;
        setListError(e.message);
        setListState("error");
      });
    return () => {
      live = false;
    };
  }, [currentUser, reloadKey]);

  // Bounded polling: after triggering an evolve, re-list every 3s for up to ~60s so the
  // async worker's fresh draft appears without a manual refresh. Stops early on task growth.
  useEffect(() => {
    if (!currentUser || pollLeft.current <= 0) return;
    const prevCount = tasks.length;
    const timer = window.setTimeout(async () => {
      try {
        const rows = await api.listEvolveTasks(currentUser);
        setTasks(rows);
        setListState("ready");
        if (rows.length > prevCount) pollLeft.current = 0;
        else pollLeft.current -= 1;
      } catch {
        pollLeft.current -= 1;
      }
      setReloadKey((k) => k + 1); // re-run this effect (and SkillPanel) for the next tick
    }, 3000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser, reloadKey]);

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);
  const startPoll = useCallback(() => {
    pollLeft.current = 20;
    setReloadKey((k) => k + 1);
  }, []);

  const activeTaskId = useMemo(() => {
    if (selectedTaskId && tasks.some((t) => t.task_id === selectedTaskId)) return selectedTaskId;
    return tasks[0]?.task_id ?? null;
  }, [selectedTaskId, tasks]);

  if (!currentUser) {
    return (
      <EmptyState
        icon={<GitBranch size={28} />}
        title="未选择用户"
        hint="在右上角选择一个 user_id 以查看其 schema-evolve 与量身定制 skill。"
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <SkillPanel userId={currentUser} onTriggered={startPoll} reloadKey={reloadKey} />

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* task list rail */}
        <aside className="max-h-56 w-full flex-none overflow-y-auto border-b border-border bg-card md:max-h-none md:w-80 md:border-b-0 md:border-r">
          <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border-subtle bg-card px-3 py-3">
            <Eyebrow>Evolve 任务 · {tasks.length}</Eyebrow>
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto"
              onClick={refresh}
              aria-label="刷新任务列表"
              title="刷新"
            >
              <RefreshCw size={13} />
            </Button>
          </div>

          {listState === "loading" && (
            <div className="flex items-center gap-2 px-4 py-6 text-[length:var(--text-sm)] text-muted-foreground">
              <Loader2 size={14} className="animate-spin" /> 加载任务…
            </div>
          )}
          {listState === "error" && (
            <div className="px-4 py-6 text-[length:var(--text-sm)] text-[var(--color-danger)]">
              加载失败：{listError}
            </div>
          )}
          {listState === "ready" && tasks.length === 0 && (
            <div className="px-4 py-6 text-[length:var(--text-sm)] text-muted-foreground">
              暂无 evolve 任务。点上方「触发 evolve」发起一次 schema 重组提案。
            </div>
          )}

          {tasks.map((t) => {
            const meta = statusMeta(t.status);
            const active = t.task_id === activeTaskId;
            const ttl = t.status === "draft" ? ttlRemainingMs(t.created_at) : null;
            return (
              <button
                key={t.task_id}
                onClick={() => select({ kind: "evolve-task", id: t.task_id })}
                className={cn(
                  "w-full border-b border-border px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active ? "bg-accent" : "hover:bg-accent",
                )}
              >
                <div className="flex items-center gap-2">
                  <Chip dotColor={meta.color}>{meta.label}</Chip>
                  {ttl != null && (
                    <span className="ml-auto inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-muted-foreground">
                      <Clock size={10} /> {fmtTtl(ttl)}
                    </span>
                  )}
                </div>
                <div className="mt-1.5 truncate font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                  {t.task_id}
                </div>
                <div className="mt-0.5 font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                  {fmtTime(t.created_at)}
                </div>
              </button>
            );
          })}
        </aside>

        {/* detail */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {activeTaskId ? (
            <TaskDetail
              key={activeTaskId}
              userId={currentUser}
              taskId={activeTaskId}
              onDecided={startPoll}
            />
          ) : (
            <EmptyState
              icon={<ArrowRight size={28} />}
              title="选择一个 evolve 任务"
              hint="左侧列表选一项查看机械摘要、dropped 清单与文件差异。"
            />
          )}
        </div>
      </div>
    </div>
  );
}

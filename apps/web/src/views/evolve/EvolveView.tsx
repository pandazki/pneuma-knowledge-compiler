import { useCallback, useEffect, useMemo, useState } from "react";
import { Sprout, UserRoundX } from "lucide-react";
import { useApp } from "@/lib/store";
import * as api from "@/lib/api";
import { ApiError, EVOLVE_DRAFT_TTL_HOURS } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Badge, type BadgeTone } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Dialog } from "@/ui/Dialog";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";

/* ------------------------------------------------------------ 状态与 TTL */

const TERMINAL: ReadonlySet<string> = new Set([
  "adopted",
  "dropped",
  "expired",
  "aborted",
  "no_change",
]);

const STATUS_LABEL: Record<string, string> = {
  draft: "草案",
  adopted: "已采用",
  dropped: "已放弃",
  expired: "已过期",
  aborted: "已中止",
  no_change: "无变化",
};

function statusTone(status: string): BadgeTone {
  switch (status) {
    case "draft":
      return "warn";
    case "adopted":
      return "ok";
    case "aborted":
      return "danger";
    default:
      return "neutral";
  }
}

/** draft 评审窗口剩余毫秒（created_at + TTL − now；advisory，服务端为准）。 */
function ttlRemainingMs(createdAt: string | null): number | null {
  if (!createdAt) return null;
  const created = new Date(createdAt).getTime();
  if (isNaN(created)) return null;
  return created + EVOLVE_DRAFT_TTL_HOURS * 3600_000 - Date.now();
}

function fmtTtl(ms: number): string {
  if (ms <= 0) return "已超评审窗口";
  const h = Math.floor(ms / 3600_000);
  const m = Math.floor((ms % 3600_000) / 60_000);
  return h > 0 ? `剩约 ${h}h${m}m` : `剩约 ${m}m`;
}

/* ------------------------------------------------------------- 行内 diff */

type DiffRow = { type: "same" | "add" | "del"; text: string };

/** 最小 LCS 行 diff：输出统一 +/− 行流（墨阶呈现，禁彩色 diff）。 */
function lineDiff(oldStr: string, newStr: string): DiffRow[] {
  const A = oldStr.split("\n");
  const B = newStr.split("\n");
  const n = A.length;
  const m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      rows.push({ type: "same", text: A[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: "del", text: A[i++] });
    } else {
      rows.push({ type: "add", text: B[j++] });
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
      <p className="mb-1.5 text-12 text-ink-3">
        <Mono>+{adds} / −{dels}</Mono>
      </p>
      <div className="overflow-x-auto rounded-2 border border-line">
        <pre className="min-w-max px-3 py-2 font-mono text-12 leading-5">
          {rows.map((r, k) => (
            <div key={k} className="flex">
              <span className="mr-2 w-3 shrink-0 select-none text-center text-ink-3">
                {r.type === "add" ? "+" : r.type === "del" ? "−" : " "}
              </span>
              <span
                className={cn(
                  "whitespace-pre-wrap break-words",
                  r.type === "add" && "text-ink",
                  r.type === "del" && "text-ink-3 line-through",
                  r.type === "same" && "text-ink-3",
                )}
              >
                {r.text || " "}
              </span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- 视图 */

export default function EvolveView() {
  const currentUser = useApp((s) => s.currentUser);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const readOnly = currentSnapshot != null;

  const [skill, setSkill] = useState<api.SkillInfo | null>(null);
  const [skillState, setSkillState] = useState<"loading" | "ready" | "error">("loading");
  const [skillError, setSkillError] = useState<string | null>(null);

  const [tasks, setTasks] = useState<api.EvolveTaskSummary[]>([]);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = useState<string | null>(null);

  const [triggering, setTriggering] = useState(false);
  const [notice, setNotice] = useState<{ tone: "warn" | "danger" | "notice"; text: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  /* skill 面 */
  useEffect(() => {
    if (!currentUser) return;
    let live = true;
    setSkillState("loading");
    api
      .getSkillInfo(currentUser)
      .then((s) => {
        if (!live) return;
        setSkill(s);
        setSkillState("ready");
      })
      .catch((e: Error) => {
        if (!live) return;
        setSkillError(e.message);
        setSkillState("error");
      });
    return () => {
      live = false;
    };
  }, [currentUser, reloadKey]);

  /* 任务账 */
  useEffect(() => {
    if (!currentUser) return;
    let live = true;
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

  /* 轮询：有 draft / 进行中任务时每 5s 刷新；卸载清理。 */
  const needsPoll = tasks.some((t) => t.status === "draft" || !TERMINAL.has(t.status));
  useEffect(() => {
    if (!currentUser || !needsPoll) return;
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [currentUser, needsPoll, refresh]);

  async function onTrigger() {
    if (!currentUser) return;
    setTriggering(true);
    setNotice(null);
    try {
      await api.triggerEvolve(currentUser);
      setNotice({ tone: "notice", text: "已入队演化任务——worker 跑完后草案会出现在下方任务账。" });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // single-flight：已有 draft 待审或任务进行中。
        setNotice({ tone: "warn", text: e.message });
      } else {
        setNotice({ tone: "danger", text: `触发失败：${(e as Error).message}` });
      }
    } finally {
      setTriggering(false);
      refresh();
    }
  }

  const selectedTaskId =
    selection?.kind === "evolve-task" &&
    tasks.some((t) => t.task_id === selection.id)
      ? selection.id
      : null;

  if (!currentUser) {
    return (
      <>
        <PageHeader title="演化 Evolve" description="schema 重组提案的评审台与当前生效 skill。" />
        <EmptyState
          icon={UserRoundX}
          title="未选择用户"
          description="在右上角选择一个 user_id，以查看它的演化任务与量身定制 skill。"
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="演化 Evolve"
        description="skill 版本与扩展 pack · 演化任务账 · draft 评审（采用 / 放弃）。"
        actions={
          <Button
            variant="primary"
            size="sm"
            loading={triggering}
            disabled={readOnly}
            title={readOnly ? "历史快照为只读" : undefined}
            onClick={onTrigger}
          >
            触发演化
          </Button>
        }
      />

      {notice && (
        <Callout tone={notice.tone} className="mb-6" onDismiss={() => setNotice(null)}>
          {notice.text}
        </Callout>
      )}

      {/* skill 面 */}
      <section>
        <SectionRule no={1} title="当前生效 skill" />
        {skillState === "loading" && <SkeletonText lines={3} className="mt-4" />}
        {skillState === "error" && (
          <ErrorState
            className="mt-4"
            title="skill 加载失败"
            error={skillError ?? "未知错误"}
            onRetry={refresh}
          />
        )}
        {skillState === "ready" && skill && (
          <div className="mt-3 flex flex-col gap-4">
            <DefinitionList
              items={[
                { term: "version", definition: <Mono>{skill.version}</Mono> },
                { term: "base_version", definition: <Mono>{skill.base_version}</Mono> },
                { term: "content_hash", definition: <Mono className="break-all">{skill.content_hash}</Mono> },
              ]}
            />
            <div>
              <p className="text-12 text-ink-3">path_templates · {skill.path_templates.length}</p>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {skill.path_templates.map((t, i) => (
                  <li key={i} className="rounded-1 border border-line-2 bg-surface px-1.5 py-0.5">
                    <Mono className="text-12 text-ink-2">{t}</Mono>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-12 text-ink-3">packs · {skill.packs.length}</p>
              {skill.packs.length === 0 ? (
                <p className="mt-1 text-12 text-ink-3">尚无扩展 pack。</p>
              ) : (
                <ul className="mt-1 flex flex-col">
                  {skill.packs.map((p, i) => (
                    <li key={p.pack_id ?? i} className="flex flex-col gap-1 border-b border-line py-2 last:border-b-0">
                      <span className="flex items-baseline gap-2">
                        <Mono className="text-12 text-ink">{p.pack_id ?? "—"}</Mono>
                        <Badge tone="neutral">{p.origin ?? "—"}</Badge>
                      </span>
                      {p.extra_path_templates.length > 0 && (
                        <span className="flex flex-wrap gap-1.5">
                          {p.extra_path_templates.map((t, k) => (
                            <Mono key={k} className="text-12 text-ink-3">{t}</Mono>
                          ))}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </section>

      {/* 任务账 */}
      <section className="mt-8">
        <SectionRule no={2} title={`任务账 · ${tasks.length}`} />
        {listState === "loading" && <SkeletonText lines={4} className="mt-4" />}
        {listState === "error" && (
          <ErrorState
            className="mt-4"
            title="任务列表加载失败"
            error={listError ?? "未知错误"}
            onRetry={refresh}
          />
        )}
        {listState === "ready" && tasks.length === 0 && (
          <EmptyState
            className="mt-4"
            icon={Sprout}
            title="暂无演化任务"
            description="点右上角「触发演化」发起一次 schema 重组提案；草案会留在这里等待评审。"
          />
        )}
        {listState === "ready" && tasks.length > 0 && (
          <div className="mt-4 flex flex-col gap-6 lg:flex-row lg:items-start">
            <ol className="w-full shrink-0 lg:w-72">
              {tasks.map((t) => {
                const active = t.task_id === selectedTaskId;
                const ttl = t.status === "draft" ? ttlRemainingMs(t.created_at) : null;
                return (
                  <li key={t.task_id}>
                    <button
                      type="button"
                      onClick={() => select({ kind: "evolve-task", id: t.task_id })}
                      aria-current={active || undefined}
                      className={cn(
                        "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left transition-colors duration-120",
                        active ? "border-accent bg-accent-soft" : "border-transparent hover:bg-hover",
                      )}
                    >
                      <span className="flex items-baseline gap-2">
                        <Mono className="min-w-0 flex-1 truncate text-12 text-ink">{t.task_id}</Mono>
                        <Badge tone={statusTone(t.status)}>{STATUS_LABEL[t.status] ?? t.status}</Badge>
                      </span>
                      <span className="text-12 text-ink-3">
                        创建 {fmtTime(t.created_at)}
                        {t.decided_at && ` · 决定 ${fmtTime(t.decided_at)}`}
                        {ttl != null && ` · ${fmtTtl(ttl)}`}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
            <div className="min-w-0 flex-1 lg:border-l lg:border-line lg:pl-6">
              {selectedTaskId ? (
                <TaskDetail
                  key={selectedTaskId}
                  userId={currentUser}
                  taskId={selectedTaskId}
                  readOnly={readOnly}
                  onDecided={refresh}
                />
              ) : (
                <p className="text-13 text-ink-3">在左侧任务账选中一条查看详情。</p>
              )}
            </div>
          </div>
        )}
      </section>
    </>
  );
}

/* -------------------------------------------------------------- 任务详情 */

function TaskDetail({
  userId,
  taskId,
  readOnly,
  onDecided,
}: {
  userId: string;
  taskId: string;
  readOnly: boolean;
  onDecided: () => void;
}) {
  const [detail, setDetail] = useState<api.EvolveTaskDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [showProposal, setShowProposal] = useState(false);
  const [openFiles, setOpenFiles] = useState<Set<string>>(new Set());
  const [confirmDrop, setConfirmDrop] = useState(false);
  const [acting, setActing] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
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
  }, [userId, taskId, reload]);

  async function onAdopt() {
    setActing(true);
    setActionErr(null);
    try {
      await api.adoptEvolveTask(userId, taskId);
      onDecided();
      setReload((k) => k + 1);
    } catch (e) {
      setActionErr(`采用失败：${(e as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  async function onDrop() {
    setActing(true);
    setActionErr(null);
    try {
      await api.dropEvolveTask(userId, taskId);
      setConfirmDrop(false);
      onDecided();
      setReload((k) => k + 1);
    } catch (e) {
      setActionErr(`放弃失败：${(e as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  if (state === "loading") return <SkeletonText lines={5} />;
  if (state === "error" || !detail) {
    return (
      <ErrorState
        title="任务加载失败"
        error={error ?? "未知错误"}
        onRetry={() => setReload((k) => k + 1)}
      />
    );
  }

  const isDraft = detail.status === "draft";
  const s = detail.summary;
  const ttl = isDraft ? ttlRemainingMs(detail.created_at) : null;
  const adoptedEntries = s ? Object.entries(s.adopted_by_document ?? {}) : [];

  return (
    <div className="flex flex-col gap-6">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <Mono className="text-14 text-ink">{detail.task_id}</Mono>
          <Badge tone={statusTone(detail.status)}>{STATUS_LABEL[detail.status] ?? detail.status}</Badge>
          {ttl != null && (
            <span className="text-12 text-ink-3" title={`评审窗口 ${EVOLVE_DRAFT_TTL_HOURS}h，客户端按 created_at 推算（advisory），实际过期以服务端为准`}>
              {fmtTtl(ttl)}
            </span>
          )}
        </div>
        <p className="mt-1 text-12 text-ink-3">
          创建 {fmtTime(detail.created_at)}
          {detail.decided_at && ` · 决定 ${fmtTime(detail.decided_at)}`}
          {detail.base_ref && (
            <>
              {" · base "}
              <Mono>{detail.base_ref.slice(0, 10)}</Mono>
            </>
          )}
          {detail.branch && (
            <>
              {" · branch "}
              <Mono>{detail.branch}</Mono>
            </>
          )}
        </p>
        {detail.detail && <p className="mt-2 text-13 text-ink-2">{detail.detail}</p>}

        {isDraft && (
          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              loading={acting}
              disabled={readOnly}
              title={readOnly ? "历史快照为只读" : undefined}
              onClick={onAdopt}
            >
              采用
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={acting || readOnly}
              title={readOnly ? "历史快照为只读" : undefined}
              onClick={() => setConfirmDrop(true)}
            >
              放弃
            </Button>
          </div>
        )}
        {actionErr && (
          <Callout tone="danger" className="mt-3">
            {actionErr}
          </Callout>
        )}
      </header>

      {/* 机械摘要账 */}
      <section>
        <SectionRule no={1} title="机械摘要" />
        {s ? (
          <div className="mt-3 grid grid-cols-3 gap-3">
            <StatCell label="新建文档" value={s.new_documents} />
            <StatCell label="搬移 claim" value={s.moved_claims} />
            <StatCell label="合并 claim" value={s.merged_claims} />
          </div>
        ) : (
          <p className="mt-3 text-13 text-ink-3">本任务无机械摘要。</p>
        )}
        {adoptedEntries.length > 0 && (
          <ul className="mt-3 flex flex-col">
            {adoptedEntries.map(([path, count]) => (
              <li key={path} className="flex items-baseline gap-2 border-b border-line py-1.5 last:border-b-0">
                <Mono className="min-w-0 flex-1 truncate text-12 text-ink-2">{path}</Mono>
                <Mono className="shrink-0 text-12 text-ink-3">收编 {count} 条</Mono>
              </li>
            ))}
          </ul>
        )}
        {detail.rationale && (
          <Callout tone="notice" title="rationale" className="mt-3">
            {detail.rationale}
          </Callout>
        )}
        {detail.proposal && (
          <div className="mt-3">
            <Button size="sm" variant="ghost" onClick={() => setShowProposal((v) => !v)}>
              {showProposal ? "收起 proposal" : "展开 proposal"}
            </Button>
            {showProposal && (
              <pre className="mt-2 overflow-x-auto rounded-2 border border-line bg-surface p-3 font-mono text-12 leading-5 text-ink-2">
                {JSON.stringify(detail.proposal, null, 2)}
              </pre>
            )}
          </div>
        )}
      </section>

      {/* dropped anchors */}
      {detail.dropped.length > 0 && (
        <section>
          <SectionRule no={2} title={`合并 / 丢弃的 claim · ${detail.dropped.length}`} />
          <ul className="mt-3 flex flex-col">
            {detail.dropped.map((d) => (
              <li key={d.anchor} className="border-b border-line py-2 last:border-b-0">
                <span className="flex flex-wrap items-baseline gap-2">
                  <Mono className="text-12 text-accent">c:{d.anchor}</Mono>
                  <Mono className="min-w-0 truncate text-12 text-ink-3">{d.old_path}</Mono>
                </span>
                <p className="mt-1 text-13 text-ink-2">{d.text}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* changed files */}
      <section>
        <SectionRule no={3} title={`变更文件 · ${detail.changed_files.length}`} />
        {detail.changed_files.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">
            {isDraft
              ? "本草案无文件级差异，或分支暂不可读。"
              : "任务已决定、分支已回收——仅保留上方机械摘要。"}
          </p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {detail.changed_files.map((f) => {
              const open = openFiles.has(f.path);
              return (
                <li key={f.path} className="rounded-2 border border-line">
                  <button
                    type="button"
                    onClick={() =>
                      setOpenFiles((prev) => {
                        const next = new Set(prev);
                        if (next.has(f.path)) next.delete(f.path);
                        else next.add(f.path);
                        return next;
                      })
                    }
                    className="flex w-full items-baseline gap-2 px-3 py-2 text-left"
                  >
                    <Mono className="min-w-0 flex-1 truncate text-12 text-ink">{f.path}</Mono>
                    <span className="shrink-0 text-12 text-ink-3">
                      {f.old_body === "" ? "新建" : f.new_body === "" ? "删除" : open ? "收起" : "展开"}
                    </span>
                  </button>
                  {open && (
                    <div className="border-t border-line px-2 py-2">
                      <DiffBlock oldBody={f.old_body} newBody={f.new_body} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* 放弃：二次确认 */}
      <Dialog
        open={confirmDrop}
        onOpenChange={setConfirmDrop}
        title="放弃这份草案？"
        description="将删除该演化分支并记为已放弃，操作不可撤销。"
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDrop(false)} disabled={acting}>
              取消
            </Button>
            <Button size="sm" variant="danger" loading={acting} onClick={onDrop}>
              确认放弃
            </Button>
          </>
        }
      >
        <p className="text-13 text-ink-2">
          任务 <Mono>{detail.task_id}</Mono> 的草案与其分支将被丢弃。
        </p>
      </Dialog>
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2 border border-line bg-surface p-3 text-center">
      <div className="text-20 text-ink">
        <Mono>{value}</Mono>
      </div>
      <div className="mt-0.5 text-12 text-ink-3">{label}</div>
    </div>
  );
}

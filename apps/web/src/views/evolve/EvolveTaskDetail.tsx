import { useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";
import { EVOLVE_DRAFT_TTL_HOURS } from "@/lib/api";
import { fmtTime, shortSha } from "@/lib/format";
import {
  buildPackDrafts,
  changedFileKind,
  diffStat,
  evolveStatusLabel,
  evolveStatusTone,
  fmtTtlRemaining,
  lineDiff,
  parseRationale,
  ttlRemainingMs,
} from "@/lib/evolve";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Dialog } from "@/ui/Dialog";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { Stamp } from "@/ui/Stamp";
import { cn } from "@/ui/cn";

/* ------------------------------------------------------------------ 行内 diff */

const KIND_LABEL: Record<ReturnType<typeof changedFileKind>, string> = {
  created: "新建",
  deleted: "删除",
  modified: "改写",
};

function DiffBlock({ oldBody, newBody }: { oldBody: string; newBody: string }) {
  const rows = useMemo(() => lineDiff(oldBody, newBody), [oldBody, newBody]);
  const { adds, dels } = diffStat(rows);
  return (
    <div>
      <p className="mb-1.5 text-12 text-ink-3">
        <Mono>
          +{adds} / −{dels}
        </Mono>
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

/* ------------------------------------------------------------------ 任务详情 */

export function EvolveTaskDetail({
  userId,
  taskId,
  ordinal,
  readOnly,
  onDecided,
}: {
  userId: string;
  taskId: string;
  /** 时间线里的次序号，标题与快照轴共用同一个编号。 */
  ordinal: number | null;
  readOnly: boolean;
  onDecided: () => void;
}) {
  const [detail, setDetail] = useState<api.EvolveTaskDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
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

  if (state === "loading") return <SkeletonText lines={6} />;
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
  const summary = detail.summary;
  const ttl = isDraft ? ttlRemainingMs(detail.created_at, EVOLVE_DRAFT_TTL_HOURS) : null;
  const packs = buildPackDrafts(detail.proposal);
  const rationale = parseRationale(detail.rationale, packs.length);
  const adoptedEntries = summary ? Object.entries(summary.adopted_by_document ?? {}) : [];
  const droppedCount = detail.dropped.length;

  return (
    <div className="flex flex-col gap-8">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-serif text-24 text-ink text-balance">
            {ordinal != null ? `第 ${ordinal} 次演化` : "演化任务"}
          </h2>
          <Badge tone={evolveStatusTone(detail.status)}>
            {evolveStatusLabel(detail.status)}
          </Badge>
          {ttl != null && (
            <span
              className="text-12 text-ink-3"
              title={`评审窗口 ${EVOLVE_DRAFT_TTL_HOURS}h，客户端按 created_at 推算（advisory），实际过期以服务端为准`}
            >
              {fmtTtlRemaining(ttl)}
            </span>
          )}
        </div>

        <p className="mt-1 text-12 text-ink-3">
          <Mono>{detail.task_id}</Mono> · 创建 {fmtTime(detail.created_at)}
          {detail.decided_at && ` · 决定 ${fmtTime(detail.decided_at)}`}
        </p>
        {detail.detail && <p className="mt-2 text-13 text-ink-2">{detail.detail}</p>}

        {packs.length > 0 && (
          <p className="mt-3 flex flex-wrap items-baseline gap-1.5 text-13 text-ink-2">
            <span>本次提议新增归档 family：</span>
            {packs.map((pack) => (
              <Mono
                key={pack.packId ?? pack.family}
                className="rounded-1 border border-accent-line bg-accent-soft px-1.5 py-px text-12 text-accent"
              >
                +{pack.family}
              </Mono>
            ))}
          </p>
        )}

        {isDraft && (
          <div className="mt-4 flex items-center gap-2 border-t border-line pt-3">
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
            <span className="text-12 text-ink-3">
              采用会把这次重组并回主线并重建 L3；放弃会删掉演化分支。
            </span>
          </div>
        )}
        {actionErr && (
          <Callout tone="danger" className="mt-3">
            {actionErr}
          </Callout>
        )}
      </header>

      {/* 提案理由 + 证据行 */}
      <section>
        <SectionRule no={1} title="提案理由" />
        {rationale.lead === "" && rationale.evidence.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">本任务没有留下提案自述。</p>
        ) : (
          <>
            {rationale.lead && (
              <div className="prose mt-3 max-w-measure text-14">
                {rationale.lead.split("\n").map((line, i) => (
                  <p key={i}>{line}</p>
                ))}
              </div>
            )}
            {rationale.evidence.length > 0 && (
              <ol className="mt-3 flex flex-col border-y border-line">
                {rationale.evidence.map((line, i) => (
                  <li
                    key={i}
                    className="flex gap-3 border-b border-line px-1 py-2 last:border-b-0"
                  >
                    <Mono className="shrink-0 text-12 text-accent">[{i + 1}]</Mono>
                    <span className="min-w-0 font-serif text-14 leading-[1.75] text-ink-2">
                      {line}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </section>

      {/* pack 草案全文 */}
      <section>
        <SectionRule no={2} title={`pack 草案 · ${packs.length}`} />
        {packs.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">
            本任务没有 pack 草案（无变化提案，或提案未通过模板校验）。
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-5">
            {packs.map((pack) => (
              <article
                key={pack.packId ?? pack.family}
                className="border-l-2 border-accent-line pl-3"
              >
                <header className="flex flex-wrap items-baseline gap-2">
                  <h3 className="font-serif text-16 font-medium text-ink">{pack.family}</h3>
                  <Mono className="text-12 text-ink-3">{pack.packId ?? "—"}</Mono>
                  {pack.origin && <Badge tone="neutral">{pack.origin}</Badge>}
                </header>

                <p className="mt-2 text-12 text-ink-3">instructions</p>
                {pack.instructions ? (
                  <p className="mt-1 max-w-measure font-serif text-14 leading-[1.75] whitespace-pre-wrap text-ink-2">
                    {pack.instructions}
                  </p>
                ) : (
                  <p className="mt-1 text-13 text-ink-3">未附 instructions。</p>
                )}

                <p className="mt-3 text-12 text-ink-3">
                  path_templates · {pack.pathTemplates.length}
                </p>
                {pack.pathTemplates.length > 0 ? (
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {pack.pathTemplates.map((template) => (
                      <li
                        key={template}
                        className="rounded-1 border border-line-2 bg-surface px-1.5 py-0.5"
                      >
                        <Mono className="text-12 text-ink-2">{template}</Mono>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-13 text-ink-3">未附路径模板。</p>
                )}

                {pack.contractRules.length > 0 && (
                  <>
                    <p className="mt-3 text-12 text-ink-3">
                      extra_contract_rules · {pack.contractRules.length}
                    </p>
                    <ul className="mt-1 flex flex-col gap-1">
                      {pack.contractRules.map((rule, i) => (
                        <li key={i} className="text-13 text-ink-2">
                          {rule}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      {/* 消失的锚——人审的重点 */}
      <section>
        <SectionRule
          no={3}
          title={`消失的锚 · ${droppedCount}`}
          actions={
            droppedCount > 0 ? (
              <Stamp tone="warn">等人裁决</Stamp>
            ) : (
              <Stamp tone="ok">锚全部保留</Stamp>
            )
          }
        />
        {droppedCount === 0 ? (
          <p className="mt-3 text-13 text-ink-3">
            这次重组没有让任何 claim 锚消失——每一条都带原锚搬到了新 family。
          </p>
        ) : (
          <>
            <Callout tone="warn" title="这是本次评审的重点" className="mt-3">
              下面 {droppedCount} 条 claim 的锚在新库里已找不到（被合并或删除）。锚消失意味着
              L3 / 事件 / git blame 上的引用链在这里断开，采用前请逐条确认这是你要的结果。
            </Callout>
            <ul className="mt-3 flex flex-col border-y border-line">
              {detail.dropped.map((d) => (
                <li
                  key={d.anchor}
                  className="border-b border-line py-3 last:border-b-0"
                >
                  <span className="flex flex-wrap items-baseline gap-2">
                    <Mono className="text-12 text-danger">c:{d.anchor}</Mono>
                    <Mono className="min-w-0 truncate text-12 text-ink-3" title={d.old_path}>
                      {d.old_path}
                    </Mono>
                  </span>
                  <p className="mt-1 max-w-measure font-serif text-14 leading-[1.75] text-ink-2">
                    {d.text}
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {/* 机械摘要 */}
      <section>
        <SectionRule no={4} title="机械摘要" />
        {summary ? (
          <div className="mt-3 grid grid-cols-3 gap-3">
            <StatCell label="新建文档" value={summary.new_documents} />
            <StatCell label="搬移 claim" value={summary.moved_claims} />
            <StatCell label="合并 claim" value={summary.merged_claims} />
          </div>
        ) : (
          <p className="mt-3 text-13 text-ink-3">本任务无机械摘要。</p>
        )}
        {adoptedEntries.length > 0 && (
          <ul className="mt-3 flex flex-col border-y border-line">
            {adoptedEntries.map(([path, count]) => (
              <li
                key={path}
                className="flex items-baseline gap-2 border-b border-line py-1.5 last:border-b-0"
              >
                <Mono className="min-w-0 flex-1 truncate text-12 text-ink-2" title={path}>
                  {path}
                </Mono>
                <Mono className="shrink-0 text-12 text-ink-3">收编 {count} 条</Mono>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* changed files */}
      <section>
        <SectionRule no={5} title={`变更文件 · ${detail.changed_files.length}`} />
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
              const kind = changedFileKind(f.old_body, f.new_body);
              return (
                <li key={f.path} className="rounded-2 border border-line">
                  <button
                    type="button"
                    aria-expanded={open}
                    onClick={() =>
                      setOpenFiles((prev) => {
                        const next = new Set(prev);
                        if (next.has(f.path)) next.delete(f.path);
                        else next.add(f.path);
                        return next;
                      })
                    }
                    className="flex w-full items-baseline gap-2 px-3 py-2 text-left transition-colors duration-120 ease-out hover:bg-hover"
                  >
                    <Mono className="min-w-0 flex-1 truncate text-12 text-ink" title={f.path}>
                      {f.path}
                    </Mono>
                    <Badge tone={kind === "deleted" ? "warn" : "neutral"}>
                      {KIND_LABEL[kind]}
                    </Badge>
                    <span className="shrink-0 text-12 text-ink-3">
                      {open ? "收起" : "展开"}
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

      {/* 技术记录 */}
      <details className="border-t border-line pt-3">
        <summary className="cursor-pointer text-13 text-ink-2 marker:text-ink-3">
          技术记录
        </summary>
        <DefinitionList
          className="mt-2"
          items={[
            { term: "task_id", definition: <Mono className="break-all">{detail.task_id}</Mono> },
            {
              term: "base_ref",
              definition: detail.base_ref ? (
                <Mono title={detail.base_ref}>{shortSha(detail.base_ref, 10)}</Mono>
              ) : (
                "—"
              ),
            },
            {
              term: "branch",
              definition: detail.branch ? (
                <Mono className="break-all">{detail.branch}</Mono>
              ) : (
                "—"
              ),
            },
          ]}
        />
        {detail.proposal && (
          <pre className="mt-2 overflow-x-auto rounded-2 border border-line bg-surface p-3 font-mono text-12 leading-5 text-ink-2">
            {JSON.stringify(detail.proposal, null, 2)}
          </pre>
        )}
      </details>

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

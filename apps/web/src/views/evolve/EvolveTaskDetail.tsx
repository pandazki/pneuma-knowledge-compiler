import { useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";
import { EVOLVE_DRAFT_TTL_HOURS } from "@/lib/api";
import { fmtTime, shortSha } from "@/lib/format";
import {
  buildPackDrafts,
  changedFileKind,
  diffStat,
  evolveStatusLabelKey,
  evolveStatusTone,
  lineDiff,
  parseRationale,
  ttlRemainingMessage,
  ttlRemainingMs,
} from "@/lib/evolve";
import type { MessageKey } from "@/lib/i18n";
import { useT, useTOr } from "@/lib/useT";
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

/* ------------------------------------------------------------------ inline diff */

const KIND_LABEL_KEY: Record<ReturnType<typeof changedFileKind>, MessageKey> = {
  created: "evolve.file.created",
  deleted: "evolve.file.deleted",
  modified: "evolve.file.modified",
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

/* ------------------------------------------------------------------ task detail */

export function EvolveTaskDetail({
  userId,
  taskId,
  ordinal,
  readOnly,
  onDecided,
}: {
  userId: string;
  taskId: string;
  /** The timeline's index for this task; the heading and the schema axis share the number. */
  ordinal: number | null;
  readOnly: boolean;
  onDecided: () => void;
}) {
  const t = useT();
  const tOr = useTOr();
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
      setActionErr(t("evolve.action.adoptFailed", { detail: (e as Error).message }));
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
      setActionErr(t("evolve.action.dropFailed", { detail: (e as Error).message }));
    } finally {
      setActing(false);
    }
  }

  if (state === "loading") return <SkeletonText lines={6} />;
  if (state === "error" || !detail) {
    return (
      <ErrorState
        title={t("evolve.detail.loadFailed")}
        error={error ?? t("common.unknownError")}
        onRetry={() => setReload((k) => k + 1)}
      />
    );
  }

  const isDraft = detail.status === "draft";
  const summary = detail.summary;
  const ttl = isDraft ? ttlRemainingMs(detail.created_at, EVOLVE_DRAFT_TTL_HOURS) : null;
  const ttlMessage = ttl != null ? ttlRemainingMessage(ttl) : null;
  const packs = buildPackDrafts(detail.proposal);
  const rationale = parseRationale(detail.rationale, packs.length);
  const adoptedEntries = summary ? Object.entries(summary.adopted_by_document ?? {}) : [];
  const droppedCount = detail.dropped.length;

  return (
    <div className="flex flex-col gap-8">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-serif text-24 text-ink text-balance">
            {ordinal != null
              ? t("evolve.evolutionOrdinal", { n: ordinal })
              : t("evolve.detail.title")}
          </h2>
          <Badge tone={evolveStatusTone(detail.status)}>
            {tOr(evolveStatusLabelKey(detail.status), detail.status)}
          </Badge>
          {ttlMessage && (
            <span
              className="text-12 text-ink-3"
              title={t("evolve.ttl.tooltip", { hours: EVOLVE_DRAFT_TTL_HOURS })}
            >
              {t(ttlMessage.key, ttlMessage.params)}
            </span>
          )}
        </div>

        <p className="mt-1 text-12 text-ink-3">
          <Mono>{detail.task_id}</Mono> ·{" "}
          {t("evolve.detail.created", { at: fmtTime(detail.created_at) })}
          {detail.decided_at &&
            ` · ${t("evolve.decided", { at: fmtTime(detail.decided_at) })}`}
        </p>
        {detail.detail && <p className="mt-2 text-13 text-ink-2">{detail.detail}</p>}

        {packs.length > 0 && (
          <p className="mt-3 flex flex-wrap items-baseline gap-1.5 text-13 text-ink-2">
            <span>{t("evolve.detail.proposedFamilies")}</span>
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
              title={readOnly ? t("evolve.readOnlyHint") : undefined}
              onClick={onAdopt}
            >
              {t("evolve.action.adopt")}
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={acting || readOnly}
              title={readOnly ? t("evolve.readOnlyHint") : undefined}
              onClick={() => setConfirmDrop(true)}
            >
              {t("evolve.action.drop")}
            </Button>
            <span className="text-12 text-ink-3">{t("evolve.action.hint")}</span>
          </div>
        )}
        {actionErr && (
          <Callout tone="danger" className="mt-3">
            {actionErr}
          </Callout>
        )}
      </header>

      {/* The proposal's reasoning + its evidence lines */}
      <section>
        <SectionRule no={1} title={t("evolve.section.rationale")} />
        {rationale.lead === "" && rationale.evidence.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">{t("evolve.rationale.empty")}</p>
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

      {/* The pack drafts, in full */}
      <section>
        <SectionRule no={2} title={t("evolve.section.packs", { count: packs.length })} />
        {packs.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">{t("evolve.packs.empty")}</p>
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
                  <p className="mt-1 text-13 text-ink-3">
                    {t("evolve.packs.noInstructions")}
                  </p>
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
                  <p className="mt-1 text-13 text-ink-3">{t("evolve.packs.noTemplates")}</p>
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

      {/* The anchors that disappear — what a human review turns on */}
      <section>
        <SectionRule
          no={3}
          title={t("evolve.section.dropped", { count: droppedCount })}
          actions={
            droppedCount > 0 ? (
              <Stamp tone="warn">{t("evolve.dropped.awaiting")}</Stamp>
            ) : (
              <Stamp tone="ok">{t("evolve.dropped.allKept")}</Stamp>
            )
          }
        />
        {droppedCount === 0 ? (
          <p className="mt-3 text-13 text-ink-3">{t("evolve.dropped.empty")}</p>
        ) : (
          <>
            <Callout
              tone="warn"
              title={t("evolve.dropped.calloutTitle")}
              className="mt-3"
            >
              {t("evolve.dropped.calloutBody", { count: droppedCount })}
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

      {/* The mechanical summary */}
      <section>
        <SectionRule no={4} title={t("evolve.section.summary")} />
        {summary ? (
          <div className="mt-3 grid grid-cols-3 gap-3">
            <StatCell label={t("evolve.stat.newDocuments")} value={summary.new_documents} />
            <StatCell label={t("evolve.stat.movedClaims")} value={summary.moved_claims} />
            <StatCell label={t("evolve.stat.mergedClaims")} value={summary.merged_claims} />
          </div>
        ) : (
          <p className="mt-3 text-13 text-ink-3">{t("evolve.summary.empty")}</p>
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
                <Mono className="shrink-0 text-12 text-ink-3">
                  {t("evolve.summary.adoptedCount", { count })}
                </Mono>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* changed files */}
      <section>
        <SectionRule
          no={5}
          title={t("evolve.section.changedFiles", { count: detail.changed_files.length })}
        />
        {detail.changed_files.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">
            {isDraft ? t("evolve.files.emptyDraft") : t("evolve.files.emptyDecided")}
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
                      {t(KIND_LABEL_KEY[kind])}
                    </Badge>
                    <span className="shrink-0 text-12 text-ink-3">
                      {open ? t("evolve.files.collapse") : t("evolve.files.expand")}
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

      {/* The technical record */}
      <details className="border-t border-line pt-3">
        <summary className="cursor-pointer text-13 text-ink-2 marker:text-ink-3">
          {t("evolve.technical")}
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

      {/* Dropping: a second confirmation */}
      <Dialog
        open={confirmDrop}
        onOpenChange={setConfirmDrop}
        title={t("evolve.drop.confirmTitle")}
        description={t("evolve.drop.confirmDescription")}
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDrop(false)} disabled={acting}>
              {t("evolve.action.cancel")}
            </Button>
            <Button size="sm" variant="danger" loading={acting} onClick={onDrop}>
              {t("evolve.drop.confirmAction")}
            </Button>
          </>
        }
      >
        <p className="text-13 text-ink-2">
          {t("evolve.drop.confirmBody.before")} <Mono>{detail.task_id}</Mono>{" "}
          {t("evolve.drop.confirmBody.after")}
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

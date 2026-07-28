import { useMemo } from "react";
import { GitCommitHorizontal, Inbox } from "lucide-react";
import { useApp } from "@/lib/store";
import type { JobRecord, PatchRecord, Snapshot } from "@/lib/types";
import { claimKey, patchChanges, patchNum, type Model } from "@/lib/model";
import { escalationText } from "@/lib/claim";
import { fmtTime, fmtTokens, shortSha } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Badge, type BadgeTone } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { cn } from "@/ui/cn";

type TimelineItem =
  | { kind: "patch"; ts: string; ref: string; patch: PatchRecord }
  | { kind: "job"; ts: string; ref: string; job: JobRecord }
  | { kind: "snapshot"; ts: string; ref: string; snapshot: Snapshot };

const KIND_BADGE: Record<TimelineItem["kind"], { label: string; tone: BadgeTone }> = {
  patch: { label: "patch", tone: "accent" },
  job: { label: "job", tone: "neutral" },
  snapshot: { label: "snapshot", tone: "neutral" },
};

export default function HistoryView() {
  const model = useApp((s) => s.model);
  const dataset = useApp((s) => s.dataset);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const setView = useApp((s) => s.setView);

  const timeline = dataset?.timeline;

  // 统一账页：patches（主体）+ jobs + snapshots，时间倒序。
  const items = useMemo<TimelineItem[]>(() => {
    if (!timeline) return [];
    const list: TimelineItem[] = [
      ...timeline.patches.map((p) => ({
        kind: "patch" as const,
        ts: p.ts ?? "",
        ref: p.patch_id,
        patch: p,
      })),
      ...timeline.jobs.map((j) => ({
        kind: "job" as const,
        ts: j.ts ?? "",
        ref: j.job_id,
        job: j,
      })),
      ...timeline.snapshots.map((s) => ({
        kind: "snapshot" as const,
        ts: s.captured_at ?? "",
        ref: s.source_id,
        snapshot: s,
      })),
    ];
    return list.sort((a, b) => {
      const t = b.ts.localeCompare(a.ts);
      if (t !== 0) return t;
      if (a.kind === "patch" && b.kind === "patch")
        return patchNum(b.patch.patch_id) - patchNum(a.patch.patch_id);
      return 0;
    });
  }, [timeline]);

  if (!dataset || !model || !timeline) {
    return (
      <>
        <PageHeader title="版本 History" description="patch / job / snapshot 的统一时间线账页。" />
        <EmptyState
          icon={Inbox}
          title="还没有版本"
          description="这个知识库尚未编译——先去「导入 Ingest」添加原料并编译，随后每次编译都会在这里留下一版。"
          action={<Button size="sm" onClick={() => setView("ingest")}>去导入</Button>}
        />
      </>
    );
  }

  const selected =
    selection?.kind === "patch" ? items.find((i) => i.kind === "patch" && i.ref === selection.id) ?? null
    : selection?.kind === "job" ? items.find((i) => i.kind === "job" && i.ref === selection.id) ?? null
    : selection?.kind === "snapshot" ? items.find((i) => i.kind === "snapshot" && i.ref === selection.id) ?? null
    : null;

  return (
    <>
      <PageHeader
        title="版本 History"
        description={`${timeline.patches.length} patches · ${timeline.jobs.length} jobs · ${timeline.snapshots.length} snapshots，按时间倒序。`}
      />
      {items.length === 0 ? (
        <EmptyState
          icon={GitCommitHorizontal}
          title="时间线为空"
          description="timeline 尚无 patch / job / snapshot 记录。"
        />
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          {/* 左：时间线账页 */}
          <ol className="w-full shrink-0 lg:w-80">
            {items.map((it) => (
              <TimelineRow
                key={`${it.kind}-${it.ref}`}
                item={it}
                selected={
                  selected?.kind === it.kind &&
                  (selected as { ref: string }).ref === it.ref
                }
                onSelect={() => {
                  if (it.kind === "patch") select({ kind: "patch", id: it.ref });
                  else if (it.kind === "job") select({ kind: "job", id: it.ref });
                  else select({ kind: "snapshot", id: it.ref });
                }}
              />
            ))}
          </ol>

          {/* 右：选中详情 */}
          <div className="min-w-0 flex-1 lg:border-l lg:border-line lg:pl-6">
            {selected?.kind === "patch" ? (
              <PatchDetail patch={selected.patch} model={model} />
            ) : selected?.kind === "job" ? (
              <JobDetail job={selected.job} model={model} />
            ) : selected?.kind === "snapshot" ? (
              <SnapshotDetail snapshot={selected.snapshot} model={model} />
            ) : (
              <p className="text-13 text-ink-3">在左侧时间线选中一条记录查看详情。</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/* -------------------------------------------------------------- 时间线行 */

function summaryOf(it: TimelineItem): string {
  if (it.kind === "patch") {
    const p = it.patch;
    return `${(p.changed_paths ?? []).length} 处变更 · 消化 ${(p.sources_consumed ?? []).length} 个来源`;
  }
  if (it.kind === "job") return `状态 ${it.job.status}`;
  return `类型 ${it.snapshot.source_type}`;
}

function TimelineRow({
  item,
  selected,
  onSelect,
}: {
  item: TimelineItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const badge = KIND_BADGE[item.kind];
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected || undefined}
        className={cn(
          "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left transition-colors duration-120",
          selected
            ? "border-accent bg-accent-soft"
            : "border-transparent hover:bg-hover",
        )}
      >
        <span className="flex items-baseline gap-2">
          <Mono className="min-w-0 flex-1 truncate text-12 text-ink">{item.ref}</Mono>
          <Badge tone={badge.tone}>{badge.label}</Badge>
        </span>
        <span className="flex items-baseline justify-between gap-2 text-12 text-ink-3">
          <span>{fmtTime(item.ts)}</span>
          <span className="truncate">{summaryOf(item)}</span>
        </span>
      </button>
    </li>
  );
}

/* -------------------------------------------------------------- patch 详情 */

function PatchDetail({ patch, model }: { patch: PatchRecord; model: Model }) {
  const jump = useApp((s) => s.jump);
  const select = useApp((s) => s.select);
  const focusSource = useApp((s) => s.focusSource);

  const changes = patchChanges(model, patch);
  const lineage = patch.lineage ?? {};
  const lineageItems = [
    { term: "model", definition: <Mono>{lineage.model ?? "—"}</Mono> },
    { term: "provider", definition: <Mono>{lineage.provider ?? "—"}</Mono> },
    { term: "tokens", definition: <Mono>{fmtTokens(lineage.tokens)}</Mono> },
    { term: "driver", definition: <Mono>{lineage.driver ?? "—"}</Mono> },
    { term: "producer", definition: <Mono>{lineage.producer ?? "—"}</Mono> },
  ];
  const flagEntries = Object.entries(patch.flag_counts ?? {});

  return (
    <div className="flex flex-col gap-6">
      <header>
        <Mono className="text-14 text-ink">{patch.patch_id}</Mono>
        <p className="mt-1 text-12 text-ink-3">
          {fmtTime(patch.ts)} · base <Mono>{shortSha(patch.base_commit)}</Mono>
          {patch.job_id && (
            <>
              {" · job "}
              <button
                type="button"
                className="text-accent underline-offset-2 hover:underline"
                onClick={() => select({ kind: "job", id: patch.job_id! })}
              >
                <Mono>{patch.job_id}</Mono>
              </button>
            </>
          )}
        </p>
        <p className="mt-1 text-12 text-ink-3">
          skill <Mono>v{patch.skill_version ?? "—"}</Mono> · effort{" "}
          <Mono>{patch.effort ?? "—"}</Mono>
        </p>
      </header>

      <section>
        <SectionRule no={1} title="变更文档" />
        <ul className="mt-3 flex flex-col">
          {changes.map((ch) => {
            const docId =
              ch.document_id ?? model.docByPath.get(ch.path)?.document_id ?? null;
            return (
              <li key={ch.path} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  disabled={!docId}
                  onClick={() => docId && jump({ kind: "document", id: docId }, "library")}
                  className="flex w-full items-baseline gap-2 py-1.5 text-left transition-colors duration-120 enabled:hover:bg-hover disabled:opacity-50"
                >
                  <span className="w-14 shrink-0 text-12 text-ink-3">
                    {ch.change_type === "created" ? "新建" : "修改"}
                  </span>
                  <Mono className="min-w-0 flex-1 truncate text-12 text-ink-2">{ch.path}</Mono>
                </button>
              </li>
            );
          })}
          {changes.length === 0 && <li className="py-1.5 text-12 text-ink-3">—</li>}
        </ul>
      </section>

      <section>
        <SectionRule no={2} title="消化来源" />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {(patch.sources_consumed ?? []).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => focusSource(s)}
              className="rounded-1 border border-line-2 bg-surface px-1.5 py-0.5 transition-colors duration-120 hover:bg-hover"
            >
              <Mono className="text-12 text-ink-2">{s}</Mono>
            </button>
          ))}
          {(patch.sources_consumed ?? []).length === 0 && (
            <span className="text-12 text-ink-3">—</span>
          )}
        </div>
      </section>

      <section>
        <SectionRule no={3} title="Lineage" />
        <DefinitionList className="mt-1" items={lineageItems} />
      </section>

      {(patch.claims ?? []).length > 0 && (
        <section>
          <SectionRule no={4} title={`Claims trace · ${patch.claims.length}`} />
          <ul className="mt-3 flex flex-col">
            {patch.claims.map((c, i) => {
              const docId = c.anchor?.document_id;
              const anchor = c.anchor?.anchor;
              const note =
                c.note ??
                (docId && anchor
                  ? model.sidecarNotes.get(claimKey(docId, anchor))?.traces.slice(-1)[0]?.note
                  : undefined);
              const jumpable = !!docId && !!anchor;
              return (
                <li key={`${docId}-${anchor}-${i}`} className="border-b border-line py-1.5 last:border-b-0">
                  <button
                    type="button"
                    disabled={!jumpable}
                    onClick={() =>
                      jumpable &&
                      jump({ kind: "claim", documentId: docId!, anchor: anchor! }, "library")
                    }
                    className="flex w-full flex-col gap-0.5 text-left transition-colors duration-120 enabled:hover:bg-hover disabled:opacity-60"
                  >
                    <span className="flex items-baseline gap-2">
                      <Mono className="text-12 text-accent">
                        {docId ?? "—"}::{anchor ?? "—"}
                      </Mono>
                      {(c.flags ?? []).map((f) => (
                        <Badge key={f} tone="warn">{f}</Badge>
                      ))}
                    </span>
                    {note && <span className="text-12 text-ink-3">{note}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {(patch.escalations ?? []).length > 0 && (
        <section>
          <SectionRule no={5} title={`Escalations · ${patch.escalations.length}`} />
          <div className="mt-3 flex flex-col gap-2">
            {patch.escalations.map((e, i) => {
              const { label, body } = escalationText(e);
              const anchorText =
                typeof e.anchor === "string"
                  ? e.anchor
                  : e.anchor
                    ? `${e.anchor.document_id ?? ""}::${e.anchor.anchor ?? ""}`
                    : null;
              return (
                <Callout key={i} tone="notice" title={label}>
                  {body && <span className="block">{body}</span>}
                  {anchorText && (
                    <Mono className="mt-0.5 block text-12 text-ink-3">{anchorText}</Mono>
                  )}
                </Callout>
              );
            })}
          </div>
        </section>
      )}

      {flagEntries.length > 0 && (
        <section>
          <SectionRule no={6} title="Flag 计数" />
          <div className="mt-3 flex flex-wrap gap-1.5">
            {flagEntries.map(([f, n]) => (
              <Badge key={f} tone="neutral">
                {f} · {n}
              </Badge>
            ))}
          </div>
        </section>
      )}

      {(patch.merges ?? []).length > 0 && (
        <section>
          <SectionRule no={7} title={`Merges · ${patch.merges.length}`} />
          <ul className="mt-3 flex flex-col gap-1">
            {patch.merges.map((m, i) => (
              <li key={i}>
                <Mono className="break-all text-12 text-ink-3">
                  {typeof m === "string" ? m : JSON.stringify(m)}
                </Mono>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- job 详情 */

function JobDetail({ job, model }: { job: JobRecord; model: Model }) {
  const select = useApp((s) => s.select);
  const tone: BadgeTone =
    job.status === "compiled" ? "ok" : job.status === "failed" ? "danger" : "warn";
  const patch = job.patch_id ? model.patchById.get(job.patch_id) : undefined;
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-2">
        <Mono className="text-14 text-ink">{job.job_id}</Mono>
        <Badge tone={tone}>{job.status}</Badge>
      </header>
      <DefinitionList
        items={[
          { term: "时间", definition: fmtTime(job.ts) },
          {
            term: "产出 patch",
            definition: patch ? (
              <button
                type="button"
                className="text-accent underline-offset-2 hover:underline"
                onClick={() => select({ kind: "patch", id: patch.patch_id })}
              >
                <Mono>{patch.patch_id}</Mono>
              </button>
            ) : (
              <Mono>{job.patch_id ?? "—"}</Mono>
            ),
          },
        ]}
      />
    </div>
  );
}

/* ----------------------------------------------------------- snapshot 详情 */

function SnapshotDetail({ snapshot, model }: { snapshot: Snapshot; model: Model }) {
  const select = useApp((s) => s.select);
  const snapshots = useApp((s) => s.snapshots);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const setSnapshot = useApp((s) => s.setSnapshot);

  const consumers = model.dataset.timeline.patches.filter((p) =>
    (p.sources_consumed ?? []).includes(snapshot.source_id),
  );
  // timeline snapshot 是「来源快照」；只有它与 git ref 同名时才可切入只读态。
  const gitRef = snapshots.find((s) => s.ref === snapshot.source_id)?.ref ?? null;
  const viewing = currentSnapshot != null && currentSnapshot === gitRef;

  return (
    <div className="flex flex-col gap-4">
      <header>
        <Mono className="text-14 text-ink">{snapshot.source_id}</Mono>
        <p className="mt-1 text-12 text-ink-3">
          捕获 {fmtTime(snapshot.captured_at)} · 类型 {snapshot.source_type}
        </p>
      </header>
      <DefinitionList
        items={[
          { term: "checksum", definition: <Mono className="break-all">{snapshot.checksum}</Mono> },
          { term: "class", definition: <Mono>{snapshot.source_class ?? "—"}</Mono> },
          {
            term: "uri",
            definition: <Mono className="break-all">{snapshot.source_uri ?? "—"}</Mono>,
          },
        ]}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={!gitRef || viewing}
          title={gitRef ? "切到此快照的只读视图" : "此快照没有对应的 git ref，无法切入只读态"}
          onClick={() => gitRef && setSnapshot(gitRef)}
        >
          查看此快照
        </Button>
        {currentSnapshot && (
          <Button size="sm" variant="ghost" onClick={() => setSnapshot(null)}>
            回到 HEAD
          </Button>
        )}
        {!gitRef && (
          <span className="text-12 text-ink-3">该来源快照无对应 git ref。</span>
        )}
      </div>

      <section>
        <SectionRule no={1} title={`被以下 patch 消化 · ${consumers.length}`} />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {consumers.map((p) => (
            <button
              key={p.patch_id}
              type="button"
              onClick={() => select({ kind: "patch", id: p.patch_id })}
              className="rounded-1 border border-line-2 bg-surface px-1.5 py-0.5 transition-colors duration-120 hover:bg-hover"
            >
              <Mono className="text-12 text-ink-2">{p.patch_id}</Mono>
            </button>
          ))}
          {consumers.length === 0 && <span className="text-12 text-ink-3">—</span>}
        </div>
      </section>
    </div>
  );
}

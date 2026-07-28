import {
  FileEdit,
  FilePlus2,
  GitMerge,
  Cpu,
  Coins,
  AlertTriangle,
  ArrowUpRight,
} from "lucide-react";
import type { JobRecord, PatchRecord } from "@/lib/types";
import type { Model, PatchDocChange } from "@/lib/model";
import { patchChanges } from "@/lib/model";
import { JOB_STATUS_ICON } from "@/lib/events";
import { fmtTime, fmtTokens, shortSha } from "@/lib/format";
import { Chip } from "./ui";
import { flagMeta, escalationText } from "@/lib/claim";
import { useApp } from "@/lib/store";
import { cn } from "@/lib/cn";

export function JobCard({
  job,
  patch,
  model,
  active,
  onReplay,
}: {
  job: JobRecord;
  patch: PatchRecord | null;
  model: Model;
  active: boolean;
  onReplay: () => void;
}) {
  const { jump, select } = useApp();
  const StatusIcon = JOB_STATUS_ICON[job.status] ?? JOB_STATUS_ICON.running;
  const statusColor =
    job.status === "compiled"
      ? "var(--color-verified)"
      : job.status === "failed"
        ? "var(--color-disputed)"
        : "var(--color-text-tertiary)";

  const changes = patch ? patchChanges(model, patch) : [];
  const created = changes.filter((c) => c.change_type === "created");
  const modified = changes.filter((c) => c.change_type === "modified");
  // label field varies by producer (reason/trigger/category/policy) — match "冲突"
  // / "conflict" across whichever is present rather than the old policy-only guess.
  const conflicts =
    patch?.escalations?.filter((e) => {
      const label = escalationText(e).label;
      return label.includes("冲突") || label.toLowerCase().includes("conflict");
    }) ?? [];
  const failed = job.status === "failed";

  return (
    <div
      id={`job-${job.job_id}`}
      className={cn(
        "border rounded-sm bg-card transition-colors",
        failed
          ? "border-[var(--color-danger)]"
          : active
            ? "border-[var(--color-border-strong)]"
            : "border-border",
      )}
      style={
        failed
          ? { boxShadow: "inset 3px 0 0 var(--color-danger)" }
          : active
            ? { boxShadow: "inset 3px 0 0 var(--color-accent)" }
            : undefined
      }
    >
      {/* header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border-subtle">
        <StatusIcon size={16} style={{ color: statusColor }} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[length:var(--text-sm)] truncate">{job.job_id}</span>
            {patch && (
              <button
                onClick={() => jump({ kind: "patch", id: patch.patch_id }, "history")}
                className="font-mono text-[length:var(--text-2xs)] px-1.5 py-[1px] border border-border rounded-sm hover:bg-accent"
                title="在 History 查看该 patch"
              >
                {patch.patch_id}
              </button>
            )}
          </div>
          <div className="text-[length:var(--text-2xs)] text-muted-foreground">{fmtTime(job.ts)}</div>
        </div>
        <div className="flex-1" />
        <button
          onClick={onReplay}
          className="inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-muted-foreground hover:text-foreground underline underline-offset-2"
        >
          回放 <ArrowUpRight size={11} />
        </button>
      </div>

      {/* change rows */}
      <div className="px-4 py-3 space-y-2">
        <ChangeRow
          icon={<FilePlus2 size={13} style={{ color: "var(--color-verified)" }} />}
          label="created"
          changes={created}
          model={model}
          onOpen={(id) => select({ kind: "document", id })}
        />
        <ChangeRow
          icon={<FileEdit size={13} style={{ color: "var(--color-info)" }} />}
          label="modified"
          changes={modified}
          model={model}
          onOpen={(id) => select({ kind: "document", id })}
        />
        {conflicts.length > 0 && (
          <div className="flex items-start gap-2">
            <GitMerge size={13} style={{ color: "var(--color-disputed)" }} className="mt-1" />
            <div className="min-w-0">
              <div className="text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground">
                conflict
              </div>
              {conflicts.map((c, i) => {
                const { label, body } = escalationText(c);
                return (
                  <div key={i} className="text-[length:var(--text-sm)] mt-0.5">
                    {body ?? label}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* meta footer */}
      {patch && (
        <div className="px-4 py-2.5 border-t border-border-subtle bg-[var(--color-surface-muted)] flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Cpu size={12} /> {patch.lineage?.model || patch.lineage?.driver || "—"}
            {patch.lineage?.provider ? ` · ${patch.lineage.provider}` : ""}
          </span>
          <span className="inline-flex items-center gap-1">
            <Coins size={12} /> {fmtTokens(patch.lineage?.tokens)} tok
          </span>
          <span>effort: {patch.effort ?? "—"}</span>
          <span>skill v{patch.skill_version ?? "—"}</span>
          <span className="font-mono">base {shortSha(patch.base_commit)}</span>
          {patch.sources_consumed?.length > 0 && (
            <span className="inline-flex items-center gap-1">
              sources: {patch.sources_consumed.map((s) => (
                <button
                  key={s}
                  onClick={() => jump({ kind: "snapshot", id: s }, "history")}
                  className="font-mono hover:text-foreground underline underline-offset-2"
                >
                  {s}
                </button>
              ))}
            </span>
          )}
          {Object.entries(patch.flag_counts ?? {}).map(([f, n]) => {
            const meta = flagMeta(f);
            return (
              <Chip key={f} dotColor={meta.token}>
                {meta.label} · {n}
              </Chip>
            );
          })}
          {patch.escalations?.length > 0 && (
            <span
              className="inline-flex items-center gap-1"
              style={{ color: "var(--color-open-question)" }}
            >
              <AlertTriangle size={12} /> {patch.escalations.length} escalation
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function ChangeRow({
  icon,
  label,
  changes,
  model,
  onOpen,
}: {
  icon: React.ReactNode;
  label: string;
  changes: PatchDocChange[];
  model: Model;
  onOpen: (docId: string) => void;
}) {
  if (changes.length === 0) return null;
  return (
    <div className="flex items-start gap-2">
      <span className="mt-1">{icon}</span>
      <div className="min-w-0">
        <div className="text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground">
          {label} · {changes.length}
        </div>
        <div className="flex flex-wrap gap-1.5 mt-1">
          {changes.map((ch) => {
            const docId =
              ch.document_id ?? model.docByPath.get(ch.path)?.document_id ?? null;
            const doc = docId ? model.docById.get(docId) : model.docByPath.get(ch.path);
            return (
              <button
                key={ch.path}
                onClick={() => docId && onOpen(docId)}
                disabled={!docId}
                className="inline-flex items-center gap-1 text-[length:var(--text-xs)] font-mono px-1.5 py-[2px] border border-border rounded-sm hover:bg-accent disabled:opacity-60 disabled:hover:bg-transparent"
                title={doc ? `打开 ${doc.title}` : ch.path}
              >
                {ch.path}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

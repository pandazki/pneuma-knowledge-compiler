import { Camera, History, Trash2 } from "lucide-react";
import { fmtTime, squish } from "@/lib/format";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Combobox, type ComboboxItem } from "@/ui/Combobox";
import { Button } from "@/ui/Button";
import { Mono } from "@/ui/Mono";

const HEAD = "__head__";
const KB_PREFIX = "kb:";

/** A snapshot's freeze moment in the app's own stamp format; the raw ISO string is a poor label. */
function freezeMoment(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "" : fmtTime(iso);
}

/**
 * The app's READ PLANE selector. Three kinds of plane, most capable first:
 *
 *  1. HEAD — the live, writable base.
 *  2. A frozen knowledge-base snapshot — the whole base copied under a read-only tenant, so
 *     it can be BROWSED AND ASKED. This is what "what did it say in March?" needs, and the
 *     footer is where one is taken.
 *  3. A canonical commit — free from git and always available, but canonical only: it has no
 *     frozen retrieval layers, so it is browse-only. Kept because commit-level browsing is
 *     genuinely useful and costs nothing; ranked last because it cannot answer questions.
 *
 * Selecting anything but HEAD is read-only and AppShell raises its archive stamp.
 */
export function SnapshotPicker() {
  const t = useT();
  const snapshots = useApp((s) => s.snapshots);
  const snapshotTotal = useApp((s) => s.snapshotTotal);
  const nextCursor = useApp((s) => s.snapshotNextCursor);
  const loading = useApp((s) => s.snapshotsLoading);
  const error = useApp((s) => s.snapshotError);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const setSnapshot = useApp((s) => s.setSnapshot);
  const loadSnapshots = useApp((s) => s.loadSnapshots);
  const loadMoreSnapshots = useApp((s) => s.loadMoreSnapshots);

  const kbSnapshots = useApp((s) => s.kbSnapshots);
  const kbLoading = useApp((s) => s.kbSnapshotsLoading);
  const kbError = useApp((s) => s.kbSnapshotError);
  const currentKb = useApp((s) => s.currentKbSnapshot);
  const setKbSnapshot = useApp((s) => s.setKbSnapshot);
  const createSnapshot = useApp((s) => s.createSnapshot);
  const removeSnapshot = useApp((s) => s.removeSnapshot);

  const scaleOf = (counts: Record<string, number>): string => {
    const sources = counts.sources ?? 0;
    const claims = counts.claims ?? 0;
    return sources || claims ? t("nav.snapshot.kbScale", { sources, claims }) : "";
  };

  const items: ComboboxItem[] = [
    {
      value: HEAD,
      label: "HEAD",
      keywords: t("nav.snapshot.headKeywords"),
      group: t("nav.snapshot.groupLive"),
      render: () => (
        <span className="flex items-baseline gap-2">
          <Mono>HEAD</Mono>
          <span className="text-12 text-ink-3">{t("nav.snapshot.headNote")}</span>
        </span>
      ),
    },
    ...kbSnapshots.map(
      (s): ComboboxItem => ({
        value: `${KB_PREFIX}${s.snapshot_id}`,
        label: s.label,
        keywords: `${s.snapshot_id} ${s.canonical_ref}`,
        group: t("nav.snapshot.groupFrozen"),
        // A non-ready snapshot stays visible but unselectable: hiding it would leave the user
        // unable to see that their snapshot is still copying, or why it failed.
        disabled: s.status !== "ready",
        render: () => (
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="min-w-0 truncate text-ink-2">{s.label}</span>
              {s.status !== "ready" && (
                <span className="shrink-0 text-12 text-ink-3">
                  {t(
                    s.status === "creating"
                      ? "nav.snapshot.kbCreating"
                      : "nav.snapshot.kbFailed",
                  )}
                </span>
              )}
            </span>
            <span className="flex min-w-0 items-baseline gap-2 text-12 text-ink-3">
              <span className="shrink-0">{freezeMoment(s.created_at)}</span>
              <span className="min-w-0 truncate">{scaleOf(s.counts)}</span>
            </span>
          </span>
        ),
      }),
    ),
    // A commit subject arrives with the spacing the writer used (`from        8 people
    // pages`); a one-line label is not the place to reproduce it.
    ...snapshots.map(
      (s): ComboboxItem => ({
        value: s.ref,
        label: squish(s.label) || s.ref,
        keywords: s.ref,
        group: t("nav.snapshot.groupCommits"),
        render: () => (
          <span className="flex min-w-0 items-baseline gap-2">
            <Mono className="shrink-0 text-12">{s.ref.slice(0, 10)}</Mono>
            <span className="min-w-0 truncate text-ink-2" title={s.label ?? undefined}>
              {squish(s.label)}
            </span>
            <span className="shrink-0 text-12 text-ink-3">{t("nav.snapshot.readOnly")}</span>
          </span>
        ),
      }),
    ),
  ];

  const empty =
    snapshots.length === 0 &&
    snapshotTotal === 0 &&
    kbSnapshots.length === 0 &&
    currentSnapshot == null &&
    !error;
  const initialLoading = loading && snapshots.length === 0;
  const loaded = Math.min(snapshots.length, snapshotTotal);

  const onChange = (value: string) => {
    if (value === HEAD) {
      setKbSnapshot(null);
      setSnapshot(null);
      return;
    }
    if (value.startsWith(KB_PREFIX)) {
      const id = value.slice(KB_PREFIX.length);
      setKbSnapshot(kbSnapshots.find((s) => s.snapshot_id === id) ?? null);
      return;
    }
    setSnapshot(value);
  };

  const footer = (query: string, close: () => void) => {
    const label = query.trim();
    return (
      <div className="flex flex-col gap-1.5 px-1 py-0.5">
        {(error || kbError) && (
          <p className="break-words px-1 text-12 text-danger" role="alert">
            {error ?? kbError}
          </p>
        )}
        {/* The filter text IS the new snapshot's label — same grammar as the user picker's
            "new profile" footer, so one habit covers both. */}
        <button
          type="button"
          disabled={!label || kbLoading}
          onClick={() => {
            void createSnapshot(label);
            close();
          }}
          className="flex w-full cursor-pointer items-center gap-2 rounded-1 px-2.5 py-1.5 text-left text-13 text-accent hover:bg-accent-soft disabled:cursor-default disabled:text-ink-3 disabled:hover:bg-transparent"
        >
          <Camera size={14} aria-hidden />
          <span className="min-w-0 truncate">
            {label
              ? t("nav.snapshot.kbCreateNamed", { label })
              : t("nav.snapshot.kbCreateHint")}
          </span>
        </button>
        {currentKb && (
          <button
            type="button"
            onClick={() => {
              void removeSnapshot(currentKb.snapshot_id);
              close();
            }}
            className="flex w-full cursor-pointer items-center gap-2 rounded-1 px-2.5 py-1.5 text-left text-13 text-danger hover:bg-danger-soft"
          >
            <Trash2 size={14} aria-hidden />
            <span className="min-w-0 truncate">
              {t("nav.snapshot.kbDelete", { label: currentKb.label })}
            </span>
          </button>
        )}
        {(nextCursor || error) && (
          <Button
            size="sm"
            variant="ghost"
            className="w-full justify-center"
            loading={loading}
            disabled={loading}
            onClick={() => void (nextCursor ? loadMoreSnapshots() : loadSnapshots())}
          >
            {nextCursor
              ? t("nav.snapshot.loadMore", { loaded, total: snapshotTotal })
              : t("nav.snapshot.retryList")}
          </Button>
        )}
      </div>
    );
  };

  return (
    <Combobox
      value={
        currentKb
          ? `${KB_PREFIX}${currentKb.snapshot_id}`
          : (currentSnapshot ?? HEAD)
      }
      onChange={onChange}
      items={items}
      trigger={
        <span className="flex items-center gap-1.5">
          {currentKb ? (
            <Camera size={13} aria-hidden className="text-ink-3" />
          ) : (
            <History size={13} aria-hidden className="text-ink-3" />
          )}
          <Mono className="text-13">
            {currentKb
              ? currentKb.label
              : currentSnapshot
                ? currentSnapshot.slice(0, 10)
                : "HEAD"}
          </Mono>
        </span>
      }
      triggerAriaLabel={t("nav.snapshot.switchAria")}
      filterPlaceholder={t("nav.snapshot.filterPlaceholder")}
      emptyText={t("nav.snapshot.empty")}
      footer={footer}
      disabled={empty || initialLoading}
      disabledNote={
        initialLoading
          ? t("nav.snapshot.loadingNote")
          : empty
            ? t("nav.snapshot.noneNote")
            : undefined
      }
    />
  );
}

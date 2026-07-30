import { History } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Combobox, type ComboboxItem } from "@/ui/Combobox";
import { Button } from "@/ui/Button";
import { Mono } from "@/ui/Mono";

const HEAD = "__head__";

/**
 * HEAD / historical-snapshot switcher: HEAD first (the live, writable state), then the git
 * refs (mono + label). Selecting anything but HEAD is the read-only historical state, and
 * AppShell raises its archive-stamp banner.
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

  const items: ComboboxItem[] = [
    {
      value: HEAD,
      label: "HEAD",
      keywords: t("nav.snapshot.headKeywords"),
      render: () => (
        <span className="flex items-baseline gap-2">
          <Mono>HEAD</Mono>
          <span className="text-12 text-ink-3">{t("nav.snapshot.headNote")}</span>
        </span>
      ),
    },
    ...snapshots.map(
      (s): ComboboxItem => ({
        value: s.ref,
        label: s.label ?? s.ref,
        keywords: s.ref,
        render: () => (
          <span className="flex min-w-0 items-baseline gap-2">
            <Mono className="shrink-0 text-12">{s.ref.slice(0, 10)}</Mono>
            <span className="min-w-0 truncate text-ink-2">{s.label ?? ""}</span>
            <span className="shrink-0 text-12 text-ink-3">{t("nav.snapshot.readOnly")}</span>
          </span>
        ),
      }),
    ),
  ];

  const empty =
    snapshots.length === 0 &&
    snapshotTotal === 0 &&
    currentSnapshot == null &&
    !error;
  const initialLoading = loading && snapshots.length === 0;
  const loaded = Math.min(snapshots.length, snapshotTotal);
  const footer =
    nextCursor || error
      ? () => (
          <div className="flex flex-col gap-1.5 px-1 py-0.5">
            {error && (
              <p className="break-words px-1 text-12 text-danger" role="alert">
                {error}
              </p>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="w-full justify-center"
              loading={loading}
              disabled={loading}
              onClick={() =>
                void (nextCursor ? loadMoreSnapshots() : loadSnapshots())
              }
            >
              {nextCursor
                ? t("nav.snapshot.loadMore", { loaded, total: snapshotTotal })
                : t("nav.snapshot.retryList")}
            </Button>
          </div>
        )
      : undefined;

  return (
    <Combobox
      value={currentSnapshot ?? HEAD}
      onChange={(v) => setSnapshot(v === HEAD ? null : v)}
      items={items}
      trigger={
        <span className="flex items-center gap-1.5">
          <History size={13} aria-hidden className="text-ink-3" />
          <Mono className="text-13">
            {currentSnapshot ? currentSnapshot.slice(0, 10) : "HEAD"}
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

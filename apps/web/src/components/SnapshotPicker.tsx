import { History } from "lucide-react";
import { useApp } from "@/lib/store";
import { Combobox, type ComboboxItem } from "@/ui/Combobox";
import { Button } from "@/ui/Button";
import { Mono } from "@/ui/Mono";

const HEAD = "__head__";

/**
 * HEAD / 历史快照切换：首项 HEAD（当前），其后 git ref 列表（mono + label）。
 * 选中非 HEAD = 只读历史态（AppShell 出档案戳横幅）。
 */
export function SnapshotPicker() {
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
      keywords: "head 当前",
      render: () => (
        <span className="flex items-baseline gap-2">
          <Mono>HEAD</Mono>
          <span className="text-12 text-ink-3">当前 · 可写</span>
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
            <span className="shrink-0 text-12 text-ink-3">只读</span>
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
                ? `加载更早版本 · ${loaded} / ${snapshotTotal}`
                : "重试版本列表"}
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
      triggerAriaLabel="切换到历史快照"
      filterPlaceholder="输入 ref 或标签…"
      emptyText="没有匹配的快照"
      footer={footer}
      disabled={empty || initialLoading}
      disabledNote={
        initialLoading ? "加载版本…" : empty ? "尚无版本" : undefined
      }
    />
  );
}

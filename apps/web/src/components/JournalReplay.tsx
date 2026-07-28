import { useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw, SkipForward, StepBack } from "lucide-react";
import type { JournalEvent } from "@/lib/types";
import { eventMeta, toneColor } from "@/lib/events";
import { fmtTime } from "@/lib/format";
import { Button, Eyebrow } from "./ui";
import { cn } from "@/lib/cn";

/** Sequential journal replay: reveals events one at a time, in order. */
export function JournalReplay({
  events,
  label,
}: {
  events: JournalEvent[];
  label: string;
}) {
  const [idx, setIdx] = useState(events.length); // revealed count
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // reset when the event set changes
  useEffect(() => {
    setIdx(events.length);
    setPlaying(false);
  }, [events]);

  useEffect(() => {
    if (!playing) return;
    if (idx >= events.length) {
      setPlaying(false);
      return;
    }
    timer.current = window.setTimeout(() => setIdx((i) => Math.min(i + 1, events.length)), 650);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [playing, idx, events.length]);

  // keep the leading edge in view during playback
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-ev="${idx - 1}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [idx]);

  const start = () => {
    if (idx >= events.length) setIdx(0);
    setPlaying(true);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
        <div className="min-w-0">
          <Eyebrow>Journal 回放</Eyebrow>
          <div className="text-[length:var(--text-2xs)] text-muted-foreground mt-1 truncate">{label}</div>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1">
          <Button size="icon" variant="ghost" title="重置" onClick={() => { setIdx(0); setPlaying(false); }}>
            <RotateCcw size={15} />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            title="上一步"
            onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)); }}
          >
            <StepBack size={15} />
          </Button>
          <Button
            size="icon"
            variant="primary"
            title={playing ? "暂停" : "播放"}
            onClick={() => (playing ? setPlaying(false) : start())}
          >
            {playing ? <Pause size={15} /> : <Play size={15} />}
          </Button>
          <Button
            size="icon"
            variant="ghost"
            title="下一步"
            onClick={() => { setPlaying(false); setIdx((i) => Math.min(events.length, i + 1)); }}
          >
            <SkipForward size={15} />
          </Button>
        </div>
      </div>

      {/* progress */}
      <div className="h-[3px] bg-[var(--color-surface-muted)]">
        <div
          className="h-full transition-[width] duration-300"
          style={{
            width: `${events.length ? (idx / events.length) * 100 : 0}%`,
            background: "var(--color-accent)",
          }}
        />
      </div>
      <div className="px-4 py-1.5 text-[length:var(--text-2xs)] text-muted-foreground border-b border-border-subtle">
        {idx} / {events.length} 事件
      </div>

      {/* event stream */}
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
        {events.length === 0 && (
          <div className="text-sm text-muted-foreground py-8 text-center">
            无 journal 事件（journal.jsonl 为空或未随导出提供）。
          </div>
        )}
        <ol className="relative">
          {events.map((ev, i) => {
            const meta = eventMeta(ev.type);
            const Icon = meta.icon;
            const revealed = i < idx;
            const isLead = i === idx - 1;
            const color = toneColor(meta.tone);
            return (
              <li
                key={ev.event_id ?? i}
                data-ev={i}
                className={cn(
                  "relative flex gap-3 pb-4 transition-opacity duration-300",
                  revealed ? "opacity-100" : "opacity-30",
                )}
              >
                {/* rail */}
                <div className="relative flex flex-col items-center">
                  <span
                    className="z-10 flex items-center justify-center rounded-full"
                    style={{
                      width: 22,
                      height: 22,
                      border: `1px solid ${isLead ? color : "var(--color-border)"}`,
                      background: "var(--color-card)",
                    }}
                  >
                    <Icon size={12} style={{ color }} />
                  </span>
                  {i < events.length - 1 && (
                    <span
                      className="absolute top-[22px] bottom-0 w-px"
                      style={{ background: "var(--color-border)" }}
                    />
                  )}
                </div>
                {/* body */}
                <div className="min-w-0 pt-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[length:var(--text-sm)] font-medium">{meta.label}</span>
                    <span className="font-mono text-[length:var(--text-2xs)] text-muted-foreground">{ev.type}</span>
                  </div>
                  <div className="text-[length:var(--text-2xs)] text-muted-foreground mt-0.5 flex flex-wrap gap-x-3">
                    <span>{fmtTime(ev.ts)}</span>
                    {ev.job_id && <span className="font-mono">{ev.job_id}</span>}
                    {ev.patch_id && <span className="font-mono">{ev.patch_id}</span>}
                  </div>
                  {ev.payload && Object.keys(ev.payload).length > 0 && (
                    <pre className="mt-1 text-[length:var(--text-2xs)] font-mono text-muted-foreground bg-[var(--color-surface-muted)] rounded-sm px-2 py-1 overflow-x-auto">
                      {JSON.stringify(ev.payload)}
                    </pre>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { provisionalAnswer } from "@/lib/answerStream";
import { liveStages, stampReceived, type FlowStage, type StageEvent } from "@/lib/stages";

/**
 * The state behind a lane being watched: the stages as they open and settle, and the answer
 * text as it is written.
 *
 * One hook rather than three copies, because Recall's fast lane, Recall's deep lane, Ask's
 * build and Ask's questions all watch the same two things over the same event vocabulary.
 * What differs between them is only which stream client is called.
 *
 * TWO CLOCKS, DELIBERATELY. A settled stage reports the SERVER's measurement and is never
 * recomputed here. A stage that has started and not yet ended has no measurement to report, so
 * its counter is derived — whatever it had already accumulated, plus the time since its start
 * frame arrived. That is why `stampReceived` runs at the edge and the reducer itself stays
 * pure: the clock is an argument, never something the fold reads. It is deliberately NOT the
 * event's `at_ms`, which is the lane's elapsed clock: counting from there would show a stage
 * as older than it is and then snap it backwards the moment it settled.
 *
 * The ticking interval runs only while `active`. A finished answer redraws from the stages it
 * carries, so leaving a timer running behind it would be re-timing something already measured.
 */
export interface LiveLane {
  /** The rows to hand `StageStrip`'s `live` prop. Empty before the first frame. */
  stages: FlowStage[];
  /**
   * The PROSE so far, ready to show. Provisional — the `done` payload replaces it.
   *
   * A `structured` answer streams as JSON, so the deltas that arrive are not what a reader
   * should be shown; `provisionalAnswer` reads the answer out of the partial object and a
   * prose answer passes through it untouched (`lib/answerStream.ts`). Rendering happens here
   * rather than in each view because every lane that streams an answer has the same problem.
   */
  text: string;
  /** Clear everything before a new run. */
  reset: () => void;
  onStage: (event: StageEvent) => void;
  onToken: (delta: string) => void;
}

//: Fast enough that a counter reads as a clock, slow enough to cost nothing.
const TICK_MS = 100;

export function useLiveLane(active: boolean): LiveLane {
  const [events, setEvents] = useState<StageEvent[]>([]);
  const [text, setText] = useState("");
  const [now, setNow] = useState(() => Date.now());
  // A new stage starting means the text that came before belongs to a step that is over —
  // the previous turn of an agentic run, or a structured attempt that fell back. It is marked
  // STALE rather than cleared, so the reader keeps seeing something until there is something
  // to replace it with; clearing on the start would blank the answer during every tool round.
  const stale = useRef(false);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [active]);

  const reset = useCallback(() => {
    stale.current = false;
    setEvents([]);
    setText("");
    setNow(Date.now());
  }, []);

  const onStage = useCallback((event: StageEvent) => {
    if (event.phase === "start") stale.current = true;
    setEvents((seen) => [...seen, stampReceived(event)]);
  }, []);

  const onToken = useCallback((delta: string) => {
    setText((seen) => {
      if (!stale.current) return seen + delta;
      stale.current = false;
      return delta;
    });
  }, []);

  return {
    stages: liveStages(events, now),
    text: provisionalAnswer(text),
    reset,
    onStage,
    onToken,
  };
}

/**
 * The Steward's prose, rendered as Markdown while it is still being written.
 *
 * The renderer is the app's own — `react-markdown` + `remark-gfm`, the same pair the cited
 * answers and the prompt studio use — under the reading layer (`.prose`, DESIGN.md §2.4). No
 * streaming Markdown library was added: the only thing a streamed answer needs beyond an
 * ordinary one is that the half-typed frame at the tail does not make the page jump, and that
 * is a cut, not a parser (`lib/streamingMarkdown.ts`). The unfinished frame is rendered as
 * preformatted text — what it will look like once it closes — so every character that has
 * arrived is on the screen and the layout settles exactly once.
 */

import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { splitStreamingMarkdown } from "@/lib/streamingMarkdown";

export const StewardMarkdown = memo(function StewardMarkdown({ text }: { text: string }) {
  const { body, pending } = useMemo(() => splitStreamingMarkdown(text), [text]);
  return (
    <div className="prose max-w-none text-14">
      {body !== "" && <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>}
      {pending != null && (
        // A fence's own marker line is not shown — the finished render will not show it
        // either — so what stands here is what was typed inside the frame, and a table in
        // progress keeps its pipes because those ARE its text until the row is complete.
        <pre className="font-mono text-13 text-ink-2" title={pending.info || undefined}>
          {pending.text}
        </pre>
      )}
    </div>
  );
});

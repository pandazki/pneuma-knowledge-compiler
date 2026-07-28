/**
 * Render model answers as safe Markdown while binding `[cite: …]` groups to
 * clickable source footnotes. Unknown local handles remain visible plain text.
 */
import { useMemo, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { prepareCitedMarkdown } from "@/lib/citedMarkdown";
import { useApp } from "@/lib/store";
import { Footnote } from "@/ui/Footnote";

export function CitedAnswer({
  text,
  handles,
}: {
  text: string;
  handles?: Record<string, string> | null;
}) {
  const focusSource = useApp((state) => state.focusSource);
  const prepared = useMemo(
    () => prepareCitedMarkdown(text, handles ?? {}),
    [text, handles],
  );

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={(url) =>
        url.startsWith("pneuma-cite:") ? url : defaultUrlTransform(url)
      }
      components={{
        a: ({
          href,
          children,
          ...props
        }: ComponentPropsWithoutRef<"a">) => {
          const citationMatch = href?.match(/^pneuma-cite:(\d+)$/);
          if (citationMatch) {
            const index = Number(citationMatch[1]);
            const citation = prepared.citations[index];
            if (!citation) return <>{children}</>;
            return (
              <Footnote
                index={index + 1}
                citation={citation}
                onJump={(entry) =>
                  focusSource(
                    entry.sourceId,
                    entry.blockStart != null
                      ? {
                          start: entry.blockStart,
                          end: entry.blockEnd ?? entry.blockStart,
                        }
                      : null,
                  )
                }
              />
            );
          }
          return (
            <a
              href={href}
              rel="noreferrer"
              target="_blank"
              {...props}
            >
              {children}
            </a>
          );
        },
      }}
    >
      {prepared.markdown}
    </ReactMarkdown>
  );
}

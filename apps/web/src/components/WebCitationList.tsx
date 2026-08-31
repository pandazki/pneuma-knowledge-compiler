import { ExternalLink } from "lucide-react";
import { cn } from "@/ui/cn";
import { Mono } from "@/ui/Mono";

export interface WebCitationEntry {
  title: string;
  url: string;
}

export interface WebCitationListProps {
  citations: WebCitationEntry[];
  className?: string;
}

/** `https://example.test/a/b?c=d` → `example.test`. The part a person recognises. */
function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * The web card's citation apparatus — deliberately the SAME set as `CitationList`.
 *
 * The owner's rule: the evidence surface is uniform across origins. A web card's pages sit
 * exactly where a library card's source spans sit, in the same numbered rows, under the same
 * hairline, at the same weights — because a reader checking where an answer came from is
 * doing one thing, not two, and a second visual language for it would say the web answer is
 * a different KIND of claim rather than a claim from a different place.
 *
 * One affordance differs, and only because the destination does: a source span opens in-app,
 * a page opens a new tab. So these rows are anchors rather than buttons, they carry the
 * external-link mark, and the full URL is on the title attribute — nobody should have to
 * click to find out where a link goes.
 */
export function WebCitationList({ citations, className }: WebCitationListProps) {
  if (citations.length === 0) return null;
  return (
    <ol className={cn("flex flex-col border-t border-line pt-1", className)}>
      {citations.map((c, i) => (
        <li key={`${c.url}-${i}`}>
          <a
            href={c.url}
            target="_blank"
            rel="noreferrer noopener"
            title={c.url}
            className="group/citation flex w-full items-baseline gap-2 rounded-1 px-1 py-0.5 text-left transition-colors duration-120 hover:bg-hover"
          >
            <Mono className="w-6 shrink-0 text-12 leading-[1.45] text-ink-3">[{i + 1}]</Mono>
            <span className="min-w-0 flex-1 truncate text-12 leading-[1.45] text-ink-2 transition-colors duration-120 group-hover/citation:text-ink">
              {c.title || c.url}
            </span>
            <Mono
              className="hidden max-w-32 shrink-0 truncate text-12 leading-[1.45] text-ink-3 sm:block"
              title={c.url}
            >
              {host(c.url)}
            </Mono>
            <ExternalLink size={11} className="shrink-0 text-ink-3" aria-hidden />
          </a>
        </li>
      ))}
    </ol>
  );
}

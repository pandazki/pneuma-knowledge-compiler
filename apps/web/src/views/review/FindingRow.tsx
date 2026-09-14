import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { useApp } from "@/lib/store";
import { useLocale, useT, useTOr } from "@/lib/useT";
import { catalogText, type CheckFinding } from "@/lib/lensReport";
import { Badge } from "@/ui/Badge";
import { Mono } from "@/ui/Mono";

/**
 * One check finding, in the shape §3.1 gives it: the sentence, what to do, the pages it is
 * about, and the evidence underneath.
 *
 * The sentence leads and the machine text recedes, which is the whole difference between this
 * and a linter's output: a count of dead ends tells a Steward nothing they can act on, and the
 * paths and evidence — the parts they eventually need — are worth nothing until they know why
 * they are looking at them.
 *
 * Every sentence here is the catalogue's, already rendered in both packs by the service
 * (`impact.text.en` / `.zh`, docs/design/structure-lens.md §5.1); the console keeps no copy.
 * The id is shown as itself because it is the name the Steward and `pkc library review` use
 * for this fault, and a finding whose kind this build has never heard of still renders under
 * that kind's own name.
 */
export function FindingRow({ finding }: { finding: CheckFinding }) {
  const t = useT();
  const tOr = useTOr();
  const locale = useLocale();
  const jump = useApp((s) => s.jump);

  const impact = catalogText(locale, finding.impact);
  const action = catalogText(locale, finding.action);
  const kind = finding.kind ? tOr(`review.kind.${finding.kind}`, finding.kind) : "";

  return (
    <li className="border-b border-line last:border-b-0">
      <div className="flex flex-col gap-2 py-3">
        <p className="max-w-measure text-balance text-14 leading-[1.5] text-ink">{impact}</p>

        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          {finding.id && <Mono className="text-12 text-ink-3">{finding.id}</Mono>}
          {kind && (
            <Badge>
              {/* Visually the word; to a screen reader what the word is saying about the row. */}
              <span className="sr-only">{t("review.kind.aria", { kind })}</span>
              <span aria-hidden>{kind}</span>
            </Badge>
          )}
        </p>

        {action && (
          <p className="flex items-baseline gap-2 text-13 text-ink-2">
            <Mono aria-hidden className="shrink-0 text-12 text-ink-3">
              →
            </Mono>
            <span className="min-w-0 max-w-measure">{action}</span>
          </p>
        )}

        {finding.paths.length > 1 && (
          /* The first path is the group's own heading; these are the rest it touches. */
          <PathList
            label={t("review.pages.label")}
            paths={finding.paths.slice(1)}
            onOpen={(path) => jump({ kind: "document", id: path }, "library")}
          />
        )}

        {finding.targets.length > 0 && (
          /* Not links: a target may be exactly the path that has no document. */
          <PathList label={t("review.targets.label")} paths={finding.targets} onOpen={null} />
        )}

        {finding.evidence.length > 0 && (
          <ul className="flex flex-col gap-0.5" aria-label={t("review.evidence.label")}>
            {finding.evidence.map((line, i) => (
              <li key={`${line}-${i}`} className="flex min-w-0 items-baseline gap-2">
                <Mono aria-hidden className="shrink-0 text-12 text-ink-3">
                  ·
                </Mono>
                <span className="min-w-0 break-words text-12 leading-[1.5] text-ink-3">
                  {line}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

/**
 * How many paths a finding lists before it folds. A finding about one page names one or two;
 * a finding about a whole CLASS of fault names a hundred, and a hundred mono paths is the
 * whole page. Twelve is about a line and a half at reading width, which is enough to tell
 * what KIND of page this is about; the count itself is already in the evidence.
 */
const PATH_CAP = 12;

/**
 * The pages a finding also touches: the first `PATH_CAP` as rows, the rest behind one word.
 *
 * Expanding is local state and nothing else — every path is already in hand, so the fold is
 * about the page's proportions and never about a second read. It folds back, because a
 * finding that lists 240 subjects would otherwise push everything after it off the screen for
 * the rest of the session.
 */
function PathList({
  label,
  paths,
  onOpen,
}: {
  label: string;
  paths: string[];
  onOpen: ((path: string) => void) | null;
}) {
  const t = useT();
  const [all, setAll] = useState(false);
  const shown = all ? paths : paths.slice(0, PATH_CAP);
  const hidden = paths.length - shown.length;

  return (
    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="shrink-0 text-12 text-ink-3">{label}</span>
      {shown.map((path) =>
        onOpen ? (
          <button
            key={path}
            type="button"
            title={t("review.openDocument")}
            onClick={() => onOpen(path)}
            className="inline-flex max-w-full items-baseline gap-1 rounded-1 text-accent transition-colors duration-120 hover:text-ink"
          >
            <Mono className="truncate text-12">{path}</Mono>
            <ArrowUpRight size={11} aria-hidden className="shrink-0 translate-y-px" />
          </button>
        ) : (
          <Mono key={path} className="max-w-full truncate text-12 text-ink-2">
            {path}
          </Mono>
        ),
      )}
      {(hidden > 0 || all) && (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="shrink-0 rounded-1 text-12 text-ink-3 underline-offset-2 transition-colors duration-120 hover:text-ink hover:underline"
        >
          {all ? t("review.pages.fewer") : t("review.pages.more", { count: hidden })}
        </button>
      )}
    </p>
  );
}

import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { useApp } from "@/lib/store";
import { fmtDay } from "@/lib/format";
import { useLocale, useT, useTOr } from "@/lib/useT";
import type { Locale } from "@/lib/i18n";
import type { LensFinding, LensText } from "@/lib/lensReport";
import { Badge } from "@/ui/Badge";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * A catalog sentence, in the reader's language.
 *
 * The report carries each sentence already rendered in both packs (`text.en` / `text.zh`,
 * docs/design/structure-lens.md §3.2), and the console keeps NO copy of them. That is the
 * point rather than an economy: one catalog, one wording, every face — the sentence the
 * Owner reads here is byte for byte the sentence `pkc lens` prints, and an application that
 * rewords a key through the overlay seam changes both without touching this build.
 *
 * Two fallbacks, in order, so a report from an older or degraded service never renders a
 * blank line: the other language, then the key with its fields spelled out.
 */
export function catalogText(locale: Locale, sentence: LensText): string {
  const { en, zh } = sentence.text;
  const mine = locale === "zh" ? zh : en;
  const other = locale === "zh" ? en : zh;
  if (mine) return mine;
  if (other) return other;
  if (!sentence.key) return "";
  const fields = Object.entries(sentence.fields)
    .map(([name, value]) => `${name}=${value}`)
    .join(" · ");
  return fields ? `${sentence.key} · ${fields}` : sentence.key;
}

export interface FindingRowProps {
  finding: LensFinding;
  /** 1-based position, shown only where the order is the point (the headline). */
  rank?: number;
  /** The headline states its findings at reading size; a group list states them at body size. */
  emphasis?: boolean;
}

/**
 * One finding, in the shape §3 gives it: the sentence, what to do, who it is addressed to,
 * the pages it is about, and the evidence underneath.
 *
 * The sentence leads and the machine text recedes. That order is the whole difference between
 * this and the surface it replaces: a count of dead ends told a reader nothing they could act
 * on, and the paths and evidence — which are the parts a maintainer eventually needs — are
 * worth nothing until they know why they are looking at them.
 */
export function FindingRow({ finding, rank, emphasis = false }: FindingRowProps) {
  const t = useT();
  const tOr = useTOr();
  const locale = useLocale();
  const jump = useApp((s) => s.jump);

  const impact = catalogText(locale, finding.impact);
  const action = catalogText(locale, finding.action);
  const actor = tOr(`lens.actor.${finding.actor}`, finding.actor);

  return (
    <li className="border-b border-line last:border-b-0">
      <div className="flex items-start gap-3 py-3">
        {rank != null && (
          <Mono className="mt-1.5 shrink-0 text-12 text-ink-3">
            {String(rank).padStart(2, "0")}
          </Mono>
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <p
            className={cn(
              "max-w-measure text-balance text-ink",
              emphasis ? "font-serif text-20 leading-[1.35]" : "text-14 leading-[1.5]",
            )}
          >
            {impact}
          </p>

          {action && (
            <p className="flex items-baseline gap-2 text-13 text-ink-2">
              <Mono aria-hidden className="shrink-0 text-12 text-ink-3">
                →
              </Mono>
              {/* The actor flows INSIDE the sentence's block rather than beside it: as a
                  sibling of the arrow it wrapped to a line of its own on a narrow screen,
                  and an arrow alone on a line points at nothing. */}
              <span className="min-w-0 max-w-measure">
                {action}{" "}
                <Badge className="ml-0.5 translate-y-px">
                  {/* Visually the word; to a screen reader the whole relation, because a bare
                      "Steward" beside a sentence does not say what it is doing there. */}
                  <span className="sr-only">{t("lens.actor.aria", { actor })}</span>
                  <span aria-hidden>{actor}</span>
                </Badge>
              </span>
            </p>
          )}

          {finding.paths.length > 0 && (
            <PathList
              label={t("lens.pages.label")}
              paths={finding.paths}
              onOpen={(path) => jump({ kind: "document", id: path }, "library")}
            />
          )}

          {finding.targets.length > 0 && (
            /* Not links: a target may be exactly the path that has no document. */
            <PathList label={t("lens.targets.label")} paths={finding.targets} onOpen={null} />
          )}

          {finding.evidence.length > 0 && (
            <ul className="flex flex-col gap-0.5" aria-label={t("lens.evidence.label")}>
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

          {/* Reserved (§9): no console act records a decline yet, so this branch is defensive
              — a report from a build that does record one still renders it. */}
          {finding.decision && (
            <p className="text-12 text-ink-3">
              {t("lens.decision", {
                reason: finding.decision.reason,
                date: fmtDay(finding.decision.decided_at.slice(0, 10)),
              })}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

/**
 * How many paths a finding lists before it folds. A lens that reports one finding per fault
 * names one or two pages; a lens that reports one finding for a whole CLASS of fault — every
 * dead end in the library, as one row — names a hundred, and a hundred mono paths is the
 * whole page. Twelve is about a line and a half at reading width, which is enough to tell
 * what KIND of page this is about; the count itself is already in the evidence.
 */
const PATH_CAP = 12;

/**
 * The pages a finding is about: the first `PATH_CAP` as rows, the rest behind one word.
 *
 * Expanding is local state and nothing else — every path is already in hand, so the fold is
 * about the page's proportions and never about a second read. It folds back, because a
 * finding that lists 240 subjects would otherwise push everything after it off the screen
 * for the rest of the session.
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
            title={t("lens.openDocument")}
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
          {all ? t("lens.pages.fewer") : t("lens.pages.more", { count: hidden })}
        </button>
      )}
    </p>
  );
}

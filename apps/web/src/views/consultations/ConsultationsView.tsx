import { useCallback, useEffect, useRef, useState } from "react";
import { MessageCircleQuestion, UserRound, X } from "lucide-react";
import {
  getConsultation,
  listConsultations,
  type Consultation,
  type ConsultationParams,
  type ConsultationSummary,
} from "@/lib/api";
import { addressLabel, citedFirst, evidenceRows } from "@/lib/consultations";
import { fmtTime } from "@/lib/format";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { UsageLine } from "@/views/_shared/UsageLine";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";
import { UsagePanel } from "./UsagePanel";
import {
  createQueryOwner,
  loadFirstPage,
  loadNextPage,
  type ListSink,
} from "./listLoading";

const PAGE = 25;
/** Select / RadioGroup take no empty-string item; this sentinel maps back to "no filter". */
const ANY = "__any__";

/**
 * The audit chain, made readable: every answer this library gave, and — for one of them —
 * the question, the library it was asked of, every address the lane put in front of the
 * model, and which of those the answer went on to cite.
 *
 * The page is a LEDGER, not a debug dump. What a reader comes here to settle is "on what did
 * this answer rest", so the manifest is one list with the citations marked inside it rather
 * than two lists that repeat most of their rows, and every address is a link back into the
 * thing it addresses — a claim to its page, a span to the source galley.
 *
 * Above it, the ledger these records feed: what has been read, and what went unanswered. It
 * is the same substrate seen from the other end, which is why it lives here rather than on
 * an overview page that would have to explain where its numbers came from.
 */
export default function ConsultationsView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const target = useApp((s) => s.consultationTarget);
  const setTarget = useCallback(
    (next: string | null) => useApp.setState({ consultationTarget: next }),
    [],
  );
  const [lane, setLane] = useState<string>(ANY);
  const [visitorClass, setVisitorClass] = useState<string>(ANY);
  const [miss, setMiss] = useState<string>(ANY);

  const [items, setItems] = useState<ConsultationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const filtered = lane !== ANY || visitorClass !== ANY || miss !== ANY || target != null;

  // Who owns the list. A response that comes back after the user or the filters moved on
  // writes nothing — see listLoading.ts; without it, switching library mid-request renders
  // the previous tenant's questions under the new library's name.
  const owner = useRef(createQueryOwner());

  const query = useCallback(
    (cursor: string | null): ConsultationParams => ({
      limit: PAGE,
      ...(cursor ? { cursor } : {}),
      lane: lane === ANY ? null : lane,
      visitor_class: visitorClass === ANY ? null : visitorClass,
      miss: miss === ANY ? null : miss === "miss",
      target,
    }),
    [lane, visitorClass, miss, target],
  );

  const sink: ListSink = {
    setLoading,
    setError,
    replace: (next, count, cursor) => {
      setItems(next);
      setTotal(count);
      setNextCursor(cursor);
      setSelected(next[0]?.consultation_id ?? null);
    },
    append: (next, cursor) => {
      setItems((prior) => [...prior, ...next]);
      setNextCursor(cursor);
    },
  };

  const load = useCallback(async () => {
    if (!currentUser) return;
    await loadFirstPage(
      owner.current,
      (params) => listConsultations(currentUser, params),
      query(null),
      sink,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `sink` is rebuilt each render
    // and holds only setters, which are stable; the query's identity is what must be tracked.
  }, [currentUser, query]);

  useEffect(() => {
    void load();
  }, [load]);

  async function loadMore() {
    // While the first page is still in flight the cursor on screen belongs to the previous
    // query, so appending from it would extend a list that is about to be replaced.
    if (!currentUser || !nextCursor || loading) return;
    await loadNextPage(
      owner.current,
      (params) => listConsultations(currentUser, params),
      query(nextCursor),
      sink,
    );
  }

  function clearFilters() {
    setLane(ANY);
    setVisitorClass(ANY);
    setMiss(ANY);
    setTarget(null);
  }

  if (!currentUser) {
    return (
      <>
        <PageHeader
          title={t("consultations.title")}
          description={t("consultations.description")}
        />
        <EmptyState
          icon={UserRound}
          title={t("consultations.noUser.title")}
          description={t("consultations.noUser.description")}
        />
      </>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        className="shrink-0"
        title={t("consultations.title")}
        description={t("consultations.description")}
      />

      <div className="shrink-0">
        <UsagePanel userId={currentUser} />
      </div>

      <div className="shrink-0 flex flex-col gap-2">
        <SectionRule no={2} title={t("consultations.ledger")} />
        <div className="flex flex-wrap items-end gap-2">
          <Select
            wrapperClassName="min-w-36"
            label={t("consultations.filter.lane")}
            value={lane}
            onChange={setLane}
            options={[
              { value: ANY, label: t("consultations.filter.all") },
              { value: "fast", label: t("consultations.lane.fast") },
              { value: "deep", label: t("consultations.lane.deep") },
              { value: "briefing_ask", label: t("consultations.lane.briefing_ask") },
            ]}
          />
          <Select
            wrapperClassName="min-w-40"
            label={t("consultations.filter.visitorClass")}
            value={visitorClass}
            onChange={setVisitorClass}
            options={[
              { value: ANY, label: t("consultations.filter.all") },
              { value: "business", label: t("visitor.business") },
              { value: "audit", label: t("visitor.audit") },
            ]}
          />
          <Select
            wrapperClassName="min-w-36"
            label={t("consultations.filter.miss")}
            value={miss}
            onChange={setMiss}
            options={[
              { value: ANY, label: t("consultations.filter.all") },
              { value: "miss", label: t("consultations.filter.missOnly") },
              { value: "answered", label: t("consultations.filter.answeredOnly") },
            ]}
          />
          {target && (
            <div className="flex min-w-0 items-center gap-1.5 pb-1.5">
              <span className="text-12 text-ink-3">
                {t("consultations.filter.target")}
              </span>
              <Mono className="min-w-0 max-w-64 truncate text-12" title={target}>
                {target}
              </Mono>
              <button
                type="button"
                aria-label={t("consultations.filter.targetClear")}
                onClick={() => setTarget(null)}
                className="rounded-1 p-0.5 text-ink-3 transition-colors duration-120 hover:bg-hover hover:text-ink"
              >
                <X size={14} aria-hidden />
              </button>
            </div>
          )}
          <p className="pb-2 text-12 text-ink-3">
            {t("consultations.total", { count: total })}
          </p>
        </div>
        {/* The three classes are met here as DATA, so this is where what they cost is
            worth saying — and why one of them can never appear in this list. */}
        <p className="max-w-measure text-12 leading-relaxed text-ink-3">
          {t("visitor.note")}
        </p>
      </div>

      {error ? (
        <ErrorState
          title={t("consultations.error.title")}
          error={error}
          onRetry={() => void load()}
        />
      ) : loading ? (
        <SkeletonText lines={8} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={MessageCircleQuestion}
          title={t(
            filtered ? "consultations.emptyFiltered.title" : "consultations.empty.title",
          )}
          description={t(
            filtered
              ? "consultations.emptyFiltered.description"
              : "consultations.empty.description",
          )}
          action={
            filtered ? (
              <Button size="sm" variant="ghost" onClick={clearFilters}>
                {t("consultations.filter.clear")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-6 lg:flex-row">
          <ScrollRegion
            as="nav"
            aria-label={t("consultations.title")}
            className="min-h-0 lg:w-96 lg:shrink-0 lg:flex-1"
          >
            <ul className="flex flex-col">
              {items.map((item) => (
                <li key={item.consultation_id}>
                  <ConsultationRow
                    item={item}
                    active={item.consultation_id === selected}
                    onSelect={() => setSelected(item.consultation_id)}
                  />
                </li>
              ))}
            </ul>
            {nextCursor && (
              <div className="py-3">
                <Button size="sm" variant="ghost" onClick={() => void loadMore()}>
                  {t("consultations.loadMore")}
                </Button>
              </div>
            )}
          </ScrollRegion>
          <ScrollRegion className="min-h-0 lg:flex-[1.4]">
            {selected ? (
              <ConsultationDetail userId={currentUser} consultationId={selected} />
            ) : (
              <p className="text-13 text-ink-3">{t("consultations.detail.select")}</p>
            )}
          </ScrollRegion>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- the listing row */

function ConsultationRow({
  item,
  active,
  onSelect,
}: {
  item: ConsultationSummary;
  active: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  return (
    <button
      type="button"
      aria-current={active ? "true" : undefined}
      onClick={onSelect}
      className={cn(
        "flex w-full min-w-0 flex-col gap-1 border-b border-line px-2 py-2.5 text-left",
        "transition-colors duration-120 ease-out",
        active ? "bg-accent-soft" : "hover:bg-hover",
      )}
    >
      <span className="min-w-0 text-13 leading-relaxed text-ink">{item.question}</span>
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <Badge>{item.lane}</Badge>
        <Badge tone={item.visitor_class === "business" ? "accent" : "neutral"}>
          {item.visitor_class}
        </Badge>
        {item.miss && <Badge tone="warn">{t("consultations.miss.badge")}</Badge>}
        <Mono className="text-12 text-ink-3">{fmtTime(item.created_at)}</Mono>
        <Mono className="text-12 text-ink-3">
          {t("consultations.detail.cited")} {item.citation_count}/{item.evidence_count}
        </Mono>
      </span>
    </button>
  );
}

/* ------------------------------------------------------------------------ the record */

function ConsultationDetail({
  userId,
  consultationId,
}: {
  userId: string;
  consultationId: string;
}) {
  const t = useT();
  const jump = useApp((s) => s.jump);
  const focusSource = useApp((s) => s.focusSource);
  const [record, setRecord] = useState<Consultation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setRecord(null);
    setError(null);
    getConsultation(userId, consultationId)
      .then((next) => {
        if (alive) setRecord(next);
      })
      .catch((e: Error) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [userId, consultationId]);

  if (error) {
    return <ErrorState title={t("consultations.detail.error")} error={error} />;
  }
  if (!record) return <SkeletonText lines={6} />;

  const rows = citedFirst(evidenceRows(record.evidence_handed, record.citations));

  return (
    <article className="flex flex-col gap-5">
      <header className="flex flex-col gap-2">
        <p className="text-12 text-ink-3">{t("consultations.detail.question")}</p>
        <h3 className="max-w-measure font-serif text-20 leading-snug text-ink">
          {record.question}
        </h3>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-12 text-ink-3">
          <Badge>{record.lane}</Badge>
          <Badge tone={record.visitor_class === "business" ? "accent" : "neutral"}>
            {record.visitor_class}
          </Badge>
          {record.miss && <Badge tone="warn">{t("consultations.miss.badge")}</Badge>}
          {record.answer_kind && <Mono className="text-12">{record.answer_kind}</Mono>}
          <span>
            {t("consultations.detail.libraryRef")}{" "}
            <Mono className="text-12">{record.library_ref || "—"}</Mono>
          </span>
          {record.as_of && (
            <span>
              {t("consultations.detail.asOf")} {fmtTime(record.as_of)}
            </span>
          )}
        </div>
        {record.degraded.length > 0 && (
          <p className="text-12 text-warn">
            {t("consultations.detail.degraded")}{" "}
            {record.degraded.map((pair) => pair.join(" · ")).join("  ·  ")}
          </p>
        )}
        {/* What this one answer spent, in the app's one token ledger — and what it cost,
            where the deployment declared a price for the model that answered. */}
        <UsageLine usage={record.token_usage} cost={record.cost} />
      </header>

      <section>
        <p className="text-12 text-ink-3">{t("consultations.detail.answer")}</p>
        <p className="mt-1 max-w-measure text-14 leading-relaxed whitespace-pre-wrap text-ink">
          {record.answer || t("consultations.detail.noAnswer")}
        </p>
      </section>

      <section>
        <p className="text-12 text-ink-3">{t("consultations.detail.evidence")}</p>
        {rows.length === 0 ? (
          <p className="mt-1 text-13 text-ink-3">{t("consultations.detail.noEvidence")}</p>
        ) : (
          <>
            <ul className="mt-1 flex flex-col">
              {rows.map((row) => {
                const label = addressLabel(row.parsed);
                const open = () => {
                  if (row.parsed.shape === "span") {
                    focusSource(row.parsed.sourceId, {
                      start: row.parsed.start,
                      end: row.parsed.end,
                    });
                  } else if (row.parsed.shape === "claim" && row.parsed.path) {
                    jump({ kind: "document", id: row.parsed.path }, "library");
                  } else if (row.parsed.shape === "document" && row.parsed.path) {
                    jump({ kind: "document", id: row.parsed.path }, "library");
                  }
                };
                const reachable =
                  row.parsed.shape === "span" ||
                  (row.parsed.shape === "claim" && !!row.parsed.path) ||
                  (row.parsed.shape === "document" && !!row.parsed.path);
                return (
                  <li
                    key={`${row.ref} ${row.path}`}
                    className="flex min-w-0 items-baseline gap-2 border-b border-line py-1.5 last:border-b-0"
                  >
                    <Badge tone={row.cited ? "accent" : "neutral"}>
                      {row.cited
                        ? t("consultations.detail.cited")
                        : t("consultations.detail.handedOnly")}
                    </Badge>
                    {reachable ? (
                      <button
                        type="button"
                        onClick={open}
                        title={
                          row.parsed.shape === "span"
                            ? t("consultations.detail.openSpan")
                            : t("consultations.detail.openDocument")
                        }
                        className="min-w-0 flex-1 truncate text-left text-13 text-accent transition-colors duration-120 hover:underline"
                      >
                        {label}
                      </button>
                    ) : (
                      <span className="min-w-0 flex-1 truncate text-13 text-ink-2">
                        {label}
                      </span>
                    )}
                    {row.parsed.shape === "claim" && row.parsed.path && (
                      <Mono
                        className="hidden max-w-56 shrink-0 truncate text-12 text-ink-3 sm:block"
                        title={row.parsed.path}
                      >
                        {row.parsed.path}
                      </Mono>
                    )}
                    <Mono className="shrink-0 text-12 text-ink-3">{row.kind}</Mono>
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-12 leading-relaxed text-ink-3">
              {t("consultations.detail.evidenceNote")}
            </p>
          </>
        )}
      </section>
    </article>
  );
}

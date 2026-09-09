import type { ReactNode } from "react";
import { HardDrive } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { EngineDot } from "@/components/LibraryPicker";
import { fmtDateTime } from "@/lib/format";
import {
  HOME_SERVICES,
  HOME_STEPS,
  formatUptime,
  stepsDone,
  type HomeLibrary,
  type HomeService,
  type HomeStatus,
} from "@/lib/home";
import { useHome } from "@/lib/useHome";
import { useT, type TFunction } from "@/lib/useT";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * The machine, at a glance: Docker, the four services it runs once, and every library on it
 * with the state of its engine, its queue and its cold start.
 *
 * Read-only, and deliberately so for now. Every action this page will grow — start an
 * engine, set a key, re-render a skill — is a `pkchome` verb behind `/home/actions/*`, and a
 * health page that reported a state it could not change is honest; one that offered buttons
 * over an endpoint that does not exist yet would not be.
 *
 * No cards and no number wall (DESIGN.md §6.5): each library is a hairline-separated block
 * whose facts read as a line of prose-shaped labels, which is how the rest of this console
 * states real state.
 */
export default function HomeView() {
  const t = useT();
  const home = useHome();

  return (
    <div className="flex flex-col gap-8">
      <PageHeader title={t("home.title")} description={t("home.description")} />
      {home ? <HomeBody home={home} t={t} /> : <HomeAbsent t={t} />}
    </div>
  );
}

/**
 * The route exists on every deployment (it is a `ViewName`, so a link to it always
 * resolves); the contents rail only offers it where a home answered. Someone who typed the
 * hash on a project deployment gets told what this page is for, not a blank.
 */
function HomeAbsent({ t }: { t: TFunction }) {
  return <EmptyState icon={HardDrive} title={t("home.title")} description={t("home.absent")} />;
}

function HomeBody({ home, t }: { home: HomeStatus; t: TFunction }) {
  return (
    <>
      <section className="flex flex-col gap-4">
        <Heading title={t("home.section.machine")} />
        <dl className="flex flex-col">
          <Row
            term={t("home.docker")}
            definition={
              <StateWord
                tone={home.docker == null ? "unknown" : home.docker.reachable ? "ok" : "bad"}
                text={t(
                  home.docker == null
                    ? "home.docker.unknown"
                    : home.docker.reachable
                      ? "home.docker.reachable"
                      : "home.docker.unreachable",
                )}
              />
            }
          />
          {HOME_SERVICES.map((name) => (
            <Row
              key={name}
              term={t(`home.service.${name}` as const)}
              definition={<ServiceLine service={home.services[name]} t={t} />}
            />
          ))}
        </dl>
        {home.home != null && (
          <p className="text-13 text-ink-3">
            {t("home.path")} <Mono className="text-ink-2">{home.home.path}</Mono>
            <span aria-hidden> · </span>
            {t("home.version")} <Mono className="text-ink-2">{home.home.version}</Mono>
          </p>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <Heading title={t("home.section.libraries")} />
        {home.libraries.length === 0 ? (
          <p className="text-14 text-ink-2">{t("home.library.none")}</p>
        ) : (
          <div className="flex flex-col">
            {home.libraries.map((library, i) => (
              <LibraryBlock key={library.name} library={library} first={i === 0} t={t} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

/* ------------------------------------------------------------------------ pieces */

/**
 * A section head WITHOUT a § number: `SectionRule` numbers the book's chapters, and the
 * machine is not one of them — printing 「§」 over it would file the install as a chapter of
 * the library it happens to hold.
 */
function Heading({ title }: { title: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <h2 className="shrink-0 font-serif text-20 text-ink">{title}</h2>
      <hr aria-hidden className="min-w-8 flex-1 border-0 border-t border-line" />
    </div>
  );
}

function Row({ term, definition }: { term: string; definition: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-t border-line py-2 first:border-t-0 sm:flex-row sm:items-baseline sm:gap-4">
      <dt className="shrink-0 text-13 font-medium text-ink sm:w-36">{term}</dt>
      <dd className="min-w-0 text-13 text-ink-2">{definition}</dd>
    </div>
  );
}

/** A real state, in a word and a semantic colour — never a bare lamp. */
function StateWord({ tone, text }: { tone: "ok" | "bad" | "unknown"; text: string }) {
  return (
    <span
      className={cn(
        tone === "ok" ? "text-ok" : tone === "bad" ? "text-danger" : "text-ink-3",
      )}
    >
      {text}
    </span>
  );
}

function ServiceLine({ service, t }: { service: HomeService | null; t: TFunction }) {
  if (service == null) return <StateWord tone="unknown" text={t("home.service.unknown")} />;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-2">
      <StateWord
        tone={service.up ? "ok" : "bad"}
        text={t(service.up ? "home.service.up" : "home.service.down")}
      />
      {service.port != null && (
        <Mono className="text-12 text-ink-3">
          {t("home.port")} {service.port}
        </Mono>
      )}
    </span>
  );
}

function LibraryBlock({
  library,
  first,
  t,
}: {
  library: HomeLibrary;
  first: boolean;
  t: TFunction;
}) {
  const { engine, queue, steps } = library;
  return (
    <div className={cn("py-5", !first && "border-t border-line")}>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <EngineDot up={engine.up} className="translate-y-[-1px]" />
        <h3 className="font-serif text-16 text-ink">{library.name}</h3>
        <Mono className="text-12 text-ink-3">{library.tenant}</Mono>
        {library.current && <span className="text-12 text-accent">{t("home.library.current")}</span>}
      </div>

      <p className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-13 text-ink-2">
        <StateWord
          tone={engine.up ? "ok" : "bad"}
          text={t(engine.up ? "home.library.engineUp" : "home.library.engineDown")}
        />
        {engine.port != null && (
          <Mono className="text-12 text-ink-3">
            {t("home.port")} {engine.port}
          </Mono>
        )}
        {engine.pid != null && (
          <Mono className="text-12 text-ink-3">
            {t("home.pid")} {engine.pid}
          </Mono>
        )}
        {engine.up && engine.uptime != null && (
          <Mono className="text-12 text-ink-3">
            {t("home.library.uptime")} {formatUptime(engine.uptime)}
          </Mono>
        )}
      </p>

      <dl className="flex flex-col">
        <Row
          term={t("home.library.queue")}
          definition={
            queue == null ? (
              <StateWord tone="unknown" text={t("home.library.queueUnknown")} />
            ) : (
              <span className="inline-flex flex-wrap items-baseline gap-2">
                {queue.succeeded != null && queue.succeeded > 0 && (
                  <span className="text-ok">
                    {t("home.library.queueSucceeded", { succeeded: queue.succeeded })}
                  </span>
                )}
                <span>
                  {queue.pending === 0 && queue.failed === 0
                    ? t("home.library.queueClear")
                    : t("home.library.queuePending", { pending: queue.pending })}
                </span>
                {queue.failed > 0 && (
                  <span className="text-danger">
                    {Object.keys(queue.failed_by_kind).length > 0
                      ? t("home.library.queueFailedByKind", {
                          failed: queue.failed,
                          kinds: Object.entries(queue.failed_by_kind)
                            .map(([kind, n]) => `${kind} ${n}`)
                            .join(", "),
                        })
                      : t("home.library.queueFailed", { failed: queue.failed })}
                  </span>
                )}
              </span>
            )
          }
        />
        <Row
          term={t("home.library.lastCompile")}
          definition={queue?.last_compile_at ? fmtDateTime(queue.last_compile_at) : "—"}
        />
        <Row
          term={t("home.library.key")}
          definition={
            <span className="flex flex-col gap-0.5">
              <StateWord
                tone={library.key ? "ok" : "bad"}
                text={t(library.key ? "home.library.keyPresent" : "home.library.keyMissing")}
              />
              {/* What a missing key actually costs, said where the key is: not the library,
                  only the console's three model-lane pages, which are quality tools. */}
              {!library.key && (
                <span className="text-12 text-ink-3">{t("home.library.keyModelLanes")}</span>
              )}
            </span>
          }
        />
        <Row
          term={t("home.library.skill")}
          definition={
            <StateWord
              tone={
                library.skill_fresh == null ? "unknown" : library.skill_fresh ? "ok" : "bad"
              }
              text={t(
                library.skill_fresh == null
                  ? "home.library.skillUnknown"
                  : library.skill_fresh
                    ? "home.library.skillFresh"
                    : "home.library.skillStale",
              )}
            />
          }
        />
        <Row
          term={t("home.library.steps")}
          definition={
            <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Mono className="text-12 text-ink-3">
                {t("home.library.stepsDone", {
                  done: stepsDone(steps),
                  total: HOME_STEPS.length,
                })}
              </Mono>
              {HOME_STEPS.map((step) => (
                <span
                  key={step}
                  title={steps[step] ?? t("home.step.pending")}
                  className={cn("text-12", steps[step] != null ? "text-ok" : "text-ink-3 line-through")}
                >
                  {t(`home.step.${step}` as const)}
                </span>
              ))}
            </span>
          }
        />
        <Row
          term={t("home.library.canonical")}
          definition={
            library.canonical_head ? <Mono>{library.canonical_head}</Mono> : "—"
          }
        />
        <Row
          term={t("home.library.engineDir")}
          definition={library.engine_dir ? <Mono>{library.engine_dir}</Mono> : "—"}
        />
        <Row
          term={t("home.library.lastUsed")}
          definition={library.last_used ? fmtDateTime(library.last_used) : "—"}
        />
      </dl>
    </div>
  );
}

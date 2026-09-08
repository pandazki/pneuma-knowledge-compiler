/**
 * The personal edition's home, as this console sees it.
 *
 * A project deployment has no home: `GET /home/status` answers 404 and everything below
 * stays unused, which is the whole point — the console renders as it always did. A personal
 * edition's engine (docs/design/single-machine-edition.md §4.12, §10) answers it with the
 * same document `pkchome status --json` prints, and the console gains exactly two things
 * from it: a library switcher by NAME instead of a raw tenant id, and a health page.
 *
 * This module is pure — types, one tolerant parser, and the small derivations the switcher
 * and the health page need. It touches no network and no store, so the parser can be tested
 * on its own, and a shape the edition grows later degrades to "unknown field ignored"
 * rather than to a blank console: every section is optional, every unknown key is dropped,
 * and only `libraries` being an array decides that this IS a status document at all. A 404
 * body (`{"detail": "Not Found"}`) therefore parses to null exactly as a network failure
 * does, and the caller has one absence to handle instead of two.
 */

/** The four services one machine runs once, in the order the health page lists them. */
export const HOME_SERVICES = ["postgres", "qdrant", "meili", "rustfs"] as const;
export type HomeServiceName = (typeof HOME_SERVICES)[number];

/** The cold start, as `library.yaml` records it — one stamp written by the command that
 *  did the work, in the order the work happens. */
export const HOME_STEPS = ["infra", "credentials", "profile", "skill", "first_compile"] as const;
export type HomeStepName = (typeof HOME_STEPS)[number];

export interface HomeInfo {
  path: string;
  version: string;
}

export interface HomeDocker {
  reachable: boolean;
}

export interface HomeService {
  port: number | null;
  up: boolean;
}

export interface HomeEngine {
  pid: number | null;
  up: boolean;
  port: number | null;
  /** Seconds since the engine process started. */
  uptime: number | null;
}

export interface HomeQueue {
  pending: number;
  failed: number;
  /** failures counted by job kind — forty failed evolve jobs beside fifty-nine good
   *  compiles must read as what they are; absent from an older engine. */
  failed_by_kind: Record<string, number>;
  /** every job that completed well, of any kind; null when the engine did not say. */
  succeeded: number | null;
  last_compile_at: string | null;
}

export type HomeSteps = Record<HomeStepName, string | null>;

export interface HomeLibrary {
  name: string;
  tenant: string;
  /** The library the engine that served this console is serving. */
  current: boolean;
  engine: HomeEngine;
  /** null when the engine is down and nobody could read its queue. */
  queue: HomeQueue | null;
  key: boolean;
  engine_dir: string | null;
  canonical_head: string | null;
  /** null when freshness could not be decided (no rendered package to compare). */
  skill_fresh: boolean | null;
  steps: HomeSteps;
  last_used: string | null;
}

export interface HomeStatus {
  home: HomeInfo | null;
  docker: HomeDocker | null;
  services: Record<HomeServiceName, HomeService | null>;
  libraries: HomeLibrary[];
}

/* ------------------------------------------------------------------ tolerant readers */

function obj(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function bool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function parseService(value: unknown): HomeService | null {
  const raw = obj(value);
  if (!raw) return null;
  return { port: num(raw.port), up: bool(raw.up) ?? false };
}

function parseEngine(value: unknown): HomeEngine {
  const raw = obj(value);
  if (!raw) return { pid: null, up: false, port: null, uptime: null };
  return {
    pid: num(raw.pid),
    up: bool(raw.up) ?? false,
    port: num(raw.port),
    uptime: num(raw.uptime),
  };
}

function parseQueue(value: unknown): HomeQueue | null {
  const raw = obj(value);
  if (!raw) return null;
  const byKind: Record<string, number> = {};
  const rawKinds = obj(raw.failed_by_kind) ?? {};
  for (const [kind, count] of Object.entries(rawKinds)) {
    const n = num(count);
    if (n != null && n > 0) byKind[kind] = n;
  }
  return {
    pending: num(raw.pending) ?? 0,
    failed: num(raw.failed) ?? 0,
    failed_by_kind: byKind,
    succeeded: num(raw.succeeded),
    last_compile_at: str(raw.last_compile_at),
  };
}

function parseSteps(value: unknown): HomeSteps {
  const raw = obj(value) ?? {};
  const steps = {} as HomeSteps;
  // A recorded step is an ISO timestamp; a derived one (profile) may be a bare `true`
  // (design §5: derived at read time, not written). Both mean done; null means not observed.
  for (const step of HOME_STEPS) {
    const v = raw[step];
    steps[step] = v === true ? "done" : str(v);
  }
  return steps;
}

/**
 * One library. A row with no name or no tenant is DROPPED rather than repaired: the name is
 * what the switcher shows and the tenant is what the console would then read, and inventing
 * either would put a library on screen that no request could reach.
 */
function parseLibrary(value: unknown): HomeLibrary | null {
  const raw = obj(value);
  if (!raw) return null;
  const name = str(raw.name);
  const tenant = str(raw.tenant);
  if (!name || !tenant) return null;
  return {
    name,
    tenant,
    current: bool(raw.current) ?? false,
    engine: parseEngine(raw.engine),
    queue: parseQueue(raw.queue),
    key: bool(raw.key) ?? false,
    engine_dir: str(raw.engine_dir),
    canonical_head: str(raw.canonical_head),
    skill_fresh: bool(raw.skill_fresh),
    steps: parseSteps(raw.steps),
    last_used: str(raw.last_used),
  };
}

/** The status document, or null for anything that is not one (a 404 body included). */
export function parseHomeStatus(input: unknown): HomeStatus | null {
  const raw = obj(input);
  if (!raw || !Array.isArray(raw.libraries)) return null;

  const home = obj(raw.home);
  const docker = obj(raw.docker);
  const services = obj(raw.services) ?? {};
  const parsedServices = {} as Record<HomeServiceName, HomeService | null>;
  for (const service of HOME_SERVICES) parsedServices[service] = parseService(services[service]);

  return {
    home: home ? { path: str(home.path) ?? "", version: str(home.version) ?? "" } : null,
    docker: docker ? { reachable: bool(docker.reachable) ?? false } : null,
    services: parsedServices,
    libraries: raw.libraries
      .map(parseLibrary)
      .filter((library): library is HomeLibrary => library !== null),
  };
}

/** `GET /home/libraries` answers the array alone; the same rows, the same tolerance. */
export function parseHomeLibraries(input: unknown): HomeLibrary[] | null {
  if (!Array.isArray(input)) return null;
  return input.map(parseLibrary).filter((library): library is HomeLibrary => library !== null);
}

/* ------------------------------------------------------------------- derivations */

/** The library this engine serves — the one the console's tenant must follow. */
export function currentLibrary(status: HomeStatus | null): HomeLibrary | null {
  return status?.libraries.find((library) => library.current) ?? null;
}

/**
 * Where another library's console lives. Each library's engine serves this same console at
 * its own port on this same host (§4.10), so switching is a NAVIGATION, not a request: same
 * scheme, same hostname, its port, and the hash route carried across so the switch lands on
 * the page you were already reading.
 */
export function libraryHref(
  library: HomeLibrary,
  location: { protocol: string; hostname: string },
  hash = "",
): string | null {
  const port = library.engine.port;
  if (port == null) return null;
  const route = hash && hash !== "#" ? (hash.startsWith("#") ? hash : `#${hash}`) : "";
  return `${location.protocol}//${location.hostname}:${port}/${route}`;
}

/** How much of the five-step cold start this library has behind it. */
export function stepsDone(steps: HomeSteps): number {
  return HOME_STEPS.filter((step) => steps[step] != null).length;
}

/**
 * Seconds as a coarse, language-neutral duration ("45s", "12m", "3h 12m", "2d 4h"). Coarse
 * on purpose: uptime is read to answer "has it been up a while", and a second-accurate
 * figure that changes on every poll answers a question nobody asked.
 */
export function formatUptime(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 0 ? `${minutes}m` : `${hours}h ${minutes % 60}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

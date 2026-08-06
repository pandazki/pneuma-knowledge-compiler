/**
 * Engine Console API client. One flag — USE_FIXTURES — switches between the mock fixtures
 * and the real `/v1/engine/*` routes, whose shapes are frozen in
 * docs/design/engine-console.md. Both sides speak the same types: every consumer imports
 * these typed functions and nothing else, which is why the real backend plugged in without
 * a single UI change.
 *
 * Fixture mode keeps a mutable in-memory copy of the fixtures: reads return deep copies,
 * `applyChanges` writes the changes into the copy, mints a fake sha, prepends a history
 * entry, and re-derives resolved values — so the whole draft → review → apply → timeline
 * loop round-trips with no service.
 */
import { ApiError } from "@/lib/api";
import { tx } from "@/lib/i18n";
import { parseYamlScalar } from "@/lib/engineConsole";
import { getOverlayMap, getYamlScalar } from "@/lib/engineYaml";
import type {
  EngineApplyChange,
  EngineApplyResult,
  EngineFile,
  EngineHistoryEntry,
  EngineHistoryFiles,
  EnginePrompts,
  EngineSchema,
  EngineState,
  PromptRewriteRequest,
  PromptRewriteResult,
} from "./types";
import schemaJson from "./fixtures/schema.json";
import stateJson from "./fixtures/state.json";
import historyJson from "./fixtures/history.json";
import promptsJson from "./fixtures/prompts.json";

export const USE_FIXTURES = import.meta.env.VITE_ENGINE_FIXTURES !== "false";

/* ---------------------------------------------------------------- real client */

const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

/** Same request idiom as lib/api.ts: JSON in/out, ApiError on network and HTTP failure. */
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError(tx("service.unreachable", { detail: (e as Error).message }), 0);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body?.detail != null) detail = String(body.detail);
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

/* -------------------------------------------------------------- fixture state */

interface FixtureHistoryFile {
  entries: EngineHistoryEntry[];
  /** sha → files-as-of-that-version, mirroring GET /history/{sha}/files. */
  snapshots: Record<string, Record<string, string>>;
}

const fixture = {
  schema: structuredClone(schemaJson) as unknown as EngineSchema,
  state: structuredClone(stateJson) as unknown as EngineState,
  history: structuredClone(historyJson) as unknown as FixtureHistoryFile,
  prompts: structuredClone(promptsJson) as unknown as EnginePrompts,
};

const delay = () => new Promise((r) => setTimeout(r, 120));

function fakeSha(): string {
  return Math.floor(Math.random() * 0xfffffff)
    .toString(16)
    .padStart(7, "0");
}

/**
 * Re-resolve values + resolution after a fixture apply: env-pinned knobs keep their
 * resolved value (the harness owns them); everything else re-reads its engine file, and a
 * key absent from the file falls back to the schema default.
 */
function rederiveState(): void {
  const { schema, state } = fixture;
  for (const stage of schema.stages) {
    for (const knob of stage.knobs) {
      const ref = `${stage.id}.${knob.key}`;
      if (state.resolution[ref] === "env") continue;
      const content = state.files[stage.file] ?? "";
      if (knob.type === "document") {
        state.values[ref] = content;
        state.resolution[ref] = content ? "engine" : "default";
      } else if (knob.type === "overlay_map") {
        state.values[ref] = getOverlayMap(content);
        state.resolution[ref] = "engine";
      } else {
        const raw = getYamlScalar(content, knob.key);
        if (raw == null) {
          state.values[ref] = (knob.default ?? null) as EngineState["values"][string];
          state.resolution[ref] = "default";
        } else {
          state.values[ref] = parseYamlScalar(raw, knob);
          state.resolution[ref] = "engine";
        }
      }
    }
  }
}

/* ------------------------------------------------------------------- exports */

export function getSchema(): Promise<EngineSchema> {
  if (!USE_FIXTURES) return req<EngineSchema>("/v1/engine/schema");
  return delay().then(() => structuredClone(fixture.schema));
}

export function getState(): Promise<EngineState> {
  if (!USE_FIXTURES) return req<EngineState>("/v1/engine/state");
  return delay().then(() => structuredClone(fixture.state));
}

/**
 * One engine file verbatim. The repair path: `/state` refuses to guess at a broken file, so
 * when it 400s this is how the console still gets the bytes to fix.
 */
export function getFile(path: string): Promise<EngineFile> {
  if (!USE_FIXTURES) {
    return req<EngineFile>(`/v1/engine/file?path=${encodeURIComponent(path)}`);
  }
  return delay().then(() => {
    const content = fixture.state.files[path];
    if (content == null) throw new ApiError(`no such engine file: ${path}`, 404);
    return { path, content };
  });
}

export function getHistory(limit = 50): Promise<EngineHistoryEntry[]> {
  if (!USE_FIXTURES) return req<EngineHistoryEntry[]>(`/v1/engine/history?limit=${limit}`);
  return delay().then(() => structuredClone(fixture.history.entries.slice(0, limit)));
}

/** One historical engine tree, used for real diffs and forward-only restore through apply. */
export function getHistoryFiles(sha: string): Promise<EngineHistoryFiles> {
  if (!USE_FIXTURES) {
    return req<EngineHistoryFiles>(`/v1/engine/history/${encodeURIComponent(sha)}/files`);
  }
  return delay().then(() => {
    const matches = Object.keys(fixture.history.snapshots).filter((candidate) =>
      candidate.startsWith(sha),
    );
    if (matches.length !== 1) throw new ApiError(`unknown engine version: ${sha}`, 404);
    const fullSha = matches[0];
    return { sha: fullSha, files: structuredClone(fixture.history.snapshots[fullSha]) };
  });
}

/** Model-visible prompt surfaces, assembled from the framework catalog and live overlays. */
export function getPrompts(): Promise<EnginePrompts> {
  if (!USE_FIXTURES) return req<EnginePrompts>("/v1/engine/prompts");
  return delay().then(() => structuredClone(fixture.prompts));
}

/**
 * Ask the deployment's recall-role model for one replacement clause. The response remains
 * a draft: only the ordinary Engine Console review/apply path can write it.
 */
export function rewritePrompt(input: PromptRewriteRequest): Promise<PromptRewriteResult> {
  if (!USE_FIXTURES) {
    return req<PromptRewriteResult>("/v1/engine/prompts/rewrite", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }
  return delay().then(() => {
    const segment = fixture.prompts.surfaces
      .flatMap((surface) => surface.segments)
      .find((candidate) => candidate.key === input.key);
    if (!segment) throw new ApiError(`unknown prompt catalog key: ${input.key}`, 404);
    const source = (segment.override_text ?? segment.framework_text).trimEnd();
    return {
      draft: `${source}\n\nApply this instruction with concise, explicit wording. When evidence is incomplete, state the limitation before the nearest supported conclusion.`,
      notes:
        input.locale === "zh"
          ? "已收紧措辞并保留全部插槽；原有事实边界不变。"
          : "Tightened the wording and preserved every placeholder; factual boundaries are unchanged.",
    };
  });
}

/**
 * Apply a change set as one version. `expectedHead` is the HEAD the draft was composed
 * against: the payload carries whole files, so without it a second tab's save would roll the
 * first one's values back silently. The service answers 409 when it no longer matches.
 */
export function applyChanges(
  changes: EngineApplyChange[],
  label: string,
  expectedHead?: string | null,
): Promise<EngineApplyResult> {
  if (!USE_FIXTURES) {
    return req<EngineApplyResult>("/v1/engine/apply", {
      method: "POST",
      body: JSON.stringify({ changes, label, expected_head: expectedHead ?? null }),
    });
  }
  return delay().then(() => {
    if (expectedHead != null && expectedHead !== fixture.state.version.head) {
      // The same refusal the service gives, so the console's stale-read path is exercised
      // in fixture mode instead of only against a live deployment.
      throw new ApiError(
        `the engine has moved on: composed against ${expectedHead}, HEAD is now ${fixture.state.version.head}`,
        409,
      );
    }
    for (const change of changes) {
      fixture.state.files[change.path] = change.content;
    }
    rederiveState();
    const sha = fakeSha();
    fixture.state.version = { head: sha, dirty: false };
    fixture.history.entries.unshift({
      sha,
      label,
      at: new Date().toISOString(),
      files: changes.map((c) => c.path),
    });
    fixture.history.snapshots[sha] = structuredClone(fixture.state.files);
    const effects: EngineApplyResult["effects"] = [];
    const seen = new Set<string>();
    for (const change of changes) {
      for (const stage of fixture.schema.stages) {
        if (stage.file !== change.path) continue;
        for (const knob of stage.knobs) {
          const ref = `${stage.id}.${knob.key}`;
          if (seen.has(ref)) continue;
          seen.add(ref);
          effects.push({ key: ref, apply: knob.apply });
        }
      }
    }
    return { sha, effects };
  });
}

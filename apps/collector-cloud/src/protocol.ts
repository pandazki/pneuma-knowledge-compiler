export const PROTOCOL = "pneuma.collector/v1";
export const MATERIAL_SCHEMA = "pneuma.material.agent-session/v1";
export const INVITATION_TTL_MS = 10 * 60 * 1000;
export const MAX_CONTROL_BYTES = 16 * 1024;
export const MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024;

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string) {
    super(code);
  }
}

export type JsonObject = Record<string, unknown>;
export type DeviceStatus = "active" | "paused" | "revoked";
export interface Policy {
  processor_id: "agent-sessions";
  scope: { projects: string[]; harnesses: string[]; since: string | null };
  interval_seconds: number;
  exclude?: string[];
}
export interface Material {
  schema: typeof MATERIAL_SCHEMA;
  snapshot_id: string;
  material_id: string;
  converter_version: number;
  session: JsonObject;
  origin: JsonObject;
}
export interface Manifest {
  snapshot_id: string;
  material_id: string;
  library_id: string;
  device_id: string;
  sha256: string;
  bytes: number;
  committed_at: string;
  sequence: number;
}

export function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError(400, "invalid_object");
  }
  return value as JsonObject;
}

export function text(value: unknown, name: string, max = 256): string {
  if (typeof value !== "string" || !value.trim() || value.length > max || /[\u0000-\u001f]/u.test(value)) {
    throw new ApiError(400, `invalid_${name}`);
  }
  return value;
}

export function identifier(value: unknown, name: string): string {
  const result = text(value, name, 128);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/u.test(result)) throw new ApiError(400, `invalid_${name}`);
  return result;
}

export function secret(value: unknown, name: string): string {
  const result = text(value, name, 256);
  if (!/^[a-zA-Z0-9_-]{32,256}$/u.test(result)) throw new ApiError(400, `invalid_${name}`);
  return result;
}

export function digest(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/u.test(value)) throw new ApiError(400, "invalid_sha256");
  return value;
}

export function policy(value: unknown): Policy {
  const data = object(value);
  const scope = object(data.scope);
  if (data.processor_id !== "agent-sessions") throw new ApiError(400, "unsupported_processor");
  if (!Array.isArray(scope.projects) || !scope.projects.length || scope.projects.length > 100) {
    throw new ApiError(400, "invalid_projects");
  }
  const projects = [...new Set(scope.projects.map((item) => text(item, "project", 2048)))];
  if (projects.includes("all") && projects.length !== 1) throw new ApiError(400, "invalid_projects");
  if (!Array.isArray(scope.harnesses) || !scope.harnesses.length || scope.harnesses.length > 2 ||
      scope.harnesses.some((item) => item !== "codex" && item !== "claude-code")) {
    throw new ApiError(400, "invalid_harnesses");
  }
  if (scope.since !== null && (typeof scope.since !== "string" || !Number.isFinite(Date.parse(scope.since)))) {
    throw new ApiError(400, "invalid_since");
  }
  if (!Number.isInteger(data.interval_seconds) || Number(data.interval_seconds) < 30 || Number(data.interval_seconds) > 86400) {
    throw new ApiError(400, "invalid_interval");
  }
  if (data.exclude !== undefined && (!Array.isArray(data.exclude) || data.exclude.length > 100)) {
    throw new ApiError(400, "invalid_exclude");
  }
  const exclude = data.exclude === undefined ? undefined :
    (data.exclude as unknown[]).map((item) => text(item, "exclude", 2048));
  return {
    processor_id: "agent-sessions",
    scope: { projects, harnesses: [...new Set(scope.harnesses)] as string[], since: scope.since as string | null },
    interval_seconds: Number(data.interval_seconds),
    ...(exclude !== undefined ? { exclude } : {}),
  };
}

export function material(value: unknown): Material {
  const data = object(value);
  if (data.schema !== MATERIAL_SCHEMA || data.converter_version !== 3) {
    throw new ApiError(400, "unsupported_material_version");
  }
  digest(data.snapshot_id);
  digest(data.material_id);
  const session = object(data.session);
  const origin = object(data.origin);
  if (session.provider !== "codex" && session.provider !== "claude-code") throw new ApiError(400, "unsupported_harness");
  text(session.session_id, "session_id", 1024);
  if (!Array.isArray(session.turns) || session.turns.length > 100000) throw new ApiError(400, "invalid_turns");
  return {
    schema: MATERIAL_SCHEMA,
    snapshot_id: data.snapshot_id as string,
    material_id: data.material_id as string,
    converter_version: data.converter_version as number,
    session,
    origin,
  };
}

export function randomSecret(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function sha256(value: string | Uint8Array): Promise<string> {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function bearer(request: Request): string {
  const authorization = request.headers.get("authorization") ?? "";
  if (!authorization.startsWith("Bearer ")) throw new ApiError(401, "authentication_required");
  const token = authorization.slice(7);
  if (token.length < 32 || token.length > 256) throw new ApiError(401, "invalid_credential");
  return token;
}

export async function boundedBody(request: Request, maximum: number): Promise<Uint8Array> {
  if (request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") {
    throw new ApiError(415, "json_required");
  }
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/u.test(length) || Number(length) > maximum)) throw new ApiError(413, "body_too_large");
  if (!request.body) throw new ApiError(400, "body_required");
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      total += chunk.value.byteLength;
      if (total > maximum) {
        await reader.cancel();
        throw new ApiError(413, "body_too_large");
      }
      chunks.push(chunk.value);
    }
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(total);
  let position = 0;
  for (const chunk of chunks) {
    result.set(chunk, position);
    position += chunk.byteLength;
  }
  return result;
}

export function parseBody(bytes: Uint8Array): unknown {
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes));
  } catch {
    throw new ApiError(400, "invalid_json");
  }
}

export function json(value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
}

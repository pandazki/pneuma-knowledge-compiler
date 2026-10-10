import { DurableObject } from "cloudflare:workers";
import { posix } from "node:path";
import {
  ApiError, INVITATION_TTL_MS, MAX_CONTROL_BYTES, MAX_SNAPSHOT_BYTES, PROTOCOL,
  bearer, boundedBody, digest, identifier, json, material, object, parseBody,
  policy, randomSecret, secret, sha256, text,
  type DeviceStatus, type Manifest, type Material, type Policy,
} from "./protocol";

type InvitationRow = {
  invitation_id: string; token_hash: string; library_id: string; label: string;
  policy: string; expires_at: string; revoked: number; device_id: string | null;
};
type DeviceRow = {
  device_id: string; secret_hash: string; library_id: string; label: string;
  policy: string; status: DeviceStatus; enrolled_at: string;
  last_seen_at: string | null; last_snapshot_at: string | null;
};
type UploadRow = {
  library_id: string; device_id: string; snapshot_id: string; material_id: string;
  sha256: string; bytes: number; received_at: string;
};
type SnapshotRow = UploadRow & { sequence: number; committed_at: string };

function failure(error: unknown): Response {
  if (error instanceof ApiError) return json({ error: error.code }, error.status);
  // Do not include exception messages, URLs, request bodies, or credentials in logs.
  console.error(JSON.stringify({ event: "collector_request_failed" }));
  return json({ error: "internal_error" }, 500);
}

function deviceView(row: DeviceRow) {
  return {
    device_id: row.device_id, library_id: row.library_id, label: row.label,
    status: row.status, policy: JSON.parse(row.policy) as Policy,
    enrolled_at: row.enrolled_at, last_seen_at: row.last_seen_at,
    last_snapshot_at: row.last_snapshot_at,
  };
}

function invitationView(row: InvitationRow) {
  return {
    invitation_id: row.invitation_id, label: row.label, device_id: row.device_id,
    expires_at: row.expires_at,
    status: row.revoked ? "revoked" : row.device_id ? "redeemed" :
      Date.parse(row.expires_at) <= Date.now() ? "expired" : "pending",
  };
}

function manifest(row: SnapshotRow): Manifest {
  return {
    snapshot_id: row.snapshot_id, material_id: row.material_id,
    library_id: row.library_id, device_id: row.device_id, sha256: row.sha256,
    bytes: row.bytes, committed_at: row.committed_at, sequence: row.sequence,
  };
}

function objectPrefix(row: UploadRow): string {
  return `libraries/${row.library_id}/devices/${row.device_id}/snapshots/${row.snapshot_id}`;
}

/** One installation belongs to one Owner; its registry is the coordination atom. */
export class CollectorRegistry extends DurableObject<Env> {
  #activeUploads = 0;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec(`
      CREATE TABLE IF NOT EXISTS invitations (
        invitation_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
        library_id TEXT NOT NULL, label TEXT NOT NULL, policy TEXT NOT NULL,
        expires_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, device_id TEXT
      );
      CREATE INDEX IF NOT EXISTS invitations_library ON invitations(library_id);
      CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY, secret_hash TEXT UNIQUE NOT NULL,
        library_id TEXT NOT NULL, label TEXT NOT NULL, policy TEXT NOT NULL,
        status TEXT NOT NULL, enrolled_at TEXT NOT NULL,
        last_seen_at TEXT, last_snapshot_at TEXT
      );
      CREATE INDEX IF NOT EXISTS devices_library ON devices(library_id);
      CREATE TABLE IF NOT EXISTS uploads (
        library_id TEXT NOT NULL, device_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
        material_id TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
        received_at TEXT NOT NULL,
        PRIMARY KEY(library_id, device_id, snapshot_id)
      );
      CREATE TABLE IF NOT EXISTS snapshots (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        library_id TEXT NOT NULL, device_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
        material_id TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
        received_at TEXT NOT NULL, committed_at TEXT NOT NULL,
        UNIQUE(library_id, device_id, snapshot_id)
      );
      CREATE INDEX IF NOT EXISTS snapshots_library ON snapshots(library_id, sequence);
    `);
  }

  // Request/Response RPC streams the body across the binding without an extra copy.
  async handle(request: Request): Promise<Response> {
    try {
      return await this.#route(request);
    } catch (error) {
      return failure(error);
    }
  }

  async #host(request: Request): Promise<void> {
    if (!this.env.HOST_TOKEN || this.env.HOST_TOKEN.length < 32) throw new ApiError(503, "host_token_not_configured");
    const [supplied, expected] = await Promise.all([sha256(bearer(request)), sha256(this.env.HOST_TOKEN)]);
    if (!crypto.subtle.timingSafeEqual(new TextEncoder().encode(supplied), new TextEncoder().encode(expected))) {
      throw new ApiError(401, "invalid_credential");
    }
  }

  #device(secretHash: string, allowPaused = false): DeviceRow {
    const row = this.ctx.storage.sql.exec<DeviceRow>("SELECT * FROM devices WHERE secret_hash = ?", secretHash).toArray()[0];
    if (!row) throw new ApiError(401, "invalid_credential");
    if (row.status === "revoked") throw new ApiError(403, "device_revoked");
    if (row.status === "paused" && !allowPaused) throw new ApiError(403, "device_paused");
    return row;
  }

  async #control(request: Request) {
    return object(parseBody(await boundedBody(request, MAX_CONTROL_BYTES)));
  }

  async #route(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    if (path === "/v1/enroll" && request.method === "POST") return this.#enroll(request);
    if (path.startsWith("/v1/device/")) {
      const secretHash = await sha256(bearer(request));
      if (path === "/v1/device/policy" && request.method === "GET") {
        const row = this.#device(secretHash, true);
        const seenAt = new Date().toISOString();
        this.ctx.storage.sql.exec("UPDATE devices SET last_seen_at = ? WHERE device_id = ?", seenAt, row.device_id);
        return json(deviceView({ ...row, last_seen_at: seenAt }));
      }
      if (path === "/v1/device/snapshots" && request.method === "POST") {
        // Hashing and parsing need a bounded buffer; limit concurrent buffers too.
        if (this.#activeUploads >= 2) throw new ApiError(429, "upload_busy");
        this.#activeUploads++;
        try {
          return await this.#upload(request, secretHash);
        } finally {
          this.#activeUploads--;
        }
      }
      throw new ApiError(404, "not_found");
    }

    await this.#host(request);
    if (path === "/v1/health" && request.method === "GET") return json({ protocol: PROTOCOL, status: "ok" });
    const match = /^\/v1\/libraries\/([^/]+)\/(invitations|devices|snapshots)(?:\/([^/]+))?$/u.exec(path);
    if (!match) throw new ApiError(404, "not_found");
    const libraryId = identifier(match[1], "library_id");
    const resource = match[2];
    const id = match[3] ? identifier(match[3], "id") : null;

    if (resource === "invitations") {
      if (!id && request.method === "POST") return this.#invite(request, libraryId);
      if (!id && request.method === "GET") {
        const rows = this.ctx.storage.sql.exec<InvitationRow>(
          "SELECT * FROM invitations WHERE library_id = ? ORDER BY expires_at DESC LIMIT 1000", libraryId,
        ).toArray();
        return json({ invitations: rows.map(invitationView) });
      }
      if (id && request.method === "DELETE") {
        const row = this.ctx.storage.sql.exec<InvitationRow>(
          "SELECT * FROM invitations WHERE library_id = ? AND invitation_id = ?", libraryId, id,
        ).toArray()[0];
        if (!row) throw new ApiError(404, "invitation_not_found");
        this.ctx.storage.sql.exec("UPDATE invitations SET revoked = 1 WHERE invitation_id = ?", id);
        return json(invitationView({ ...row, revoked: 1 }));
      }
    }
    if (resource === "devices") {
      if (!id && request.method === "GET") {
        const rows = this.ctx.storage.sql.exec<DeviceRow>(
          "SELECT * FROM devices WHERE library_id = ? ORDER BY enrolled_at, device_id LIMIT 1000", libraryId,
        ).toArray();
        return json({ devices: rows.map(deviceView) });
      }
      if (id && request.method === "PATCH") return this.#updateDevice(request, libraryId, id);
    }
    if (resource === "snapshots" && request.method === "GET") {
      if (id) return this.#download(libraryId, id, identifier(url.searchParams.get("device_id"), "device_id"));
      const cursorValue = url.searchParams.get("cursor") ?? "0";
      const limitValue = url.searchParams.get("limit") ?? "100";
      if (!/^\d{1,16}$/u.test(cursorValue) || !Number.isSafeInteger(Number(cursorValue)) ||
          !/^\d{1,3}$/u.test(limitValue) || Number(limitValue) < 1 || Number(limitValue) > 100) {
        throw new ApiError(400, "invalid_pagination");
      }
      const rows = this.ctx.storage.sql.exec<SnapshotRow>(
        "SELECT * FROM snapshots WHERE library_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
        libraryId, Number(cursorValue), Number(limitValue) + 1,
      ).toArray();
      const items = rows.slice(0, Number(limitValue));
      return json({
        items: items.map(manifest),
        next_cursor: String(items.at(-1)?.sequence ?? cursorValue),
        has_more: rows.length > Number(limitValue),
      });
    }
    throw new ApiError(405, "method_not_allowed");
  }

  async #invite(request: Request, libraryId: string): Promise<Response> {
    const body = await this.#control(request);
    const acceptedPolicy = policy(body.policy);
    const label = text(body.label, "label", 128);
    const token = randomSecret();
    const tokenHash = await sha256(token);
    const id = crypto.randomUUID();
    const expiresAt = new Date(Date.now() + INVITATION_TTL_MS).toISOString();
    this.ctx.storage.sql.exec(
      "INSERT INTO invitations(invitation_id, token_hash, library_id, label, policy, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
      id, tokenHash, libraryId, label, JSON.stringify(acceptedPolicy), expiresAt,
    );
    return json({ invitation_id: id, invite_token: token, expires_at: expiresAt }, 201);
  }

  async #enroll(request: Request): Promise<Response> {
    const body = await this.#control(request);
    const token = secret(body.invite_token, "invite_token");
    const deviceId = identifier(body.device_id, "device_id");
    const deviceSecret = secret(body.device_secret, "device_secret");
    if (body.label !== undefined) text(body.label, "label", 128);
    const [tokenHash, secretHash] = await Promise.all([sha256(token), sha256(deviceSecret)]);
    const result = this.ctx.storage.transactionSync(() => {
      const invitation = this.ctx.storage.sql.exec<InvitationRow>(
        "SELECT * FROM invitations WHERE token_hash = ?", tokenHash,
      ).toArray()[0];
      if (!invitation) throw new ApiError(401, "invalid_invitation");
      if (invitation.revoked) throw new ApiError(403, "invitation_revoked");
      if (invitation.device_id) {
        const existing = this.ctx.storage.sql.exec<DeviceRow>(
          "SELECT * FROM devices WHERE device_id = ?", invitation.device_id,
        ).toArray()[0];
        if (!existing || existing.device_id !== deviceId || existing.secret_hash !== secretHash) {
          throw new ApiError(409, "invitation_already_claimed");
        }
        if (existing.status === "revoked") throw new ApiError(403, "device_revoked");
        return existing;
      }
      if (Date.parse(invitation.expires_at) <= Date.now()) throw new ApiError(410, "invitation_expired");
      const conflicts = this.ctx.storage.sql.exec(
        "SELECT device_id FROM devices WHERE device_id = ? OR secret_hash = ?", deviceId, secretHash,
      ).toArray();
      if (conflicts.length) throw new ApiError(409, "device_already_registered");
      const enrolledAt = new Date().toISOString();
      this.ctx.storage.sql.exec(
        "INSERT INTO devices(device_id, secret_hash, library_id, label, policy, status, enrolled_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
        deviceId, secretHash, invitation.library_id, invitation.label, invitation.policy, enrolledAt,
      );
      this.ctx.storage.sql.exec("UPDATE invitations SET device_id = ? WHERE invitation_id = ?", deviceId, invitation.invitation_id);
      return this.ctx.storage.sql.exec<DeviceRow>("SELECT * FROM devices WHERE device_id = ?", deviceId).one();
    });
    return json(deviceView(result));
  }

  async #updateDevice(request: Request, libraryId: string, deviceId: string): Promise<Response> {
    const body = await this.#control(request);
    if (body.status !== "active" && body.status !== "paused" && body.status !== "revoked") throw new ApiError(400, "invalid_status");
    const row = this.ctx.storage.sql.exec<DeviceRow>(
      "SELECT * FROM devices WHERE library_id = ? AND device_id = ?", libraryId, deviceId,
    ).toArray()[0];
    if (!row) throw new ApiError(404, "device_not_found");
    if (row.status === "revoked" && body.status !== "revoked") throw new ApiError(409, "device_revoked");
    const nextPolicy = body.policy === undefined ? row.policy : JSON.stringify(policy(body.policy));
    this.ctx.storage.sql.exec("UPDATE devices SET status = ?, policy = ? WHERE device_id = ?", body.status, nextPolicy, deviceId);
    return json(deviceView({ ...row, status: body.status, policy: nextPolicy }));
  }

  #checkScope(device: DeviceRow, snapshot: Material): void {
    const allowed = JSON.parse(device.policy) as Policy;
    if (snapshot.origin.device_id !== undefined && snapshot.origin.device_id !== device.device_id) {
      throw new ApiError(403, "device_identity_mismatch");
    }
    if (!allowed.scope.harnesses.includes(String(snapshot.session.provider))) throw new ApiError(403, "harness_not_allowed");
    if (!allowed.scope.projects.includes("all")) {
      const project = String(snapshot.session.project_path ?? "");
      const normalized = (path: string) => posix.normalize(path).replace(/\/$/u, "") || "/";
      if (!project || !allowed.scope.projects.some((root) => normalized(project) === normalized(root))) {
        throw new ApiError(403, "project_not_allowed");
      }
    }
    if (allowed.scope.since !== null) {
      const turns = snapshot.session.turns as unknown[];
      const lastTurn = turns.at(-1);
      const lastAt = Date.parse(String(lastTurn ? object(lastTurn).at ?? "" : ""));
      if (!Number.isFinite(lastAt) || lastAt < Date.parse(allowed.scope.since)) throw new ApiError(403, "history_not_allowed");
    }
  }

  async #upload(request: Request, secretHash: string): Promise<Response> {
    this.#device(secretHash);
    const expectedHash = digest(request.headers.get("X-Content-SHA256"));
    const configuredMaximum = Number(this.env.MAX_SNAPSHOT_BYTES);
    const maximum = Number.isSafeInteger(configuredMaximum) && configuredMaximum > 0 ?
      Math.min(configuredMaximum, MAX_SNAPSHOT_BYTES) : MAX_SNAPSHOT_BYTES;
    const bytes = await boundedBody(request, maximum);
    if (await sha256(bytes) !== expectedHash) throw new ApiError(400, "hash_mismatch");
    const snapshot = material(parseBody(bytes));
    // Re-read after body/hash awaits: revocation or a policy change may have happened.
    const device = this.#device(secretHash);
    this.#checkScope(device, snapshot);
    const lookup = [device.library_id, device.device_id, snapshot.snapshot_id];
    const upload = this.ctx.storage.transactionSync(() => {
      const existing = this.ctx.storage.sql.exec<UploadRow>(
        "SELECT * FROM uploads WHERE library_id = ? AND device_id = ? AND snapshot_id = ?", ...lookup,
      ).toArray()[0];
      if (existing) {
        if (existing.sha256 !== expectedHash || existing.bytes !== bytes.byteLength) throw new ApiError(409, "snapshot_conflict");
        return existing;
      }
      const row: UploadRow = {
        library_id: device.library_id, device_id: device.device_id,
        snapshot_id: snapshot.snapshot_id, material_id: snapshot.material_id,
        sha256: expectedHash, bytes: bytes.byteLength, received_at: new Date().toISOString(),
      };
      this.ctx.storage.sql.exec(
        "INSERT INTO uploads(library_id, device_id, snapshot_id, material_id, sha256, bytes, received_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        row.library_id, row.device_id, row.snapshot_id, row.material_id, row.sha256, row.bytes, row.received_at,
      );
      return row;
    });
    const committed = this.#committed(...lookup as [string, string, string]);
    if (committed) return json({ ...manifest(committed), duplicate: true });
    const prefix = objectPrefix(upload);
    const bodyKey = `${prefix}/snapshot.json`;
    const stored = await this.env.MATERIALS.put(bodyKey, bytes, {
      onlyIf: { etagDoesNotMatch: "*" }, sha256: expectedHash,
      httpMetadata: { contentType: "application/json" }, customMetadata: { sha256: expectedHash },
    });
    if (stored === null) {
      const existing = await this.env.MATERIALS.head(bodyKey);
      if (!existing || existing.customMetadata?.sha256 !== expectedHash || existing.size !== bytes.byteLength) {
        throw new ApiError(409, "snapshot_conflict");
      }
    }
    const storedManifest = JSON.stringify({ schema: "pneuma.collector.manifest/v1", ...upload });
    const manifestHash = await sha256(storedManifest);
    const writtenManifest = await this.env.MATERIALS.put(`${prefix}/manifest.json`, storedManifest, {
      onlyIf: { etagDoesNotMatch: "*" }, sha256: manifestHash,
      httpMetadata: { contentType: "application/json" }, customMetadata: { sha256: manifestHash },
    });
    if (writtenManifest === null) {
      const existing = await this.env.MATERIALS.head(`${prefix}/manifest.json`);
      if (!existing || existing.customMetadata?.sha256 !== manifestHash) throw new ApiError(409, "manifest_conflict");
    }
    // Sequence is assigned only after both R2 objects exist. A slow upload cannot
    // appear behind a polling cursor that already acknowledged a later upload.
    const result = this.ctx.storage.transactionSync(() => {
      this.#checkScope(this.#device(secretHash), snapshot);
      const prior = this.#committed(...lookup as [string, string, string]);
      if (prior) return { row: prior, duplicate: true };
      const committedAt = new Date().toISOString();
      this.ctx.storage.sql.exec(
        "INSERT INTO snapshots(library_id, device_id, snapshot_id, material_id, sha256, bytes, received_at, committed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        upload.library_id, upload.device_id, upload.snapshot_id, upload.material_id,
        upload.sha256, upload.bytes, upload.received_at, committedAt,
      );
      this.ctx.storage.sql.exec("UPDATE devices SET last_seen_at = ?, last_snapshot_at = ? WHERE device_id = ?", committedAt, committedAt, device.device_id);
      return { row: this.#committed(...lookup as [string, string, string])!, duplicate: false };
    });
    return json({ ...manifest(result.row), duplicate: result.duplicate }, result.duplicate ? 200 : 201);
  }

  #committed(libraryId: string, deviceId: string, snapshotId: string): SnapshotRow | undefined {
    return this.ctx.storage.sql.exec<SnapshotRow>(
      "SELECT * FROM snapshots WHERE library_id = ? AND device_id = ? AND snapshot_id = ?", libraryId, deviceId, snapshotId,
    ).toArray()[0];
  }

  async #download(libraryId: string, snapshotId: string, deviceId: string): Promise<Response> {
    const row = this.#committed(libraryId, deviceId, snapshotId);
    if (!row) throw new ApiError(404, "snapshot_not_found");
    const body = await this.env.MATERIALS.get(`${objectPrefix(row)}/snapshot.json`);
    if (!body) throw new ApiError(503, "snapshot_unavailable");
    return new Response(body.body, {
      headers: {
        "Content-Type": "application/json", "Content-Length": String(row.bytes),
        "Cache-Control": "no-store", "X-Content-SHA256": row.sha256,
        "X-Content-Type-Options": "nosniff",
      },
    });
  }
}

export default {
  async fetch(request, env): Promise<Response> {
    try {
      const path = new URL(request.url).pathname;
      if ((request.method === "GET" || request.method === "HEAD") &&
          ["/install.sh", "/collector.py", "/agent_sessions.py", "/release.json"].includes(path)) {
        const response = await env.ASSETS.fetch(request);
        const headers = new Headers(response.headers);
        headers.set("Cache-Control", "no-store");
        headers.set("X-Content-Type-Options", "nosniff");
        return new Response(response.body, { status: response.status, headers });
      }
      if (!path.startsWith("/v1/")) return json({ error: "not_found" }, 404);
      return await env.REGISTRY.getByName("owner-installation").handle(request);
    } catch (error) {
      return failure(error);
    }
  },
} satisfies ExportedHandler<Env>;

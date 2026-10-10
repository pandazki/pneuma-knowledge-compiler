import assert from "node:assert/strict";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { setTimeout } from "node:timers/promises";
import { after, before, beforeEach, afterEach, test } from "node:test";
import { build } from "esbuild";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";

const ownerToken = randomBytes(32).toString("hex");
const basePolicy = {
  processor_id: "agent-sessions",
  scope: { projects: ["all"], harnesses: ["codex", "claude-code"], since: null },
  interval_seconds: 300,
};
const sha = (value) => createHash("sha256").update(value).digest("hex");
let script;
let mf;

before(async () => {
  const result = await build({
    entryPoints: ["tests/worker.ts"], bundle: true, write: false,
    format: "esm", platform: "neutral", target: "es2022", external: ["cloudflare:workers", "node:path"],
  });
  script = result.outputFiles[0].text;
});

beforeEach(() => {
  mf = new Miniflare(convertV4MiniflareOptions({
    modules: true, script, compatibilityDate: "2026-10-10", compatibilityFlags: ["nodejs_compat"],
    bindings: { HOST_TOKEN: ownerToken, MAX_SNAPSHOT_BYTES: "4096" },
    durableObjects: { REGISTRY: { className: "CollectorRegistry", useSQLite: true } },
    r2Buckets: ["MATERIALS"],
    serviceBindings: { ASSETS: (request) => new Response(`asset:${new URL(request.url).pathname}`) },
  }));
});
afterEach(async () => { await mf.dispose(); });
after(() => { script = undefined; });

async function request(path, { method = "GET", token = ownerToken, body, headers = {} } = {}) {
  return mf.dispatchFetch(`https://collector.test${path}`, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: typeof body === "string" ? body : JSON.stringify(body) } : {}),
  });
}

async function invite(library = "library-a", policy = basePolicy) {
  const response = await request(`/v1/libraries/${library}/invitations`, {
    method: "POST", body: { label: "Synthetic device", policy },
  });
  assert.equal(response.status, 201, await response.clone().text());
  return response.json();
}

async function enroll(library = "library-a", policy = basePolicy) {
  const invitation = await invite(library, policy);
  const credentials = {
    invite_token: invitation.invite_token, device_id: randomUUID(),
    device_secret: randomBytes(32).toString("hex"), label: "Synthetic device",
  };
  const response = await request("/v1/enroll", { method: "POST", token: null, body: credentials });
  assert.equal(response.status, 200, await response.clone().text());
  return { ...credentials, invitation, enrollment: await response.json() };
}

function snapshot(device, seed = "first") {
  return {
    schema: "pneuma.material.agent-session/v1",
    converter_version: 3, snapshot_id: sha(seed), material_id: sha("synthetic-session"),
    session: {
      provider: "codex", session_id: "synthetic-session", project_path: "/work/synthetic",
      model: "synthetic-model", is_subagent: false, project_conflict: false,
      turns: [{ turn_id: "turn-1", role: "user", kind: "message", at: "2026-10-10T00:00:00Z", text: "Synthetic project discussion." }],
      last_at: "2026-10-10T00:00:00Z", timestamp_repairs: 0, injected_blocks: 0,
    },
    origin: { device_id: device.device_id, file: "/synthetic/session.jsonl" },
  };
}

async function upload(device, value, headers = {}) {
  const body = JSON.stringify(value);
  return request("/v1/device/snapshots", {
    method: "POST", token: device.device_secret, body,
    headers: { "X-Content-SHA256": sha(body), ...headers },
  });
}

async function registry() {
  return (await mf.getDurableObjectNamespace("REGISTRY")).getByName("owner-installation");
}

async function waitUntilBlocked(stub) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await stub.uploadIsBlocked()) return;
    await setTimeout(10);
  }
  assert.fail("Upload did not reach the synthetic R2 delay");
}

test("health is owner-authenticated and bootstrap assets are public", async () => {
  assert.equal((await request("/v1/health", { token: null })).status, 401);
  assert.equal((await request("/v1/health", { token: "x".repeat(64) })).status, 401);
  assert.deepEqual(await (await request("/v1/health")).json(), { protocol: "pneuma.collector/v1", status: "ok" });
  for (const asset of ["install.sh", "collector.py", "agent_sessions.py", "release.json"]) {
    const response = await request(`/${asset}`, { token: null });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
  }
  assert.equal((await request("/private.txt", { token: null })).status, 404);
});

test("enrollment persists only hashed secrets and its exact retry survives expiry", async () => {
  const device = await enroll();
  const stored = await (await registry()).storedCredentials();
  assert.deepEqual(stored.devices, [{ secret_hash: sha(device.device_secret) }]);
  assert.deepEqual(stored.invitations, [{ token_hash: sha(device.invite_token) }]);
  assert.equal(JSON.stringify(device.enrollment).includes(device.device_secret), false);
  await (await registry()).expireInvitations();
  const retry = await request("/v1/enroll", { method: "POST", token: null, body: device });
  assert.equal(retry.status, 200);
  assert.deepEqual(await retry.json(), device.enrollment);
  const list = await (await request("/v1/libraries/library-a/invitations")).json();
  assert.equal(list.invitations[0].status, "redeemed");
  assert.equal(list.invitations[0].device_id, device.device_id);
  assert.equal(JSON.stringify(list).includes(device.invite_token), false);
});

test("racing claims atomically bind one invitation to one device", async () => {
  const invitation = await invite();
  const identities = [0, 1].map((i) => ({
    invite_token: invitation.invite_token, device_id: `device-${i}`,
    device_secret: randomBytes(32).toString("hex"), label: `Synthetic ${i}`,
  }));
  const claims = await Promise.all(identities.map((body) => request("/v1/enroll", { method: "POST", token: null, body })));
  assert.deepEqual(claims.map((r) => r.status).sort(), [200, 409]);
  const devices = await (await request("/v1/libraries/library-a/devices")).json();
  assert.equal(devices.devices.length, 1);
});

test("the Owner's invitation label survives enrollment and client hostname changes", async () => {
  const created = await request("/v1/libraries/library-a/invitations", {
    method: "POST", body: { label: "Owner's work laptop", policy: basePolicy },
  });
  assert.equal(created.status, 201);
  const invitation = await created.json();
  const claim = {
    invite_token: invitation.invite_token, device_id: "label-device",
    device_secret: randomBytes(32).toString("hex"), label: "hostname-before",
  };
  const first = await request("/v1/enroll", { method: "POST", token: null, body: claim });
  assert.equal(first.status, 200);
  assert.equal((await first.json()).label, "Owner's work laptop");
  await request("/v1/libraries/library-a/devices/label-device", { method: "PATCH", body: { status: "paused" } });
  const retry = await request("/v1/enroll", {
    method: "POST", token: null, body: { ...claim, label: "hostname-after" },
  });
  assert.equal(retry.status, 200);
  const device = await retry.json();
  assert.equal(device.label, "Owner's work laptop");
  assert.equal(device.status, "paused");
});

test("unused invitations expire and revoked invitations never enroll", async () => {
  const expired = await invite();
  await (await registry()).expireInvitations();
  const claim = { invite_token: expired.invite_token, device_id: "expired-device", device_secret: "a".repeat(64), label: "Synthetic" };
  assert.equal((await request("/v1/enroll", { method: "POST", token: null, body: claim })).status, 410);
  const revoked = await invite();
  assert.equal((await request(`/v1/libraries/library-a/invitations/${revoked.invitation_id}`, { method: "DELETE" })).status, 200);
  assert.equal((await request("/v1/enroll", { method: "POST", token: null, body: { ...claim, invite_token: revoked.invite_token } })).status, 403);
});

test("pause permits policy polling, resume restores upload, revocation is terminal", async () => {
  const device = await enroll();
  const endpoint = `/v1/libraries/library-a/devices/${device.device_id}`;
  assert.equal((await request(endpoint, { method: "PATCH", body: { status: "paused" } })).status, 200);
  const paused = await request("/v1/device/policy", { token: device.device_secret });
  assert.equal((await paused.json()).status, "paused");
  assert.equal((await upload(device, snapshot(device))).status, 403);
  assert.equal((await request(endpoint, { method: "PATCH", body: { status: "active" } })).status, 200);
  assert.equal((await upload(device, snapshot(device))).status, 201);
  assert.equal((await request(endpoint, { method: "PATCH", body: { status: "revoked" } })).status, 200);
  assert.equal((await request("/v1/device/policy", { token: device.device_secret })).status, 403);
  assert.equal((await upload(device, snapshot(device, "after-revoke"))).status, 403);
  assert.equal((await request(endpoint, { method: "PATCH", body: { status: "active" } })).status, 409);
  assert.equal((await request("/v1/enroll", { method: "POST", token: null, body: device })).status, 403);
});

test("immutable upload is idempotent, different bytes conflict without overwrite", async () => {
  const device = await enroll();
  const value = snapshot(device);
  const original = JSON.stringify(value);
  const first = await upload(device, value);
  assert.equal(first.status, 201, await first.clone().text());
  const firstManifest = await first.json();
  const second = await upload(device, value);
  assert.equal(second.status, 200);
  assert.deepEqual(await second.json(), { ...firstManifest, duplicate: true });
  const changed = structuredClone(value);
  changed.session.turns[0].text = "Different synthetic material.";
  assert.equal((await upload(device, changed)).status, 409);
  const body = await request(`/v1/libraries/library-a/snapshots/${value.snapshot_id}?device_id=${device.device_id}`);
  assert.equal(await body.text(), original);
  assert.equal(body.headers.get("x-content-sha256"), sha(original));
  const bucket = await mf.getR2Bucket("MATERIALS");
  const objects = await bucket.list();
  assert.equal(objects.objects.length, 2);
  assert.equal(objects.objects.some((item) => item.key.endsWith("/manifest.json")), true);
});

test("same material on two devices keeps both origins; libraries and credentials are isolated", async () => {
  const a = await enroll();
  const b = await enroll();
  const other = await enroll("library-b");
  const value = snapshot(a);
  assert.equal((await upload(a, value)).status, 201);
  assert.equal((await upload(b, { ...value, origin: { ...value.origin, device_id: b.device_id } })).status, 201);
  assert.equal((await upload(other, snapshot(other))).status, 201);
  const list = await (await request("/v1/libraries/library-a/snapshots")).json();
  assert.equal(list.items.length, 2);
  assert.deepEqual(new Set(list.items.map((row) => row.device_id)), new Set([a.device_id, b.device_id]));
  assert.equal((await request(`/v1/libraries/library-b/snapshots/${value.snapshot_id}?device_id=${a.device_id}`)).status, 404);
  assert.equal((await request("/v1/libraries/library-a/snapshots", { token: a.device_secret })).status, 401);
  assert.equal((await upload(a, snapshot(b, "spoofed-device"))).status, 403);
  assert.equal((await request(`/v1/libraries/library-b/devices/${a.device_id}`, { method: "PATCH", body: { status: "revoked" } })).status, 404);
});

test("pagination cursor resumes at the committed tail and sees later arrivals", async () => {
  const device = await enroll();
  for (const seed of ["one", "two", "three"]) assert.equal((await upload(device, snapshot(device, seed))).status, 201);
  const first = await (await request("/v1/libraries/library-a/snapshots?limit=2")).json();
  assert.equal(first.items.length, 2);
  assert.equal(first.has_more, true);
  const second = await (await request(`/v1/libraries/library-a/snapshots?cursor=${first.next_cursor}&limit=2`)).json();
  assert.equal(second.items.length, 1);
  assert.equal(second.has_more, false);
  const empty = await (await request(`/v1/libraries/library-a/snapshots?cursor=${second.next_cursor}`)).json();
  assert.equal(empty.items.length, 0);
  assert.equal(empty.next_cursor, second.next_cursor);
  await upload(device, snapshot(device, "later"));
  const later = await (await request(`/v1/libraries/library-a/snapshots?cursor=${empty.next_cursor}`)).json();
  assert.equal(later.items.length, 1);
  assert.ok(later.items[0].sequence > Number(empty.next_cursor));
});

test("body limits, transport hash, schema, and IDs are checked before storage", async () => {
  const device = await enroll();
  const valid = snapshot(device);
  assert.equal((await upload(device, valid, { "X-Content-SHA256": "0".repeat(64) })).status, 400);
  assert.equal((await upload(device, { ...valid, schema: "unsupported/v1" })).status, 400);
  assert.equal((await upload(device, { ...valid, snapshot_id: "../other" })).status, 400);
  assert.equal((await upload(device, { ...valid, padding: "x".repeat(5000) })).status, 413);
  assert.equal((await upload(device, valid, { "Content-Type": "text/plain" })).status, 415);
  const counts = await (await registry()).counts();
  assert.equal(counts.uploads, 0);
  assert.equal(counts.snapshots, 0);
});

test("project, harness, and history policy apply to every upload", async () => {
  const restricted = await enroll("library-a", {
    ...basePolicy, scope: { projects: ["/work/synthetic"], harnesses: ["codex"], since: "2026-10-01T00:00:00Z" },
  });
  const value = snapshot(restricted);
  assert.equal((await upload(restricted, value)).status, 201);
  const invalid = (field, content, seed) => ({ ...value, snapshot_id: sha(seed), session: { ...value.session, [field]: content } });
  assert.equal((await upload(restricted, invalid("project_path", "/work/synthetic-other", "path"))).status, 403);
  assert.equal((await upload(restricted, invalid("project_path", "/work/synthetic/subproject", "subproject"))).status, 403);
  assert.equal((await upload(restricted, invalid("provider", "claude-code", "harness"))).status, 403);
  assert.equal((await upload(restricted, invalid("turns", [{ ...value.session.turns[0], at: "2026-09-01T00:00:00Z" }], "history"))).status, 403);
  assert.equal((await upload(restricted, invalid("turns", [], "missing-history"))).status, 403);
});

test("conflicting simultaneous upload accepts one payload and never overwrites it", async () => {
  const device = await enroll();
  const a = snapshot(device);
  const b = structuredClone(a);
  b.session.turns[0].text = "Conflicting synthetic transcript.";
  const responses = await Promise.all([upload(device, a), upload(device, b)]);
  assert.deepEqual(responses.map((response) => response.status).sort(), [201, 409]);
  const original = responses[0].status === 201 ? a : b;
  const response = await request(`/v1/libraries/library-a/snapshots/${a.snapshot_id}?device_id=${device.device_id}`);
  assert.equal(await response.text(), JSON.stringify(original));
  const counts = await (await registry()).counts();
  assert.equal(counts.uploads, 1);
  assert.equal(counts.snapshots, 1);
});

test("a failed manifest write stays invisible and an exact retry repairs delivery", async () => {
  const device = await enroll();
  const value = snapshot(device);
  const stub = await registry();
  await stub.failNextManifest();
  assert.equal((await upload(device, value)).status, 500);
  assert.equal((await (await request("/v1/libraries/library-a/snapshots")).json()).items.length, 0);
  const bucket = await mf.getR2Bucket("MATERIALS");
  assert.equal((await bucket.list()).objects.length, 1);
  assert.equal((await upload(device, value)).status, 201);
  assert.equal((await bucket.list()).objects.length, 2);
  assert.equal((await (await request("/v1/libraries/library-a/snapshots")).json()).items.length, 1);
});

test("slow uploads commit after the current cursor rather than disappearing behind it", async () => {
  const device = await enroll();
  const slow = snapshot(device, "slow");
  const stub = await registry();
  await stub.blockUpload(slow.snapshot_id);
  const pending = upload(device, slow);
  await waitUntilBlocked(stub);
  assert.equal((await upload(device, snapshot(device, "fast"))).status, 201);
  const first = await (await request("/v1/libraries/library-a/snapshots")).json();
  assert.equal(first.items.length, 1);
  assert.equal(first.items[0].snapshot_id, sha("fast"));
  await stub.releaseUpload();
  assert.equal((await pending).status, 201);
  const next = await (await request(`/v1/libraries/library-a/snapshots?cursor=${first.next_cursor}`)).json();
  assert.equal(next.items.length, 1);
  assert.equal(next.items[0].snapshot_id, slow.snapshot_id);
});

test("revocation during an R2 write prevents that in-flight upload from committing", async () => {
  const device = await enroll();
  const value = snapshot(device);
  const stub = await registry();
  await stub.blockUpload(value.snapshot_id);
  const pending = upload(device, value);
  await waitUntilBlocked(stub);
  assert.equal((await request(`/v1/libraries/library-a/devices/${device.device_id}`, {
    method: "PATCH", body: { status: "revoked" },
  })).status, 200);
  await stub.releaseUpload();
  assert.equal((await pending).status, 403);
  assert.equal((await (await request("/v1/libraries/library-a/snapshots")).json()).items.length, 0);
});

test("exclusion policy is preserved and bounded", async () => {
  const device = await enroll("library-a", { ...basePolicy, exclude: ["/tmp/**", "**/synthetic-private/**"] });
  const current = await (await request("/v1/device/policy", { token: device.device_secret })).json();
  assert.deepEqual(current.policy.exclude, ["/tmp/**", "**/synthetic-private/**"]);
  assert.equal((await request("/v1/libraries/library-a/invitations", {
    method: "POST", body: { label: "Synthetic", policy: { ...basePolicy, exclude: Array(101).fill("/tmp") } },
  })).status, 400);
});

test("streaming uploads are bounded even without a Content-Length header", async () => {
  const device = await enroll();
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("x".repeat(3000)));
      controller.enqueue(new TextEncoder().encode("y".repeat(3000)));
      controller.close();
    },
  });
  const response = await mf.dispatchFetch("https://collector.test/v1/device/snapshots", {
    method: "POST", body, duplex: "half",
    headers: { Authorization: `Bearer ${device.device_secret}`, "Content-Type": "application/json", "X-Content-SHA256": "0".repeat(64) },
  });
  assert.equal(response.status, 413);
});

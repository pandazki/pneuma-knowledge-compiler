// Local integration harness: real Worker, SQLite Durable Object, R2, and frozen assets.
import { build } from "esbuild";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";
import { cp, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";

if (!process.env.HOST_TOKEN || process.env.HOST_TOKEN.length < 32) throw new Error("HOST_TOKEN required");
const result = await build({
  entryPoints: ["src/index.ts"], bundle: true, write: false,
  format: "esm", platform: "neutral", target: "es2022", external: ["cloudflare:workers", "node:path"],
});
const script = result.outputFiles[0].text;
const assetRoot = await mkdtemp(join(tmpdir(), "pkc-collector-assets-"));
await cp("public", assetRoot, { recursive: true });
const mf = new Miniflare(convertV4MiniflareOptions({
  host: "127.0.0.1", port: Number(process.env.COLLECTOR_TEST_PORT ?? "48738"),
  modules: true, script, compatibilityDate: "2026-10-10", compatibilityFlags: ["nodejs_compat"],
  bindings: { HOST_TOKEN: process.env.HOST_TOKEN, MAX_SNAPSHOT_BYTES: "8388608" },
  durableObjects: { REGISTRY: { className: "CollectorRegistry", useSQLite: true } },
  r2Buckets: ["MATERIALS"],
  serviceBindings: {
    ASSETS: async (request) => {
      const name = new URL(request.url).pathname.slice(1);
      if (!["install.sh", "collector.py", "agent_sessions.py", "release.json"].includes(name)) return new Response(null, { status: 404 });
      try {
        const bytes = await readFile(join(assetRoot, name));
        return new Response(bytes, { headers: { "Content-Type": name.endsWith(".json") ? "application/json" : "text/plain" } });
      } catch {
        return new Response(null, { status: 404 });
      }
    },
  },
}));
console.log(JSON.stringify({ ready: String(await mf.ready), worker_sha256: createHash("sha256").update(script).digest("hex") }));
await new Promise((resolve) => {
  process.once("SIGINT", resolve);
  process.once("SIGTERM", resolve);
});
await mf.dispose();
await rm(assetRoot, { recursive: true, force: true });

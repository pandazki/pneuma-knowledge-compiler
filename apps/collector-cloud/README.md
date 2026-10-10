# Collector cloud

**English** | [简体中文](README.zh-CN.md)

This optional Cloudflare application connects remote Codex and Claude Code collectors to a personal knowledge library. One installation belongs to one Owner. The Owner's local console creates a ten-minute invitation and produces the target machine's install command. After enrollment, the target collects and uploads while the Owner's computer is offline. Knowledge processing still happens locally through the shared agent-session processor; core does not depend on this application or a cloud registration service.

The Worker serves the installer and authenticates every material operation. A SQLite Durable Object holds invitations, device credentials, policy and delivery receipts; a private R2 bucket holds immutable normalized snapshots and manifests. Uploads and downloads pass through the Worker binding. Neither an invitation nor a collector receives an R2 credential.

## Prepare an installation

Use Node.js 22.13 or newer, pnpm and Python 3. The Python collector and shared decoder are packaged from their source files by `scripts/build_collector_assets.py`; do not edit generated files under `public/`.

```bash
cd apps/collector-cloud
pnpm install
pnpm run check
pnpm test
pnpm run dry-run
```

`check` generates binding/runtime types from `wrangler.jsonc` before checking TypeScript. `dry-run` packages the real collector assets and validates the deployment without deploying. Tests use local Miniflare, SQLite and R2; no Cloudflare account, model key or production knowledge library is used.

For a new Owner installation, set distinct Worker and bucket names in `wrangler.jsonc`, authenticate to that Owner's Cloudflare account, create the private bucket and configure a random Owner token with at least 32 characters:

```bash
pnpm exec wrangler login
pnpm exec wrangler r2 bucket create pneuma-collector-materials
pnpm exec wrangler secret put HOST_TOKEN
pnpm run deploy
```

Enter the token at Wrangler's secret prompt. Save the resulting Worker HTTPS URL and the same Owner token in the local console's remote-source configuration. The token controls all libraries in this one installation. Do not put it in a collector command, URL, repository, or project variables. A local-only `.dev.vars` can be created from `.dev.vars.example` for `pnpm run dev`; the example's placeholder must be replaced. Deployment uses the Worker secret, not `.dev.vars`.

The Owner creates invitations and controls devices through the local console. A revoked device must enroll as a new device with a new invitation. Pausing a device preserves its identity and can be reversed. Revoking an invitation does not revoke a device already enrolled from it; use the device control for that.

## HTTP contract

The protocol version is `pneuma.collector/v1`. Control bodies and responses are JSON. Errors are `{"error":"code"}`. Authenticated responses have `Cache-Control: no-store`. There is no credential in a query string and no browser CORS interface.

Owner requests use `Authorization: Bearer <HOST_TOKEN>`:

| Method and path | Request / result |
| --- | --- |
| `GET /v1/health` | `{protocol,status:"ok"}` |
| `POST /v1/libraries/{library_id}/invitations` | `{label,policy}` → `{invitation_id,invite_token,expires_at}`; expires after ten minutes |
| `GET /v1/libraries/{library_id}/invitations` | `{invitations:[{invitation_id,label,status,expires_at,device_id}]}`; no token is returned |
| `DELETE /v1/libraries/{library_id}/invitations/{invitation_id}` | Revokes the invitation; returns its current view |
| `GET /v1/libraries/{library_id}/devices` | `{devices:[{device_id,library_id,label,status,policy,enrolled_at,last_seen_at,last_snapshot_at}]}` |
| `PATCH /v1/libraries/{library_id}/devices/{device_id}` | `{status:"active"\|"paused"\|"revoked",policy?}` → device view |
| `GET /v1/libraries/{library_id}/snapshots?cursor=0&limit=100` | `{items:[manifest],next_cursor,has_more}` |
| `GET /v1/libraries/{library_id}/snapshots/{snapshot_id}?device_id={device_id}` | Original snapshot JSON bytes with `X-Content-SHA256` |

`library_id` and `device_id` contain ASCII letters, digits, `_` or `-`, begin with a letter or digit, and have at most 128 characters. The Owner selects the library when creating an invitation. A device cannot select or change its destination library. Device IDs and credential hashes are unique within an installation.

The invitation policy is:

```json
{
  "processor_id": "agent-sessions",
  "scope": {
    "projects": ["all"],
    "harnesses": ["codex", "claude-code"],
    "since": null
  },
  "interval_seconds": 300,
  "exclude": ["/tmp/**"]
}
```

`projects` is either `["all"]` or an explicit list of remote project paths. Paths match exactly after lexical normalization; selecting a directory does not authorize subprojects. `since` is null or an ISO date/time and is checked against the last retained turn's timestamp, matching the shared scanner. The optional exclusion list is passed to the collector's shared scanner. The cloud additionally checks the reported harness, project and history scope for every upload. Interval bounds are 30–86400 seconds; project and exclusion lists each contain at most 100 entries.

Enrollment is `POST /v1/enroll` without a bearer header:

```json
{
  "invite_token": "<one-time invitation>",
  "device_id": "<locally generated id>",
  "device_secret": "<locally generated random secret>",
  "label": "Laptop"
}
```

The collector must persist its ID and random secret before sending this request. Secrets use 32–256 URL-safe alphanumeric, underscore or hyphen characters. The response is the device view; the secret is never returned. The device keeps the Owner's invitation label; an optional client label does not rename it. Claiming an invitation and creating its device happen in one SQLite transaction. A retry with the same device ID and secret retrieves the enrollment's current status even after the invitation expires, unless the invitation or device was revoked. Changing the client's hostname does not change its identity. Another device or a conflicting secret gets `409 invitation_already_claimed`. Unused expired invitations get `410 invitation_expired`.

Device requests use `Authorization: Bearer <device_secret>`:

| Method and path | Request / result |
| --- | --- |
| `GET /v1/device/policy` | Device view with current status and policy; paused devices can poll |
| `POST /v1/device/snapshots` | Raw snapshot JSON plus `X-Content-SHA256`; returns the manifest and `duplicate` |

Snapshots use `schema: "pneuma.material.agent-session/v1"` and `converter_version: 3`. The shared Python decoder defines the material shape. `snapshot_id` and `material_id` are lowercase SHA-256 hex identifiers. The transport digest covers the exact uploaded UTF-8 bytes, including origin metadata, and must be recomputed by the downloader before processing. If present, `origin.device_id` must equal the authenticated device. The server does not treat a device's reported origin as a cryptographically verified account or repository identity.

A manifest contains `{snapshot_id,material_id,library_id,device_id,sha256,bytes,committed_at,sequence}`. Pagination uses a monotonically increasing committed sequence, not object names or upload timestamps. `next_cursor` is always returned, including at an empty tail; persist it and use `has_more` to decide whether to fetch another page immediately. Advance the local durable checkpoint only after the local application has durably accepted its delivery.

## Storage and failure behavior

Objects are scoped by the authenticated library and device:

```text
libraries/{library_id}/devices/{device_id}/snapshots/{snapshot_id}/snapshot.json
libraries/{library_id}/devices/{device_id}/snapshots/{snapshot_id}/manifest.json
```

The same normalized material may appear on multiple devices with different origin metadata. Each observation has its own immutable object; downstream material/project merging does not erase device provenance.

A snapshot ID is reserved against its exact digest before writing R2. Both objects use conditional creation and cannot overwrite an existing object through this API. Identical retries return the original delivery (`duplicate:true`); conflicting bytes return `409 snapshot_conflict`. A manifest is written only after its snapshot exists. A delivery enters the list only after both R2 objects exist and a SQLite commit assigns its sequence. Consequently, a slow upload cannot arrive behind a cursor that already acknowledged a faster upload.

Failure before the final commit can leave an unlisted R2 object or pending reservation. The collector keeps its outbox entry and retries the identical bytes to finish delivery. This is retryable delivery with deduplication, not an atomic transaction between R2 and SQLite or a promise of exactly-once local ingestion. Registry state and R2 both belong in an installation backup. The committed list is not automatically reconstructed from R2 after loss of the registry.

Credentials and invitations are stored as hashes. Revocation rejects subsequent requests immediately and is checked again before an in-flight upload commits. Paused devices cannot upload; revoked devices cannot poll or enroll again using the old invitation. Previously committed snapshots remain available to the Owner.

The first release accepts snapshots up to **8 MiB**, counts bytes while reading even without `Content-Length`, and allows at most two uploads to buffer concurrently per installation (`429 upload_busy` is retryable). `MAX_SNAPSHOT_BYTES` can lower this limit. Oversized sessions receive `413 body_too_large`; the collector must retain/report them rather than truncate or mark them uploaded. Larger-session transport needs a future multipart protocol. Control requests are limited to 16 KiB. The Owner's device/invitation listings show at most 1000 entries each; snapshot listing is fully paginated.

## Local end-to-end harness

`tests/dev-server.mjs` starts the production Worker on loopback using synthetic local bindings and a frozen copy of the built assets. Supply a synthetic `HOST_TOKEN` in the environment and optionally `COLLECTOR_TEST_PORT` (default 48738). It prints the ready URL and a hash of the exact Worker bundle. Stop it with SIGINT or SIGTERM. It never imports a real knowledge tenant or deploys to Cloudflare.

Implementation references: [Workers best practices](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/), [SQLite Durable Object transactions](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/), [R2 conditional operations](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/), and [streamed Request/Response RPC](https://developers.cloudflare.com/workers/runtime-apis/rpc/).

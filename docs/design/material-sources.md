# Material sources and shared processors

**English** | [简体中文](material-sources.zh-CN.md)

The personal edition accepts coding-agent sessions from this computer and from other
computers through the same material feed. One host still owns the library, its middleware
and its canonical writer. Remote collectors publish observations; they never run a second
knowledge engine or write canonical. This extends the collection boundary of the
[single-machine edition](single-machine-edition.md#16-application-owned-increments-and-resident-sync).

## 1. The application boundary

```
local logs ── shared scanner/decoder ── LocalFeed ────────────────┐
                                                               │
remote logs ── same scanner/decoder ── durable outbox ── R2 ── SnapshotFeed
                                                               │
                          shared agent-session processor ◀───────┘
                              │ incremental source contracts
                              ▼
                 ordinary ingest → L0 + jobs → citation gate
```

A **source** chooses where material is obtained. A **processor** chooses how a material
type becomes an intake contract. Codex and Claude Code are two input decoders for the
same `agent-session` processor. R2 is a storage adapter, not a processor or an authority
over knowledge. The framework's six provider-neutral source contracts remain its input
boundary; the material feed lives upstream in `personal/`.

`LocalFeed` and `SnapshotFeed` enter the same incremental loop in
`personal/skill/scripts/agent_sessions.py`. Local reads retain their raw-prefix check;
remote reads validate normalized snapshots without opening the publisher's paths. The
shared loop owns triage, held increments, splits, continuation links and the exact
`sync-pending` journal. Only ordinary `pkc ingest` writes L0. Official contract intake now
commits source rows, blocks and all required index/compile jobs in one PostgreSQL
transaction. A lost response can therefore be retried without leaving a source whose
processing was never queued. Historical orphaned imports are not silently recompiled.

## 2. Material protocol v1

`pneuma.material.agent-session/v1` is a complete snapshot of the decoder's **retained**
session, not a final ingest contract. It contains:

- `schema`, `converter_version`, `material_id`, `snapshot_id`;
- `session`: provider, native session ID, original project path, model, subagent/conflict
  flags, retained turns, last activity and deterministic decoder counters;
- `origin`: original log path, credential-free primary git remote, and device observations.

The decoder keeps Owner statements, agent narrative and bounded action stubs. It does
not transmit raw harness records, tool bodies, reasoning, injected instructions or a
model-generated summary. Material IDs identify the provider/native conversation;
snapshot IDs hash the canonical normalized session and decoder version. Origin fields
do not change that content identity. The transport separately hashes the exact uploaded
bytes, so retrying the same device/snapshot with altered origin bytes is a conflict.

Original paths are provenance labels on the host. A cache path, container mount or
receiving computer's home never becomes the session's identity. Snapshot validation
checks the schema/version, digest, turn IDs, role/kind pairs, timestamp order and action
stub bounds. Unsupported versions are refused; they are not interpreted as a newer v1.

## 3. Durable delivery

The reference cloud service is in [apps/collector-cloud](../../apps/collector-cloud/README.md):
a Worker, one Owner-scoped SQLite Durable Object, and the Owner's private R2 bucket.
Both computers make outbound HTTPS requests. There is no requirement to expose the host
or to keep it awake while a remote computer collects sessions.

The device generates and durably saves its random credential before claiming a ten-minute
invitation. Claiming is atomic. A lost claim response is retryable with the same device
ID and credential; another claimant is refused. Host credentials never enter the one-line
invitation, browser read responses or device configuration. Cloud API credentials are
hashes in the registry; R2 account credentials are never distributed to devices.

The collector writes exact snapshot bytes into its local outbox before upload. A cloud
receipt must match the snapshot, exact digest, library, device and committed sequence
before the outbox entry is removed. R2 body and commit manifest are written before the
registry exposes a sequence. In-flight and failed writes are absent from listing. Retry
repairs an incomplete write, and conflicting bytes cannot overwrite an immutable object.
The sequence advances when a write commits, so a slow writer cannot be skipped by a
faster writer's receipt. Upload commit rechecks device authorization.

Before sending queued material, the collector checks the latest project, harness, history
and exclusion policy again. Newly excluded entries keep their original bytes locally,
are counted as held and receive no acknowledgement; other authorized entries continue.
Restoring their authorization allows the same bytes to be retried later.

Host listing is paginated by committed sequence. Every verified revision is placed in a
durable processing queue; fetching advances only the download cursor. Processing advances
its own cursor. Each device's latest snapshot remains available after observation,
including held sessions. Multiple devices' origins remain distinct while the processor
deduplicates their shared retained history. A provably older copy is reported as stale;
a same-device history rewrite or conflicting history is refused. Removing cloud objects
never deletes imported L0 or canonical.

Paused devices retain their outbox and stop scanning when they receive the policy.
Revocation is terminal: the cloud refuses further reads of device policy and uploads,
and the collector stops scanning when it receives that refusal. During a network outage
an active collector may continue scanning its last authorized scope into its local outbox.
An unavailable cloud source does not stop local processing or replay of previously
downloaded material. A cloud receipt means stored delivery, not completed compilation.

## 4. Host configuration and remote installation

The console's Home view has a collection section. The Owner connects the deployed cloud
URL and host token once, names a device and reviews its project/harness/history scope.
The result is one expiring command, or the same command inside a prompt for an AI on the
target computer. The UI does not pretend to have used a model to infer scope. The target
AI executes the installer and checks the service; it is not the resident collection loop.

The installer verifies release assets and installs a user-level macOS LaunchAgent or
Linux systemd service. It uses Python 3.10+ or installs managed Python through uv when
needed. No Docker, model key or knowledge database is required on a collector. Custom
harness roots discovered in the installing shell are retained for background execution.
Automatic discovery continues to use the same Codex/Claude/Orca rules as local sync.

Project scope is `all` or exact **absolute paths on the target computer**. It does not
implicitly include descendants. `since` selects sessions whose retained activity reaches
the stated timezone-aware boundary; admitted sessions retain their full context. It does
not erase earlier turns. Scope and exclusions are passed to the shared scanner. An empty
or invalid scope never widens to `all`.

`/home/collection/*` belongs to the personal application and is bound to the serving
engine's library. The credential/configuration face refuses cross-origin and non-loopback
browser access. `collection.json` is private mode 0600; host credentials are write-only
through the console. Local on/off writes only `local_enabled`. Older per-project harness,
date and recursive watch rules survive toggling unchanged; replacing heterogeneous rules
is an explicit advanced configuration action. Processor changes rejudge unacknowledged
increments even when the material bytes have not changed.

## 5. Stable projects and device provenance

The host assigns an opaque `project_id`. Equivalent SSH/HTTPS forms of the **primary
origin** map to the same repository. Host names normalize; repository paths are compared
conservatively. A fork with a different origin remains separate. Reusing a directory for
a different known repository does not silently merge it with its previous occupant.
Projects with no remote remain bound to their device and original directory.

The application keeps collection observations outside evidence hashes in
`collection-observations.jsonl`. They bind native sessions, project IDs, devices, original
paths and resulting source IDs. `collection-projects.json` is a disposable projection
replayed from those observations; rebuilding never reassigns an existing ID. Observations
are written before ingest so a worker cannot outrun project attribution.

The application's `collection-projects` component supplies a mechanical project identity
line through the framework's existing `source_preamble` seam. Its `prepare` loads one
tenant's bindings, and `rebuild` replays the kept records. It has no canonical write face.
The engine, `pkchome exec -- pkc`, and the managed library `bin/pkc` register the same
component; skill installation and verification use that entry too. Per-job source aliases
are never used as persistent lookup keys. These observations group source context; they
do not concatenate sessions, rewrite historical L0, or bypass the citation gate.

The source page and citation drawer expose these associations as **collection records**
through the optional personal endpoint
`GET /home/collection/sources/{source_id}?user_id={user_id}`. The engine rejects a different
tenant before reading any records. Only locations in rows associated with this source are
returned; another session in the same repository does not add its devices to the result.
These rows establish session observations, not exclusive importing devices: an observed
copy may refer to source IDs from earlier increments. Their timestamps are record times,
not upload times or the device's last contact. A missing record never implies local origin.
Current friendly device names use a disposable, library/cloud-bound
`collection-device-labels.json` cache containing only IDs and labels. Registry outages
preserve the kept associations. Historical console snapshots omit current collection
records rather than presenting them as historical facts.

## 6. Compatibility and current limits

Old local watch configuration, source IDs, successful cursors, held increments and exact
pending payloads remain usable. Verified legacy byte prefixes lazily gain normalized
baseline references under `sync-materials/`; transcript text never enters sync-state.
Unverifiable history remains a reported rewrite. A dry run creates no download cache,
observation or ingest state.

The first reference implementation handles agent sessions, one shared editable processor,
macOS and Linux with a functioning user service manager. It limits each normalized snapshot
to 8 MiB and reports oversize sessions without truncating or acknowledging them. It uses
polling (device default five minutes, host's existing sync schedule); notifications and
generic document/image collectors are separate extensions. On Linux, persistence after
logout depends on the account's systemd user/linger configuration. The host owns compilation,
so host sleep delays import and compilation while remote collection and cloud storage can
continue. A library remains one authoritative engine; this is not multi-master library sync.

## 7. Validation

Synthetic tests cover local/remote contract equivalence, old-cursor migration, held and
rewritten histories, repeated/delayed turns, partial JSONL, split retries, multi-device
provenance, independent cursors, project replay and tenant refusals. PostgreSQL tests inject
faults between source/block/job writes and race duplicate imports. Cloud tests exercise
real local SQLite DO/R2, invitation races, authorization, conflicting uploads, partial
publication repair, sequence ordering and in-flight revocation. Native-to-cloud-to-host
integration uses synthetic Codex and Claude logs; production data and cloud deployment
are not part of that test.

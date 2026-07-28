# pneuma-knowledge-compiler on GKE

Deployment target: GKE Autopilot, project `your-gcp-project`, region `asia-east1`,
public domain `pneuma-knowledge.example.com` (Cloudflare-fronted).

## Shape

```
Cloudflare (TLS, Proxied)  →  LoadBalancer :80  →  pneuma-knowledge-web (nginx, 2 replicas)
                                                      ├── /            → SPA (static)
                                                      └── /v1, /healthz → pneuma-knowledge-api
                                                                            │
                                    pneuma-knowledge-app pod (1 replica, Recreate) ──┘
                                      ├── container: api    (uvicorn :8080)
                                      └── container: worker (compile loop)
                                            └── shared PVC /data/canonical (RWO)

                              backing: postgres · qdrant · meilisearch (StatefulSets)
```

Two images, both from this repo:

| Image | Dockerfile | Contents |
|---|---|---|
| `pneuma-knowledge` | `docker/Dockerfile` | Python 3.12 + uv + **git**; runs API *or* worker by `command:` |
| `pneuma-knowledge-web` | `docker/web.Dockerfile` | pnpm-built Vite SPA served by nginx + `/v1` proxy |

## Decisions worth knowing

- **API and worker share one pod.** Both touch the per-user canonical git repos — the
  worker writes, the API reads (`/dataset`, `/snapshots`, recall). The PVC is
  ReadWriteOnce, so they cannot be split across Deployments without a ReadWriteMany
  Filestore volume (~1TiB minimum). Single-writer safety still comes from the Postgres
  queue's per-user `FOR UPDATE SKIP LOCKED` claim, not from colocation.
- **`Recreate`, not rolling update.** A rolling update would deadlock waiting to attach the
  PD to a second node while the old pod holds it. Rollouts have a brief downtime window.
- **nginx proxies `/v1` same-origin.** This reproduces the dev-time vite proxy, so
  `VITE_API_BASE` stays empty and there is no CORS surface and no build-time API URL.
- **Origin is plain HTTP:80.** Cloudflare terminates TLS (Flexible SSL). The DNS record
  **must be Proxied / orange-cloud** — a grey-cloud DNS-only record yields
  `ERR_CONNECTION_CLOSED`.
- **The image keeps the repo source layout.** `adapters/postgres.py` resolves
  `infra/schema.sql` via `Path(__file__).parents[5]`. Installing the wheel alone breaks
  every process at boot — hence `uv sync` + the whole repo copied in.
- **`git` is installed in the runtime image.** The canonical store shells out to it.
- **Slow, network-dependent boot.** `build_context()` applies the schema, then probes the
  embedding dim with a **real OpenRouter call**, then connects Meili and Qdrant. The pod
  will not serve until all four are reachable — hence a 5-minute `startupProbe` budget.
- **Embedding dim is load-bearing.** `PNEUMA_KNOWLEDGE_EMBEDDING_MODEL` must stay
  `openrouter:openai/text-embedding-3-small` (1536) to match the preset bundles'
  `manifest.json`; a mismatch makes the shared Qdrant collection dim conflict on import.

## Deploy from scratch

```bash
PROJECT=your-gcp-project
REGION=asia-east1
CLUSTER=<cluster-name>          # gcloud container clusters list

gcloud config set project "$PROJECT"

# 1. Artifact Registry repo (once)
gcloud artifacts repositories create pneuma-knowledge \
  --repository-format=docker --location="$REGION"

# 2. Reserve the public static IP (once)
gcloud compute addresses create pneuma-knowledge-web --region="$REGION"
gcloud compute addresses describe pneuma-knowledge-web --region="$REGION" --format='value(address)'
#   → put this in overlays/test/kustomization.yaml (loadBalancerIP)
#   → and point pneuma-knowledge.example.com at it in Cloudflare

# 3. Build + push both images
gcloud builds submit --config cloudbuild.yaml --substitutions=_TAG=v1 .

# 4. Cluster credentials
gcloud container clusters get-credentials "$CLUSTER" --region="$REGION"

# 5. Namespace + secret (out-of-band; never committed)
kubectl create namespace pneuma-knowledge --dry-run=client -o yaml | kubectl apply -f -
PGPASS='<generate>'
MEILIKEY='<generate>'
kubectl -n pneuma-knowledge create secret generic pneuma-knowledge-secret \
  --from-literal=OPENROUTER_API_KEY='sk-or-v1-...' \
  --from-literal=PNEUMA_KNOWLEDGE_MEILI_KEY="$MEILIKEY" \
  --from-literal=POSTGRES_PASSWORD="$PGPASS" \
  --from-literal=PNEUMA_KNOWLEDGE_PG_DSN="postgresql://pneuma_knowledge:${PGPASS}@postgres.pneuma-knowledge.svc.cluster.local:5432/pneuma_knowledge"

# 6. Apply
kubectl apply -k deploy/gke/overlays/test
kubectl -n pneuma-knowledge rollout status deploy/pneuma-knowledge-app --timeout=10m

# 7. Seed the bundled synthetic preset (keyless — ships its own vectors)
bash scripts/gke-seed-presets.sh
```

## Verify

```bash
IP=$(kubectl -n pneuma-knowledge get svc pneuma-knowledge-web -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl -s "http://$IP/healthz"                       # {"status":"ok","version":"0.6.0"}
curl -s "http://$IP/v1/users"                      # includes u-opc-lin
curl -s "http://$IP/" | head -5                    # SPA shell
```

## Routine operations

```bash
# Redeploy a new image tag
gcloud builds submit --config cloudbuild.yaml --substitutions=_TAG=v2 .
(cd deploy/gke/overlays/test && kustomize edit set image \
  REGION-docker.pkg.dev/PROJECT/REPO/pneuma-knowledge=asia-east1-docker.pkg.dev/your-gcp-project/pneuma-knowledge/pneuma-knowledge:v2)
kubectl apply -k deploy/gke/overlays/test

# ConfigMap-only change — kustomize has no configmap hash suffix here, so restart manually
kubectl -n pneuma-knowledge rollout restart deploy/pneuma-knowledge-app

# Logs
kubectl -n pneuma-knowledge logs -f deploy/pneuma-knowledge-app -c api
kubectl -n pneuma-knowledge logs -f deploy/pneuma-knowledge-app -c worker

# Rebuild derived layers (L1/L2/L3) after wiping middleware or changing embedding dim
kubectl -n pneuma-knowledge exec deploy/pneuma-knowledge-app -c api -- python examples/rebuild_derived.py --all
```

## Gotchas

- An expired local gcloud token makes `kubectl` return **empty results** for reads with the
  error only on stderr — it looks like "the secret is empty" rather than an auth failure.
  Re-auth with `gcloud auth login`.
- `spec.loadBalancerIP` is deprecated in k8s 1.24+. GKE still honors it; the modern form is
  the `networking.gke.io/load-balancer-ip-addresses` annotation. Latent migration.
- Verify the public HTTPS URL from a phone or with `curl --resolve`, not the dev browser,
  if you run a local DNS rewriter.

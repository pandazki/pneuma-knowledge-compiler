#!/usr/bin/env bash
# Import the bundled OPC preset (examples/README.md "预制数据集") into the GKE stack.
#
# Runs INSIDE the running app pod via kubectl exec rather than as a separate k8s Job,
# because the import writes canonical git repos to the ReadWriteOnce PVC that the app pod
# already holds — a Job pod could not attach the same disk.
#
# Keyless: the bundles ship their vectors, so this never calls an embedding provider.
# Idempotent: each friendly user is fully wiped across all four layers before load.
#
#   bash scripts/gke-seed-presets.sh             # import every bundled preset
#   bash scripts/gke-seed-presets.sh u-opc-lin   # import the OPC preset explicitly
set -euo pipefail

NS="${PNEUMA_KNOWLEDGE_NAMESPACE:-pneuma-knowledge}"

POD="$(kubectl -n "$NS" get pod \
  -l app.kubernetes.io/name=pneuma-knowledge,app.kubernetes.io/component=app \
  -o jsonpath='{.items[0].metadata.name}')"

if [[ -z "$POD" ]]; then
  echo "no pneuma-knowledge app pod found in namespace $NS" >&2
  exit 1
fi

echo "==> importing presets into pod $POD (ns=$NS) ${*:-[all]}"
kubectl -n "$NS" exec "$POD" -c api -- \
  python examples/import_presets.py "$@"

echo
echo "==> verifying via the API"
kubectl -n "$NS" exec "$POD" -c api -- \
  python -c "
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8080/v1/users') as r:
    print(json.dumps(json.load(r), ensure_ascii=False, indent=2))
"

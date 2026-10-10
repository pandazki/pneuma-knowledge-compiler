#!/bin/sh
# A user-level bootstrap. Long-lived credentials are created on the target computer.
set -eu
umask 077
pkc_cloud_url=''
pkc_invite=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --url) pkc_cloud_url="$2"; shift 2 ;;
    --invite) pkc_invite="$2"; shift 2 ;;
    *) printf '%s\n' 'Unknown collector install option' >&2; exit 2 ;;
  esac
done
[ -n "$pkc_cloud_url" ] && [ -n "$pkc_invite" ] || { printf '%s\n' 'Missing URL or invitation' >&2; exit 2; }
case "$pkc_cloud_url" in
  https://*|http://127.0.0.1:*|http://localhost:*) ;;
  *) printf '%s\n' 'Collector URL requires HTTPS' >&2; exit 2 ;;
esac
pkc_python=''
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
  pkc_python=$(command -v python3)
else
  pkc_uv=$(command -v uv || true)
  if [ -z "$pkc_uv" ]; then
    curl -fsSL https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
    pkc_uv="$HOME/.local/bin/uv"
  fi
  "$pkc_uv" python install 3.12
  pkc_python=$("$pkc_uv" python find 3.12)
fi
pkc_stage=$(mktemp -d)
trap 'rm -rf "$pkc_stage"' EXIT HUP INT TERM
curl -fsSL --max-redirs 0 "$pkc_cloud_url/collector.py" -o "$pkc_stage/collector.py"
curl -fsSL --max-redirs 0 "$pkc_cloud_url/release.json" -o "$pkc_stage/release.json"
"$pkc_python" -c 'import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); expected=json.loads((p/"release.json").read_text())["files"]["collector.py"]; actual=hashlib.sha256((p/"collector.py").read_bytes()).hexdigest(); sys.exit(0 if actual == expected else "Collector bootstrap digest mismatch")' "$pkc_stage"
"$pkc_python" "$pkc_stage/collector.py" install --url "$pkc_cloud_url" --invite "$pkc_invite"

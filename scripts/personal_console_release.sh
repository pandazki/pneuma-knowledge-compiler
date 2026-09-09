#!/usr/bin/env bash
# Publish the console dist as the release asset the personal edition downloads.
#
# The edition's wheel carries `pkc_personal/console/dist` only when it is built inside this
# repository with the artifact present; the README's one-line install builds from the git
# tree, where that directory is ignored. So the same directory is published once per edition
# version and fetched by `pkchome console install` (personal/src/pkc_personal/console.py).
#
# Usage: scripts/personal_console_release.sh [version]   # default: personal/pyproject.toml
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version="${1:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$root/personal/pyproject.toml" | head -1)}"
[ -n "$version" ] || { echo "cannot read the edition version" >&2; exit 1; }
tag="personal-console-v$version"
name="pkc-console-$version.tar.gz"

"$root/scripts/personal_console_dist.sh"
dist="$root/personal/src/pkc_personal/console/dist"
[ -d "$dist" ] || { echo "no console dist at $dist" >&2; exit 1; }

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
# One top-level entry, `dist/`, which is what the installer expects to find in the tarball.
COPYFILE_DISABLE=1 tar -czf "$staging/$name" -C "$(dirname "$dist")" dist
(cd "$staging" && shasum -a 256 "$name" > "$name.sha256")
echo "$name: $(find "$dist" -type f | wc -l | tr -d ' ') files, $(cat "$staging/$name.sha256")"

if gh release view "$tag" >/dev/null 2>&1; then
    gh release upload "$tag" "$staging/$name" "$staging/$name.sha256" --clobber
else
    gh release create "$tag" "$staging/$name" "$staging/$name.sha256" \
        --title "pkc personal console $version" \
        --notes "The built console page for pkc-personal $version; fetched by \`pkchome console install\`."
fi
echo "published $tag"

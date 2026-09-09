#!/usr/bin/env bash
# Build the console web (apps/web) and hand its dist to the personal edition as an ARTIFACT.
#
# The personal edition is an application over the library and never imports the console's
# source (docs/design/single-machine-edition.md §4.12); what it serves is a built `dist`.
# Inside this repository that artifact comes from this script; once the edition has a
# repository of its own it downloads the same directory from a release. The destination is
# git-ignored: nothing under personal/ names apps/web, and nothing built is committed.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="$root/personal/src/pkc_personal/console/dist"
(cd "$root/apps/web" && pnpm install --frozen-lockfile --silent && pnpm run build >/dev/null)
rm -rf "$dest" && mkdir -p "$(dirname "$dest")" && cp -R "$root/apps/web/dist" "$dest"
echo "console dist -> $dest ($(find "$dest" -type f | wc -l | tr -d ' ') files)"

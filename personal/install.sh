#!/bin/sh
# The pkc personal edition installer: one machine, one command, safe to re-run.
#
# It does six things in order — uv, the package, the `pkc` launcher, the harness skill,
# a Docker probe, the optional desktop app — and ends with a block addressed to the
# coding agent that ran it. Every step prints one `ok:` or `skip:` line; nothing is
# undone when a step stops the run, so a re-run continues from where it stopped.
#
# POSIX sh only: no bashisms, no `set -o pipefail`.
set -eu

# The release process pins these two. PKC_RELEASE overrides the ref for one install;
# PKC_SOURCE=/path/to/a/checkout/personal installs from a local checkout instead.
PKC_REPOSITORY="https://github.com/pandazki/pneuma-knowledge-compiler"
PKC_REF="${PKC_RELEASE:-main}"

QUIET=0
for argument in "$@"; do
    case "$argument" in
        -q|--quiet) QUIET=1 ;;
        -h|--help)
            printf 'usage: install.sh [--quiet]\n'
            printf '  PKC_RELEASE=<ref>     install that release instead of the default ref\n'
            printf '  PKC_SOURCE=<dir>      install from a local checkout of the edition\n'
            printf '  PKC_DESKTOP=1         also download the desktop app, when a build is published\n'
            exit 0 ;;
        *) printf 'unknown option: %s\n' "$argument" >&2; exit 2 ;;
    esac
done

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
complain() { printf '%s\n' "$*" >&2; }
# Print a path the way the README writes it, so the agent reads one shape everywhere.
tilde() { case "$1" in "$HOME"/*) printf '~%s' "${1#"$HOME"}" ;; *) printf '%s' "$1" ;; esac; }

# (1) uv --------------------------------------------------------------------------------
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PATH
if command -v uv >/dev/null 2>&1; then
    say "skip: uv already installed ($(command -v uv))"
else
    command -v curl >/dev/null 2>&1 || { complain "error: curl is needed to install uv"; exit 1; }
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    command -v uv >/dev/null 2>&1 || { complain "error: uv did not land on PATH; install it from https://docs.astral.sh/uv/ and re-run"; exit 1; }
    say "ok: uv installed ($(command -v uv))"
fi

# (2) the personal edition --------------------------------------------------------------
if [ -n "${PKC_SOURCE:-}" ]; then
    [ -d "$PKC_SOURCE" ] || { complain "error: PKC_SOURCE is not a directory: $PKC_SOURCE"; exit 1; }
    SPECIFICATION="$PKC_SOURCE"
    ORIGIN="$PKC_SOURCE"
else
    SPECIFICATION="pkc-personal @ git+$PKC_REPOSITORY@$PKC_REF#subdirectory=personal"
    ORIGIN="$PKC_REPOSITORY@$PKC_REF"
fi
if [ "$QUIET" -eq 1 ]; then
    uv tool install --quiet --force --reinstall "$SPECIFICATION"
else
    uv tool install --force --reinstall "$SPECIFICATION"
fi
say "ok: pkc-personal installed from $ORIGIN"

# (3) the pkc launcher, beside pkchome ---------------------------------------------------
PKCHOME="$(command -v pkchome || true)"
[ -n "$PKCHOME" ] || { complain "error: pkchome is not on PATH after installing; add $(tilde "$HOME/.local/bin") to PATH and re-run"; exit 1; }
BIN_DIRECTORY="$(dirname "$PKCHOME")"
LAUNCHER="$BIN_DIRECTORY/pkc"
# Our own second line is the marker: anything else at this path is somebody's command.
MARKER='exec pkchome exec -- pkc "$@"'
LAUNCHER_TEXT="$(printf '#!/bin/sh\n%s\n' "$MARKER")"
if [ -e "$LAUNCHER" ] && ! grep -Fqx -- "$MARKER" "$LAUNCHER" 2>/dev/null; then
    complain "refused: $LAUNCHER exists and is not ours — move it aside and re-run"
    exit 1
fi
if [ -f "$LAUNCHER" ] && [ "$(cat "$LAUNCHER")" = "$LAUNCHER_TEXT" ] && [ -x "$LAUNCHER" ]; then
    say "skip: pkc launcher already at $(tilde "$LAUNCHER")"
else
    STAGED="$LAUNCHER.install.$$"
    printf '%s\n' "$LAUNCHER_TEXT" > "$STAGED"
    chmod 755 "$STAGED"
    mv -f "$STAGED" "$LAUNCHER"
    say "ok: pkc launcher written to $(tilde "$LAUNCHER")"
fi

# (4) the harness skill ------------------------------------------------------------------
SKILLS=""
for HARNESS in "codex:.codex" "claude-code:.claude"; do
    BACKEND="${HARNESS%%:*}"
    DIRECTORY="$HOME/${HARNESS#*:}"
    if [ -d "$DIRECTORY" ]; then
        INSTALLED="$(pkchome skill install --backend "$BACKEND" --force)"
        SKILLS="$SKILLS$INSTALLED
"
        say "ok: $BACKEND skill installed at $(tilde "$INSTALLED")"
    else
        say "skip: no $(tilde "$DIRECTORY") — $BACKEND skill not installed"
    fi
done

# (5) Docker -----------------------------------------------------------------------------
if docker info >/dev/null 2>&1; then
    say "ok: docker reachable"
else
    complain "error: docker is not reachable (\`docker info\` failed)."
    complain "Install and start one of them, then re-run this installer — everything above is done and is not undone:"
    complain "  Docker Desktop  https://www.docker.com/products/docker-desktop/"
    complain "  OrbStack        https://orbstack.dev"
    exit 3
fi

# (6) the desktop app, when a build is published -------------------------------------------
# The release process pins this asset URL; empty means no build is published yet.
PKC_DESKTOP_ASSET="${PKC_DESKTOP_ASSET:-}"
if [ "${PKC_DESKTOP:-0}" = "1" ] && [ -n "$PKC_DESKTOP_ASSET" ]; then
    mkdir -p "$HOME/Applications"
    ASSET="$HOME/Applications/$(basename "$PKC_DESKTOP_ASSET")"
    curl -fsSL -o "$ASSET" "$PKC_DESKTOP_ASSET"
    say "ok: desktop app downloaded to $(tilde "$ASSET")"
else
    say "skip: desktop app not installed — \`pkchome tray\` says where to get it"
fi

# The block the agent reads: the harness may not reload its skills within this session.
[ "$QUIET" -eq 1 ] || printf '\n'
printf '== next (for the agent) ==\n'
if [ -n "$SKILLS" ]; then
    printf '%s' "$SKILLS" | while IFS= read -r INSTALLED_PATH; do
        if [ -n "$INSTALLED_PATH" ]; then
            printf 'skill installed: %s\n' "$(tilde "$INSTALLED_PATH")"
        fi
    done
else
    printf 'skill installed: none (no harness directory found; run: pkchome skill install --backend codex)\n'
fi
printf 'run: pkchome status\n'
printf 'then: pkchome setup --answers <file>   # see the skill'\''s "Cold start" section\n'

# PKC desktop

[简体中文](README.zh-CN.md)

A Tauri 2 menu-bar client for a personal knowledge home. The 360 × 520 panel has
Dashboard, Search and Settings panes. It reads `~/.pkc` (or `PKC_HOME`), probes the
machine itself, and overlays each engine's `/home/status` response. It never writes
home files: start, stop, restart, library selection, credentials and preferences go
through `pkchome`. Launch at login uses the operating system via Tauri's autostart plugin.

## Development

Use Node 22.13+ (Node 25 was used here), pnpm 11.21.0, Rust 1.88+, and the native
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/) for your platform.
Run these commands in this directory:

```sh
pnpm install
pnpm tauri dev
```

Click the book in the menu bar to open the panel. Escape, clicking outside, or the
close button dismisses it; quitting the tray leaves your libraries running. The
right-click menu offers Open PKC, Search and Quit. On Linux, where a desktop does
not expose tray geometry, opening uses the top-right corner of the active monitor.

For an isolated manual smoke, point `PKC_HOME` at an empty temporary directory before
launch; the icon should be grey and the panel should explain `pkchome setup`. Do not
run Start/Stop against a real home unless that is what you intend to operate.

```sh
PKC_HOME=/tmp/pkc-tray-smoke pnpm tauri dev
pnpm test
cd src-tauri
cargo test
cargo fmt --check
```

The bundled frontend needs the Tauri IPC bridge; `pnpm dev` alone serves assets but
cannot display live status. State is fetched from the Rust cache before the first
React render, then updated by events. Opening commits that cached DOM before showing
the native panel. There is no status spinner or HTTP request on the opening path.

## Build and release

```sh
pnpm run build
pnpm tauri build --debug
pnpm tauri build
# Regenerate platform icons from the source drawing:
pnpm tauri icon src-tauri/icons/app.svg
```

Artifacts go under `src-tauri/target/{debug,release}/bundle/`: macOS `macos/PKC.app`
and `dmg/*.dmg`, Windows `nsis/*-setup.exe` / `msi/*.msi`, Linux `deb/*.deb`,
`rpm/*.rpm` and `appimage/*.AppImage`, according to the host's installed bundlers.
Build on the target operating system. Signing, notarization and release publishing
are distribution steps; no signing identity or updater is configured here.

Install `PKC.app` in `~/Applications` or `/Applications`. `pkchome tray` opens the first
one it finds there, or prints the [release page](https://github.com/pandazki/pneuma-knowledge-compiler/releases).

Direct dependency versions are exact in `package.json` and `src-tauri/Cargo.toml`;
`pnpm-lock.yaml` fixes the frontend dependency graph. Native Tauri is 2.11.5,
Tauri build is 2.6.3, shell is 2.3.6, autostart is 2.5.1, and positioner is 2.3.4; the Rust set floats within those minors and `Cargo.lock` pins it.
macOS uses [tauri-nspanel 2.0.1 from its Tauri 2 branch](https://github.com/ahkohd/tauri-nspanel/tree/v2),
with accessory activation policy, a real NSPanel, and a template glyph plus a separate
colored dot. Tauri CLI 2.8.1's development version checker prints diagnostics for
Cargo's exact `=version` syntax; Cargo itself accepts those exact pins.

## Behavior and verification limits

- The Rust poller checks every 5 seconds, or 2 seconds while open; bounded probes can
  take longer when an endpoint times out. Docker and deep requests time out after
  2 seconds, TCP probes after 350 ms. Time passing alone emits no state event.
- Green means Docker, all four services and every engine are up. Amber means Docker
  answers but a service, engine or configuration needs attention. Red means Docker
  is unreachable. Grey means no `config.yaml` exists. Deep failures never change the icon.
- Fast recall posts to the current library tenant's `/v1/users/<tenant>/recall` with
  `mode: fast`. Canonical paths resolve through the public dataset to console document
  IDs. Source links retain source IDs and block numbers; unavailable document IDs
  remain plain text beside their source citations. No framework source is imported.
- Secrets enter a password field and reach `pkchome credentials set KEY --from-stdin`
  through stdin only. The command vocabulary is checked in Rust. Failed commands show
  stderr in a dismissible toast, with the submitted key redacted. No key is persisted
  in frontend storage or sent in argv. The installed CLI path is reread for each action;
  macOS resolves the login-shell PATH once at startup.
- Retry failed jobs is intentionally disabled with a tooltip. The optional global
  shortcut is not implemented. Fixed tray-anchored geometry needs no saved window prefs.
- In the implementation environment, the frontend build and five state/routing tests
  passed, icon generation passed, and CLI launch/fallback checks passed. Frontend
  packages were restored from a local pnpm 10 cache; build/test commands used pnpm 11.
  Native builds stopped before compilation because GitHub DNS was unavailable; no
  `Cargo.lock`, app bundle or installer could be produced. The nspanel branch revision
  therefore still needs locking with the first successful Cargo resolution.
- `pnpm tauri dev` stopped at `listen EPERM 127.0.0.1:1420`. No native GUI appeared,
  so tray anchoring, focus dismissal, appearance, autostart and real engine HTTP flows
  still need a desktop smoke on an unrestricted host. No plain-window fallback was
  selected: nspanel compatibility could not be evaluated before dependency fetching.

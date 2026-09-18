# PKC desktop

[简体中文](README.zh-CN.md)

A Tauri 3 developer-edition menu-bar client for a personal knowledge home. The 380-point-wide, content-sized panel has
Dashboard, Search and Settings panes. It reads `~/.pkc` (or `PKC_HOME`), probes the
machine itself, and overlays each engine's `/home/status` response. It never writes
home files: start, stop, restart, library selection, credentials and preferences go
through `pkchome`. Launch at login uses the operating system via Tauri's autostart plugin,
and is on by default: the first launch registers the app itself and records that it did, in
`login` inside `preferences.json` in the app's config directory. Any record — the app's own
default or the Settings toggle — ends the app's say, so login the Owner turned off stays off;
a registration the system refuses records nothing, and Settings shows the switch off with the
system's reason.

## Development

Use Node 22.13+ (Node 25 was used here), pnpm 11.21.0, Rust 1.95.0 (selected by `rust-toolchain.toml`), and the native
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/) for your platform.
Run these commands in this directory:

```sh
pnpm install
pnpm tauri dev
```

Click the book in the menu bar to open the panel. Escape, clicking outside, or the
close button dismisses it; quitting the tray leaves your libraries running. The
right-click menu offers Open PKC, Search, Call the library and Quit. On Linux,
where a desktop does not expose tray geometry, opening uses the top-right corner
of the active monitor.

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

Tauri, CLI and the Wry runtime are pinned to `3.0.0-alpha.1`; the build crate,
official plugins and JS API use `3.0.0-alpha.0`. Both lockfiles are committed.
The builder explicitly selects Wry; there is no CEF runtime or local dependency fork.

macOS uses accessory activation policy and the application's small `native_panel.rs`
adapter over AppKit. Tauri owns the existing window and webview; the adapter gives it
NSPanel behavior, checks main-thread access, and handles keyboard focus and resizing.
It does not retain or release the window and does not depend on `tauri-nspanel`.
The template glyph and separate colored status dot are preserved.

`tray-icon 0.25.1` contains the upstream macOS 27 click fix. Left clicks open the panel;
right clicks use the dependency's native menu. The application-level menu workaround
has been removed. This developer edition deliberately uses pinned Tauri 3 alpha releases.

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
- Call the library opens the current library's console at `#/steward?call=1` in your
  default browser, never in the panel: the panel's content security policy reaches `ipc:`
  alone, this bundle declares no microphone purpose, and a popover that hides on focus loss
  is no place to hold a conversation. Port and tenant are read from disk at the click, and
  the engine is asked whether it can place one (`GET /v1/users/<tenant>/call`). No current
  library, a stopped engine, a deployment with no voice key, or an engine older than the
  call opens the panel on Dashboard with the reason on its message line; the item is never
  greyed, because a disabled item cannot say which of those it was. Not exercised here
  against a running engine or a real browser.
- Retry failed jobs is intentionally disabled with a tooltip. The optional global
  shortcut is not implemented. Fixed tray-anchored geometry needs no saved window prefs.
- The Tauri 3 migration passes 29 frontend and 18 native tests and a release app build.
  On macOS 27, real mouse events verify the panel on left click, the menu on right click,
  and subsequent left clicks after closing the menu. The panel reads the running library's
  status. Other platforms, login-time launch and long-running behavior require separate checks.

## Continuing tasks and importing content

The dashboard names three different operations:

- **Continue now (N)** appears for delayed retries and paused jobs. After restoring quota,
  login or connectivity, it releases their waits and restarts the retry schedule, preserving
  job IDs and failure history. Running and finished jobs are untouched. Unattended compilation
  must be enabled for the worker to run agent compilation automatically.
- **Import new content** scans watched directories for new sessions and changes; it does not
  release queued retry waits.
- **Restart service** restarts all library engines and preserves scheduled retry times.

The queue shows delayed and paused counts and the next retry date/time in local time.
Continue uses the selected library's tenant-scoped `POST /jobs/resume` with
`include_waiting: true`. Update both tray and engine for this feature; an older engine is
reported explicitly rather than silently ignoring delayed tasks. The API and CLI retain
paused-only behavior unless the API explicitly requests waiting jobs as well.

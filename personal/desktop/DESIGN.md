# The console's pocket instrument

**English** | [简体中文](DESIGN.zh-CN.md)

A library Owner glances at a Mac menu bar at their reading desk, in daylight or lamplight. The tray belongs to the console's galley-proof world: warm paper, ink, hairlines, footnotes. It is quiet, bookish and exact. The confirmed context is [.impeccable.md](.impeccable.md); the console's own design document (its world and palette) informs it. All implementation and tokens live here, with no console imports.

## Surfaces and tokens

`src/styles.css` owns every colour of the native shell. The engine-owned Fold frame is scoped separately below. `color-scheme: light dark` and `light-dark()` follow system appearance. Paper and Lightbox are independently tuned. Neutrals share hue 85; muted text is darkened/lightened enough to remain readable. The blue pencil and health colours are conversions of the console's sRGB values. A health colour appears only on the small mark beside each library name; the native tray icon retains its existing contract. Opening the console hands that same face over as `?locale=` and `?theme=`, the theme read from the very `prefers-color-scheme` query `light-dark()` resolves against, so the browser does not re-guess a language the Owner has already chosen. Errors and failure details use words on the ordinary surface.

| Token | Paper · OKLCH | Lightbox · OKLCH |
|---|---|---|
| `--bg` | `0.965 0.006 85` | `0.20 0.006 85` |
| `--surface` | `0.985 0.004 85` | `0.235 0.006 85` |
| `--ink` | `0.22 0.01 85` | `0.92 0.006 85` |
| `--ink-2` | `0.43 0.012 85` | `0.78 0.008 85` |
| `--ink-3` | `0.52 0.014 85` | `0.68 0.008 85` |
| `--line` | `0.89 0.008 85` | `0.335 0.006 85` |
| `--line-2` | `0.76 0.012 85` | `0.46 0.008 85` |
| `--accent` | `0.47643 0.10777 264.094` | `0.73415 0.07007 264.398` |
| `--ok` | `0.51418 0.06226 154.166` | `0.69594 0.06217 154.381` |
| `--warn` | `0.54319 0.10958 75.410` | `0.74265 0.10709 80.130` |
| `--danger` | `0.49433 0.13535 31.926` | `0.69020 0.09652 33.445` |

Hover and active use the console's translucent ink overlays: 4%/7% on Paper, 5%/9% on Lightbox, via `color-mix(in oklch, var(--ink) …, transparent)`. No additional component colours.

## Type and readout grammar

- Serif: `"Alegreya", "Songti SC", "Noto Serif CJK SC", serif`. Headings, italic running heads and readout figures.
- Sans: `"Alegreya Sans", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", sans-serif`. UI, answers and source lines. Neither family falls back to the other.
- Fixed rem sizes: 11 / 13 / 15 / 20 / 28px equivalents. The 15→20→28 hierarchy exceeds 1.25; 11 and 13 are auxiliary footnote/metadata sizes. Chinese metadata uses 13, never 11. CJK adds 0.1 to the relevant line height and uses zero tracking. Mixed Chinese titles keep their full accessible name and wrap to two visible lines.
- Latin labels use `all-small-caps` with `0.04em` tracking; Chinese labels stay unchanged. Figures use `tabular-nums lining-nums`.
- Vendored Latin WOFF2: `alegreya-{normal,italic}-latin.woff2` (variable 400–900); `alegreya-sans-{300,400,500,700}-normal-latin.woff2` and `alegreya-sans-400-italic-latin.woff2` (static). The supplied Sans family uses real static weights. Every face has `font-display: block` and a Latin `unicode-range`; the four faces used at opening are preloaded. No runtime font fetch. The SIL Open Font License 1.1 texts are beside the fonts as `OFL-Alegreya.txt` and `OFL-Alegreya-Sans.txt`, also linked into the build.

A readout is `label ………… value`, a definition-list row with a decorative dotted leader. Engine, Queue, Last compile, Sync, Key and Skill remain in that order. Queue successes (`queue.succeeded`), pending work and failures stay distinct; failure kinds sit beneath in ink-3. Held sync increments are never queue counts. An unknown or incomplete readout is one `—`, with no unit or status words attached; known zero counts and an observed absence of earlier work stay meaningful. Current library comes first; deep observations never come from its sibling engine. Chinese calls Skill `skill 包`; language still follows the system until explicitly chosen.

## Control grammar

Settings reads `label ………… control`, with ink values and `appearance: none`. Selects have no box and a CSS chevron drawn with 1px strokes; the open list is the page's own listbox (paper on paper, a hairline edge, one soft ink shadow), right-aligned under the value, flipping upward near the panel's bottom edge, with the chosen entry marked by an accent dot. It is portalled to the body because the settle animation leaves a transform on `main`. The trigger keeps focus and drives the list from the keyboard (arrows, Home/End, type-ahead, Enter, Escape). Hover tints the whole row with the console's hover overlay; focus draws a 1px accent hairline beneath the value. The interval is a bare tabular number followed by its unit, with ghost −/+ buttons and the existing Save action. A switch shows both on/off words (localized), the selected word in ink and the inactive word in ink-3, separated by a 1px hairline; it retains switch semantics and its setting label. Password and text fields use a bottom hairline with no box or fill, and the secret remains a real password input. Search has no box or fill: its only focus mark is the header's 1px accent hairline and the caret, with an Alegreya Sans placeholder in ink-3.

## Composition and interaction

The panel initially opens at 920×820; content fitting then clamps height to 280–820 points. A 44px borderless search field is pinned above the scrolling body, with a magnifier, localized prompt and ⌘K hint. Content uses 16px vertical / 20px horizontal padding, 32px readout rows, and 24px plus a hairline between sections. The body has `min-height: 0` and shrinks to its content: the machine hairline, health line and footer follow short content directly. When content exceeds the available height, including two libraries, only the body scrolls; search and footer remain pinned. Down services have a dot. Five setup words keep their order and middots: done words use ink, undone words use ink-3 with a 1px dotted underline, and the first undone word has the accent hairline.

Typing shows results after a short debounce; Chinese composition completes before a search is sent. Answers are plain text with numbered superscript citations, followed by source entries. ⌘K focuses search; Escape clears a query, then closes. Up/down moves through citation links; Enter opens the focused citation (or the first one from the field). Controls use the focus hairlines above; other buttons and links retain a 2px accent focus ring with 2px offset.

Settings is a footer text link and uses the control grammar above. Directory removal appears on hover or keyboard focus. A stored embedding key is a readout, not a waiting field: the credential's name, when it was saved, and what has been proved about it — verified by the running engine (startup is fail-closed, so a live engine with semantic retrieval on is the provider's own verdict), stored but unverified while the engine is down, or stored and unused while semantic retrieval is off. Replace reveals the name and secret fields; Cancel collapses them, and a successful save collapses them too. An unknown key is one `—`. Secret fields never reveal a key, clear on submission and unmount on dismissal; a rejected credential states the provider's own reason, with every occurrence of the submitted value replaced by `•••` before the message leaves the Rust side. Compile unattended states the consequence of switching it off. Launch at login is on from the first launch — the tray is this edition's sync, and a tray that does not come back after a reboot is a library that has quietly stopped listening — and the line under the switch says so plainly; the app decides once and records it, the Owner's later choice is final and is never re-made for them, and a registration the system refused reads as the switch off with the system's own reason in that line, never as a success nobody was given. Actions are ghost text; only Start receives primary accent while an engine is off. Start/Stop/Restart still act on the entire home.

The footer shows checked time or a fading one-line status, with Settings and Quit alongside. Opening uses the cached state and the existing `setTimeout` reveal handshake. Content settles once in 120ms with opacity and a 2px rise, `cubic-bezier(0.22, 1, 0.36, 1)`; live row updates do not animate. Reduced motion disables animation. Empty homes show a short paragraph and a sentence to paste into a coding agent; stopped engines and Docker failures retain the available readouts.

Banned: cards and card grids, tab bars, icons above headings, centred hero numbers, side stripes, gradient text, glow, decorative glass, bounces, purple/cyan palettes, runtime font services, and presentation that invents health or provenance.

Queue recovery is shown directly below its readouts when delayed or paused work exists: counts, the next local retry date/time, and **Continue now (N)**. Its help ties the action to restored quota, login or connectivity. The content action reads **Import new content** with a watched-directory explanation; **Restart service** explicitly retains retry times. Success reports the actual number resumed; failures use the existing message line.


## Attention extension

Fold extends this instrument with a long-view reading surface. The native shell identity
and bans above remain in force. The Owner-approved exception is scoped to the engine-owned
Fold frame: subdued identity hues, the original Fold C shaded WebGL drops, and the six-choice
visual settings gallery are allowed here. These do not authorize native shell cards or a
replacement palette. Product context is in [PRODUCT.md](PRODUCT.md); behavior and evidence
boundaries are in the [Fold design authority](../../docs/design/fold-attention.md).

### Layout and reading order

The native panel is 920 points wide, initially 820 high and fitted within 280–820 points.
Fold opens in a 650px-high scrolling iframe; its separate native settings embedding is
680px high. Library health follows in a disclosure, expanded when the engine is stopped.
The console embeds the same engine surface; neither application imports the other's source.
Local frame permission grants no native capabilities.

The board starts with view controls, actual dates and the visual field. Cited period
interpretation appears once in the reflection below, alongside evidence and supporting
threads. Keep factual labels, encoding keys, actual counts/status and necessary operational
help; omit slogans, introductory manifestos, copied design discussion and duplicate summaries.
Attention atlas is the starting preference; all six forms remain selectable and shared by
library. This default does not rank atlas as universally best or river as the product center.
Root themes describe continuing
projects, goals and questions; concrete events support them. Selecting a theme reveals its
reason, pinned evidence and notes. Child themes can be explored and the reader can return
to the macro view. Historical reviews remain read-only.

The frame uses a fluid column capped at 1400px with 24px side gutters; above 1100px the
gutters become 38px. At 600px and below they become 16px, reflection notes stack in one
column and the settings gallery changes from three columns to two. Wide charts scroll
horizontally inside their own field. At desktop widths with viewport height at most 750px,
header and control spacing compact to preserve the visual field. The saved-review time machine
is fixed at the frame's bottom with reserved content padding, reachable during reading and
settings. It steps, scrubs, plays, loads earlier saved rounds and returns to now. It is distinct
from the river's source-date axis and the console's canonical snapshot picker. No review
history is invented before the board existed.

### Colors and typography

`attention/web/board.css` owns this frame's tokens, independently of the native shell's
OKLCH tokens. Explicit theme follows the embedding surface; otherwise `light-dark()` uses
system appearance.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--paper` | `#f7f6ef` | `#242620` | Page and fixed time machine |
| `--surface` | `#fdfcf7` | `#2b2d26` | Fields and preview choices |
| `--ink` | `#233027` | `#e7eadf` | Primary text |
| `--muted` | `#626c60` | `#acb6a4` | Supporting text |
| `--line` | `#d4d8cc` | `#4b5345` | Hairlines and controls |
| `--accent` | `#416d60` | `#9bc8b7` | Evidence links, focus and selection |
| `--free` | `#edede3` | `#21241d` | Unallocated attention |
| `--wash` | `#e9ede3` | `#343c30` | Hover and selected previews |

Identity hues are `#5a9b8e`, `#c88d65`, `#a9a05b`, `#7899b4`, `#a88aad`, `#8ca37b`,
`#c47f84`, `#7a9f9f`, `#a7987b` and `#8995bd`. They follow stable identities across forms
and saved rounds, with a per-library browser color map. Visible projects receive color
priority before unrelated historical themes; additional muted hues are generated when the
base palette is exhausted. They encode identity, not health,
urgency or measured productivity; labels and evidence carry the meaning. Atlas areas mix
identity color with paper (25%, 35% on hover); the free region remains visibly unallocated.

Body type is 15px/1.6 `"Alegreya Sans", "PingFang SC", "Hiragino Sans GB", system-ui,
sans-serif`. Reading-section headings use weight 500 `"Alegreya", "Songti SC", Georgia,
serif` at 23px/1.35, becoming 21px on mobile. No introductory hero heading is rendered.
Atlas titles use the body family at weight 650; font size (13, 15, 17 or 21px) and line clamp
are calculated from each region’s dimensions. Compact regions omit repeated share metadata;
full titles and shares remain in accessible labels. Reflection paragraphs use 14px/1.9;
supporting controls and captions generally use
11–14px. These are local font fallbacks, not fonts inherited or downloaded from the shell.
The shell's bundled-font and unboxed-control rules remain unchanged.

### Six forms and their meanings

| Form | Visual contract |
|---|---|
| Project river (`river`) | Project bands use original source dates and period totals. A single-line keyed legend identifies projects without leader lines; mobile places the legend below the chart. Counts show recorded involvement, never work hours. Missing observations remain gaps; unavailable coverage is explicit. |
| Attention atlas (`space`) | Proportional theme areas use a finite 64-share budget, including actual free area. Stable layout transitions preserve orientation; select a region for details and child themes. |
| Living field (`drops`) | The original Fold C WebGL2 shader and layout solver render proportional themes; quieter themes become small beads. Bounded geometry interpolation, Canvas2D fallback and reduced-motion handling preserve access. |
| Review mosaics (`mosaic`) | Each 8×8 map is an actually saved review on the same 64-share scale, with its recorded date/time. Selecting one opens that review. |
| Thread lines (`lineage`) | Stable theme identities continue across saved rounds; width shows share, nodes show changes, gaps mark absence from the board. Diagonal joins require an explicitly recorded merge. |
| Give & take (`yield`) | Adjacent reviews show balanced released and gained shares, including free space, on one common scale. No donor-to-recipient causal pairing is implied. |

### Controls, depth and motion

Compact buttons/selects use thin borders, 3px corners and a 34px minimum height; text fields
use 2px corners. Focus uses a 2px accent outline with 3px offset. The gallery is a radio group
with six schematic previews, names and descriptions; selected previews use an accent edge
and wash. Settings and form choice are saved per library and shared by tray and console;
a changed look-back period takes effect on the next review.

Depth is mostly paper, hairlines and spacing. The fixed time machine has a soft paper-colored
edge shadow. Shaded drops and the small beads' inset highlights are the scoped material
exception. Reduced motion disables CSS transitions/animations and visual interpolation.
Evidence and explanatory labels remain available without relying on motion or color.
The surface records reflections and Owner context for the next review; it does not become
an immediate action inbox or claim that an absent observation proves inactivity.

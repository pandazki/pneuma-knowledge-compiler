# The console's pocket instrument

**English** | [简体中文](DESIGN.zh-CN.md)

A library Owner glances at a Mac menu bar at their reading desk, in daylight or lamplight. The tray belongs to the console's galley-proof world: warm paper, ink, hairlines, footnotes. It is quiet, bookish and exact. The confirmed context is [.impeccable.md](.impeccable.md); the console's [world and palette](../../apps/web/DESIGN.md) inform it. All implementation and tokens live here, with no console imports.

## Surfaces and tokens

`src/styles.css` owns every colour. `color-scheme: light dark` and `light-dark()` follow system appearance. Paper and Lightbox are independently tuned. Neutrals share hue 85; muted text is darkened/lightened enough to remain readable. The blue pencil and health colours are conversions of the console's sRGB values. A health colour appears only on the small mark beside each library name; the native tray icon retains its existing contract. Errors and failure details use words on the ordinary surface.

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

The panel is 380×560. A 44px borderless search field is pinned above the scrolling body, with a magnifier, localized prompt and ⌘K hint. Content uses 16px vertical / 20px horizontal padding, 32px readout rows, and 24px plus a hairline between sections. The body has `min-height: 0` and shrinks to its content: the machine hairline, health line and footer follow short content directly. When content exceeds the available height, including two libraries, only the body scrolls; search and footer remain pinned. Down services have a dot. Five setup words keep their order and middots: done words use ink, undone words use ink-3 with a 1px dotted underline, and the first undone word has the accent hairline.

Typing shows results after a short debounce; Chinese composition completes before a search is sent. Answers are plain text with numbered superscript citations, followed by source entries. ⌘K focuses search; Escape clears a query, then closes. Up/down moves through citation links; Enter opens the focused citation (or the first one from the field). Controls use the focus hairlines above; other buttons and links retain a 2px accent focus ring with 2px offset.

Settings is a footer text link and uses the control grammar above. Directory removal appears on hover or keyboard focus. Secret fields never reveal a key, clear on submission and unmount on dismissal; credential failures cannot echo their payload. Compile unattended states the consequence of switching it off. Actions are ghost text; only Start receives primary accent while an engine is off. Start/Stop/Restart still act on the entire home.

The footer shows checked time or a fading one-line status, with Settings and Quit alongside. Opening uses the cached state and the existing `setTimeout` reveal handshake. Content settles once in 120ms with opacity and a 2px rise, `cubic-bezier(0.22, 1, 0.36, 1)`; live row updates do not animate. Reduced motion disables animation. Empty homes show a short paragraph and a sentence to paste into a coding agent; stopped engines and Docker failures retain the available readouts.

Banned: cards and card grids, tab bars, icons above headings, centred hero numbers, side stripes, gradient text, glow, decorative glass, bounces, purple/cyan palettes, runtime font services, and presentation that invents health or provenance.

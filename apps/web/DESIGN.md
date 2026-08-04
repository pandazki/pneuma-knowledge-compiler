# apps/web · Design system

**English** | [简体中文](DESIGN.zh-CN.md)

The design authority for `apps/web`; the `§` references in source comments (`DESIGN.md §2.4`, `hard rule 4`, …) point here. Two files carry the same rules in executable form — `src/styles/tokens.css` (every colour) and `src/index.css` (prose, scroll regions, native-control resets) — and the hidden `#/components` route shows every primitive in every state. This page says what those decisions mean and which of them are load-bearing.

---

## 1. The world: a galley proof

An editor's desk with a galley on it. Paper, ink, hairlines, footnotes. The product's central promise — every claim returns to an exact source span — is a *footnote* in that world: a superscript number in the body, a provenance column in the margin. Three type roles carry the three layers of the product: sans for the editorial shell, serif for reading surfaces, mono for machine text. Structure comes from hairlines and whitespace rather than cards.

The vocabulary that recurs in code and copy: **footnote** (a citation marker), **marginalia** (flags and provenance beside the body), **§ numbering** (chapters and sections), **ruler lines / hairlines** (structure and diagrams), **archive stamp** (read-only, synthetic), **galley** (the compiled view of a source next to its original).

Why the metaphor holds:

1. **Narrative isomorphism.** Citation is a footnote, provenance is checking against the proof, a version is an edition, the citation gate is the proof-reader's red pencil. Every mechanism has a native expression; nothing decorative has to be invented.
2. **Texture through typography.** Editorial quality is built from type, spacing, hairlines and measure — which is inherently low-saturation and calm.
3. **Two real surfaces.** Light is ink on paper; dark is film on a lightbox. Two independently tuned surfaces, not one inverted.
4. **Anti-card.** Hairline sections, margins and numbered chapters replace card containers.

---

## 2. Design tokens (single source of truth)

Every colour lives in `src/styles/tokens.css` as CSS custom properties, mapped to Tailwind v4 utilities through `@theme inline` in `src/index.css`. **Components carry zero hex and zero `rgb()`/`hsl()` literals**; the only exceptions are tokens.css itself and `color-mix()` derivations from variables already defined there.

`lib/cn.ts` extends tailwind-merge with these token names — grouped colours with colours, sizes with sizes, radii with radii. Without that registration tailwind-merge reads `text-accent-ink` as a font size and drops it on merge, which is how the primary button once lost its colour.

### 2.1 Colour · light "Paper"

| token | value | use |
|---|---|---|
| `--bg` | `#f6f5f1` | page paper ground |
| `--surface` | `#fbfaf7` | reading surface / panel ground |
| `--raised` | `#ffffff` | overlays (popover / dialog / menu) |
| `--ink` | `#20201d` | primary text |
| `--ink-2` | `#57554e` | secondary text |
| `--ink-3` | `#8b887e` | muted text / placeholder |
| `--line` | `#e3e1d9` | hairline rule |
| `--line-2` | `#cfcdc3` | emphasized divider / control border |
| `--accent` | `#3d5a99` | blue pencil: links, selection, footnote numbers, focus |
| `--accent-ink` | `#fbfaf7` | text on an accent ground |
| `--ok` | `#4a7257` | a real success state |
| `--warn` | `#94650f` | a real warning state |
| `--danger` | `#a03d2c` | a real error state |

Derived shades come from `color-mix` over the variables above, never from a new hex: `--accent-soft` (accent 10% on bg, selected ground), `--accent-line` (accent 35%, selected border), `--hover` (ink 4%, as an overlay so it works over any ground), `--active` (ink 7%), and `--ok-soft` / `--warn-soft` / `--danger-soft` (10%).

### 2.2 Colour · dark "Lightbox"

Not an inversion: the ground is warmer, the ink slightly desaturated, and the hairlines still read as a layer.

| token | value |
|---|---|
| `--bg` | `#17171a` |
| `--surface` | `#1d1d21` |
| `--raised` | `#252529` |
| `--ink` | `#e8e6e0` |
| `--ink-2` | `#a6a39a` |
| `--ink-3` | `#6f6c65` |
| `--line` | `#2c2c31` |
| `--line-2` | `#3d3d44` |
| `--accent` | `#93a9d6` |
| `--accent-ink` | `#17171a` |
| `--ok` | `#7fa98c` |
| `--warn` | `#cfa458` |
| `--danger` | `#d08574` |

The dark derivations sit a few points higher than their light counterparts (12% for the soft grounds, ink 5%/9% for hover/active) because the same ratio reads weaker over a dark ground.

Contrast (WCAG 2.2 AA): body and control text ≥ 4.5:1, large text and icons ≥ 3:1, the focus ring against its ground ≥ 3:1. Both accents were chosen at body-text contrast.

### 2.3 Type

| token | stack | use |
|---|---|---|
| `--font-sans` | `system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif` | the editorial shell: navigation, buttons, forms |
| `--font-serif` | `"LXGW WenKai Screen"` (bundled, OFL), `"Songti SC"`, `"Noto Serif SC"`, `"Source Han Serif SC"`, Georgia, `"Times New Roman"`, serif | reading surfaces: canonical bodies, answers, source verbatim text, page titles |
| `--font-mono` | `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace` | machine text: ids, paths, git refs, lineage, block numbers, token counts |

The webfont is imported unicode-range-split in `index.css`, so the browser downloads only the glyphs in use and falls back to the system Song/serif face until it lands.

Scale (px): `12 / 13 / 14 / 16 / 20 / 24 / 30 / 38`. **12px is the floor for visible Chinese text**, reserved for footnotes and auxiliary metadata. Line heights are bound per size in the `@theme` block: 1.5 for UI sizes, 1.75 at 16 (body), 1.25 from 20 up (headings). Reading measure `--measure: 68ch`; content column `--content-max: 1080px`. Weights 400 / 500 / 650 — hierarchy is not built out of 700+.

Two things this rules out: long runs of uppercase + letter-spacing standing in for professionalism, and mono on Chinese body text, buttons or dropdowns (mono belongs to content that is genuinely monospaced-semantic).

### 2.4 The reading layer (`.prose`)

Every serif reading surface — answers, claim bodies, source verbatim text, quoted spans, suggestion card bodies — goes through `.prose` / `.prose-lede` in `index.css`. The rules follow [kami](https://github.com/tw93/kami)'s print typography discipline; most of them are the kind you only learn by getting them wrong once:

- On-screen CJK line height 1.65 (body) / 1.7 (lede), with density-compensating `letter-spacing` 0.015em / 0.03em. That is the breathing room a Kai face needs at screen sizes, not decorative tracking.
- `strong` is pinned to 500. LXGW WenKai ships one weight, and browsers asked for 700 synthesise a smeared fake bold.
- Inline `code` resets `letter-spacing` to 0 — the CJK compensation would loosen a mono run.
- Heading proximity: space above ≥ 2× space below. Headings take `text-wrap: balance`, body text `pretty`.
- Native list markers, inked accent. Quotes are a 2px accent left rule + ink-2. `pre` is padded and frameless. Tables are frameless with hairline rows, ink-2 headers and tabular-nums. Links are accent with no underline, deepening toward ink on hover.
- Diagram labels and metric numbers use serif + tabular-nums, not mono.

`.prose` is a component-layer class, so callers override size and colour with utilities (`text-14`, `text-ink-2`). A reading surface should not re-spell `font-serif leading-[1.65] tracking-[0.015em]` inline.

### 2.5 Space, shape, motion — and scrolling

- **Spacing**: 4px baseline — `4 / 8 / 12 / 16 / 24 / 32 / 48 / 64`.
- **Radius**: `--r-1` 2px (small controls), `--r-2` 4px (inputs, buttons), `--r-3` 8px (overlays). Near-square is the editorial signal; pill and bubble radii are not part of the system.
- **Shadow**: overlays only (`--shadow-overlay`, deepened in dark). Content areas separate with hairlines instead of shadows and cards.
- **Motion**: `--dur-1` 120ms / `--dur-2` 200ms, `ease-out`; fade or a 2–4px shift, nothing else. Under `prefers-reduced-motion: reduce` every animation and transition is zeroed in the base layer.
- **z axis**: `--z-nav` 40 / `--z-overlay` 50 / `--z-toast` 60.
- **The scroll charter**: a view pins its control region (page header, query bar, lane switch) and hands each content region to `ScrollRegion`, so scrolling one pane never drags the page and an anchor jump lands inside the pane it belongs to. Overflow is stated rather than decorated: an edge that hides content fades through a `mask` (alpha, so it holds over any ground and in both themes, and needs no new token), and the scrollbar gutter is reserved once the region overflows and then stays — nobody should have to hover to learn that a region scrolls. The edge arithmetic is the import-free `lib/scrollRegion.ts`; the CSS is `.scroll-region`; `AppShell`'s `VIEWPORT_PANE_VIEWS` bounds the content column to the viewport at ≥lg for the views built this way.

---

## 3. Information architecture

Hash routing is the deep-link contract (`lib/hash.ts`): twelve views plus selection encoding. Navigation is a book's table of contents — a contents rail on desktop, a Drawer on mobile. The § numbers, order and grouping live in `components/TocNav.tsx` (`TOC`), the words in `i18n/nav.ts`: numbering is structure, labels are copy.

| Chapter | § | View (route) | What it is for |
|---|---|---|---|
| Front matter | 01 | `overview` | why this is a *compiler* |
| Materials | 02 / 03 | `sources` / `ingest` | read what came in; bring something in and see its plan |
| Process | 04 | `process` | compile jobs and their states |
| Retrieval | 05 / 06 / 07 | `recall` / `ask` / `live_context` | the three retrieval lanes, briefings, live suggestions |
| Canon | 08 / 09 / 10 | `library` / `graph` / `history` | canonical documents, structure health, versions |
| Evolution | 11 | `evolve` | schema drafts under review |
| Back matter | 12 | `profile` | the tenant's profile |

`#/components` is a hidden thirteenth route (the primitive gallery) and stays out of the contents.

The top bar runs across every view: wordmark, the mobile contents button, and on the right the UserPicker (tenant), the SnapshotPicker (live HEAD / frozen answerable snapshots / canonical commits, browse-only), LocaleToggle and ThemeToggle. While a snapshot is pinned, the content column opens with an archive-stamp banner and every mutating control is disabled (§4.3).

`overview` has to answer, on one screen: how material enters → how it is compiled and indexed → how a claim gets back to its source span → how it enters a version → how the retrieval surfaces are gated → that the data is synthetic. It does so as a galley — serif title, a short editor's note, a ruler-line production diagram (materials → compile → canon → retrieval, hairlines and § numbers, live counts on the nodes), the L0–L3 definition list, a numbered reading guide into the views, and the synthetic disclosure. Not a metro map, not a coloured pipeline graphic. With no data the counts read `—` and the guide still reads.

---

## 4. Component system

Layers: `src/ui/` (primitives) → `src/components/` (composed, product-wide) → `src/views/` (pages). Headless behaviour comes from **Radix UI**, one library only. Styling is Tailwind utilities over tokens (`bg-surface`, `text-ink-2`, `border-line`, `rounded-2`, `text-14`, `max-w-measure`, `max-w-content`), never a one-off CSS file.

### 4.1 Primitives (`src/ui/`)

Every primitive is controlled, keyboard reachable, focus-visible through the global standard (2px accent outline + 2px offset — already in effect, don't hand-roll one), labelled (`aria-label` / description), carries the disabled / error / loading / empty states that apply to it, works in both themes and at 390px, and looks the same across the three engines. No native control appearance leaks through; `index.css` strips it globally (§6 rule 2).

Contracts worth stating beyond what the types say:

- **Button** — `variant`: `primary` (accent ground) / `default` (ink outline) / `ghost` / `danger`; `size`: `sm` (h-7, 13px) / `md` (h-9, 14px); `loading` moves the spinner into the button, sets `aria-busy` and blocks re-submission.
- **IconButton** — square, lucide glyph, `aria-label` is a **required** prop (TS-enforced).
- **TextField / SearchField / TextArea / NumberField / FilePicker** — the reset is total: no native outline, no yellow autofill, no number spinner, no resize handle, no file-selector button. Clear buttons, ± steppers and drop zones are drawn; the native input survives visually-hidden for accessibility and file selection. `TextArea` grows via `autoRows`, not a native resize handle.
- **Select / Combobox / Menu / Tabs / SegmentedControl / Dialog / Drawer / Popover / Tooltip / Switch / Checkbox / RadioGroup / Slider** — Radix underneath, drawn on top. `Combobox` (Popover + filter input) is what UserPicker and SnapshotPicker share, and its `footer(query, close)` is where an action like "create a profile named …" goes. `SegmentedControl` renders only its triggers — the caller switches its own content off `value`. `Tooltip` is desktop hover + focus and single-line only; rich content belongs in `Footnote` or `Popover`.
- **Spinner / Skeleton / SkeletonText** — loading has one shape: skeletons in content positions, spinners only inside buttons.
- **EmptyState / ErrorState** — the product's only empty and error implementations. Empty copy names the next action; error carries the `ApiError` detail (in mono) and a retry.
- **Callout** — `tone`: notice (accent) / info (ink-3) / warn / danger; `variant`: `block` or `inline` (the full-width notice under the top bar). A 2px semantic left rule over a neutral ground.
- **Footnote** — the signature component. A superscript accent `[n]` in the body; hover or focus opens the citation card; a click jumps to the source span (usually through `focusSource(sourceId, { start, end })`).
- **Mono / Kbd / Badge / Stamp** — machine text with automatic tabular-nums (never for Chinese body text, buttons or dropdowns); key caps; neutral labels in four tones; and the archive stamp (a -2deg outlined seal) reserved for read-only / synthetic / a real status.
- **SectionRule / DefinitionList** — `§01 ── title ────────` section breaks, used instead of cards, and term/definition rows separated by hairlines.
- **ScrollRegion** — the single carrier of the scroll charter (§2.5). **The caller owns the height** (`flex-1 min-h-0` inside a pinned pane, `max-h-…` in flow); with no height bound the region never overflows and degrades to ordinary page flow, so a narrow screen reuses the same markup. The component only measures itself and writes the edge state out as `data-fade` (none/top/bottom/both) and `data-overflowing`; the fade and the rail live in CSS.

### 4.2 Composed (`src/components/`)

`AppShell` (top bar + contents rail at 232px + content column at `max-w-content` + notice bar + offline bar + the snapshot banner), `TocNav`, `UserPicker`, `SnapshotPicker`, `ThemeToggle`, `LocaleToggle`, `PageHeader` (serif page title at 24 + one ink-2 line + actions), `PaginationBar`, `ActivityHeatmap`.

The ones carrying a design decision:

- **SourceSpanSheet** — where a citation lands: a right Drawer with the original (mono block numbers + serif body), the target span highlighted in accent-soft, and a "fetch the exact span" locator call. Shared by recall / ask / live_context / library, so a citation always lands the same way.
- **CitationList** — a footnote register: one hairline above the block and none between rows; `[n]` in mono ink-3 because accent belongs to the in-body `Footnote` marker; 12px ink-2 titles, 12px ink-3 spans and ids, line height tightened to 1.45. The recession is visual only — a row still hovers and clicks back to the source span, and hover brings its title back to ink.
- **ClaimRow** — serif body + `Footnote` sequence + mono anchor; flags (disputed / open_question) as marginalia in a right rail at ≥md, dropping below the body on narrow screens.
- **GateLedger** — the five drop counters (`unparsed / repeat / uncited / low_confidence / capped`) as a ledger page; only real states take colour (uncited danger, the rest warn, zero ink-3). What the gate ate appears *only* as a count: the gate's seriousness is expressed by the absence.
- **`views/library/NeighborhoodCard`** — outbound and inbound columns where every row is the other document's title plus **the claim sentence that made the edge**. An edge's information *is* that sentence, so anywhere an edge shows, the sentence comes with it. Structure is never drawn with a graph-rendering library (rule 11).

### 4.3 States (uniform across views)

| state | how |
|---|---|
| loading, content position | `Skeleton` / `SkeletonText` — never a per-view invention |
| loading, an action | `Button loading` |
| empty | `EmptyState`, copy naming the next action |
| error | `ErrorState` with the `ApiError` detail and `onRetry` |
| offline / reconnecting | `Callout variant="inline"` under the top bar (AppShell already handles `usersError`); a WS view also shows connecting/open/closed as words plus a single dot in its header — not a bank of coloured lamps |
| read-only snapshot | AppShell's archive-stamp banner + every mutation control `disabled` (`currentSnapshot != null`) |

Status in general is words plus an ink step, not a traffic light; an unknown machine status renders as its raw name rather than as a blank. The typography of reading surfaces is §2.4. `#/components` is the state matrix in visual form.

### 4.4 Copy and i18n

Dictionaries live in `src/i18n/`, one namespace file per view, declared through `defineMessages()` so zh/en key parity is a **compile-time** fact: a key present in one language and missing in the other fails `tsc -b`. `tests/i18n.test.mjs` is the second net and also catches keys duplicated across bundles. No user-facing literal is written in `src/`.

- **New copy goes into the namespace file it belongs to**, keyed with that namespace (`library.claim.empty`). Shared words — retry, close, previous, flag, gate, pagination, footnote — are already in `i18n/common.ts`.
- **Server-side closed vocabularies** (intake archetype, context focus, suggestion kind, source kind) live in `i18n/enums.ts` keyed by the stable `key` the API returns, and are read through **`useTOr()` with the server's label as fallback** — so when the server gains a value the UI degrades to that English label instead of a blank.
- **Data is not translated**: canonical text, source content, personal names, server-supplied rationale / detail / error messages.
- **Pure-function modules must not import i18n at runtime** — `lib/evolve.ts`, `lib/citations.ts`, `views/*/…Presentation.ts`, the ones the tests esbuild into a `data:` URL on their own. Return a message key for the view to translate, or take a translate function as an argument.
- Primitive default copy already comes from the dictionary (`ErrorState.title`, `Select.placeholder`, `Combobox.filterPlaceholder`/`emptyText`, `SearchField.clearLabel`, `PaginationBar.noun` are optional; omitted, they fall back to `common.*`).

`locale` sits in the store beside `theme` (`s.locale` / `setLocale` / `toggleLocale`), and `LocaleToggle` sits next to `ThemeToggle` in the top bar — switching is immediate, with no reload. Resolution order: an explicit localStorage choice → `navigator.language` (`zh*` → zh) → **en**. `fmtTime` / `fmtDate` in `lib/format.ts` follow the locale through `Intl`, so call sites don't handle it.

---

## 5. Views

- **overview** — 60 seconds on "this is a knowledge compiler", built as described in §3.
- **sources** — master-detail: a source catalog on the left (title, kind, block count, digestion state as words and a time, not a lamp); on the right two reading layers. The *source view* restores each contract's native reading syntax (meeting: header, participants, timed transcript; document-library: vault path, frontmatter, tags and backlinks; IM: channel context, dates, thread indent; email: thread header, correspondents, attachments). The *galley* keeps the intake plan, the structure map, normalized blocks (mono block number + serif body) and span highlighting. All four kinds share the same tokens — the difference is information structure, not four colour schemes. An older source missing newer display metadata degrades to its blocks rather than guessing at provider fields.
- **ingest** — two steps: edit (title + TextArea / FilePicker + archetype Select + source class RadioGroup) → a mechanical preview (structure tree, block and character counts, the proposed IntakePlan's two knobs, the archetype mapping) → confirm → result (source id, deduplicated, a way into sources). Preview-first is the point: nothing is imported before its plan is visible.
- **process** — a job ledger, one row per compile (mono job id, kind, status in words, time, snapshot ref); a selected row expands into its sources, detail and lineage (model / provider / tokens as a mono definition list). `compile` is the primary action.
- **recall** — a SegmentedControl over the three lanes: `rag` (fused L1/L2 hits with scores, source, block span, a Footnote into the span), `fast` (a serif answer + used-claim footnotes), `deep` (an SSE step trail, then the answer). Token usage is a mono definition list. All three lanes keep their input and results in `store.recallCache`, so leaving to read an original and coming back loses nothing.
- **ask** — briefing construction (query, source multi-select, a character budget NumberField) then a continuous thread of serif question/answer pairs with citation footnotes and per-turn usage. A citation opens `SourceSpanSheet`.
- **live_context** — two chains in one view: one-shot SSE (workflow window, focus/kind, a min-confidence Slider → surviving cards + the `GateLedger`) and a long-lived WS (connection state, config, turn append, flush, `want_more`). A card is title + serif body + trigger + confidence as a number, not a gauge.
- **library** — the document tree on the left; on the right the selected document as a proof: serif body, mono claim anchors, footnote citations, and flags as marginalia. A selected claim deep-links to `#/library/claim/…`. The neighbourhood card (§4.2) is where a thread gets followed.
- **graph** — the structure *lens*, not an exploration canvas: a free layout of the whole base answered none of the questions people actually brought to it. Two tabs — **structure health** (the three most abnormal things stated in sentences, then concentration, connectivity, family balance, each abnormal entry clicking into its document) and **snapshot compare** (two snapshots: a metric delta table, a per-subject gain/loss list, new internal links each with the sentence that made it). Old `#/graph/node/<id>` links resolve to the document (or source) the node stood for.
- **history** — one ledger over snapshots, jobs and patches (mono ref, time, changed paths, sources consumed, lineage). A patch expands into escalations, flag counts and claim traces; a snapshot row can be opened read-only through the SnapshotPicker.
- **evolve** — three surfaces: the evolution timeline (status is the station's shape and semantic colour), the task detail (proposal reasoning, pack drafts, the anchors that disappear, changed-file diffs, adopt/drop), and the schema axis (families and path templates accumulating over time). A 409 single-flight conflict surfaces as a `Callout`. `#/evolve/evolve-task/<id>` lands on the detail.
- **profile** — the tenant's profile: identity plus a definition list of the fields the compile contract reads, and an edit form built entirely from primitives. AI generation belongs to new-profile onboarding only (one sentence → a draft → the user confirms); an existing profile shows no generate affordance.
- **components** (hidden `#/components`) — every primitive in default / hover / focus / disabled / error / loading / empty, for review screenshots and regression.

---

## 6. Hard rules

1. Colour lives only in `tokens.css`; components carry zero hex and zero `rgb()`/`hsl()` literals (`color-mix` derivation excepted).
2. Zero native control appearance in product pages: select, number spinner, range, checkbox, radio, file, datalist, date picker all go through primitives; a visually-hidden native input remains only as the accessibility and file-selection backing.
3. Visible Chinese text ≥ 12px; mono never on Chinese body text, buttons or dropdowns.
4. One accent per product (the blue pencil). Modules are not assigned their own colours, and semantic colour is only for real states.
5. No card stacks, no KPI number walls, no gradients, neon, glassmorphism or saturated blue-purple.
6. Dark is not an inversion: the two themes are tuned independently, dark keeps its ink steps, and pure black grounds are out.
7. Wide screens don't stretch forever: the content column is bounded; a genuinely wide view (a table, a long ledger) scrolls horizontally on its own.
8. No horizontal overflow at 390px, and every interaction is reachable there.
9. Under `prefers-reduced-motion` all motion is zero.
10. WCAG 2.2 AA: contrast, visible focus, full keyboard reachability.
11. No graph-rendering library: structure is expressed typographically (tables, ledgers, hairline bars), and the bundle stays modest.
12. All interface copy is open-source-safe, domain-agnostic and synthetic — no real customer, company or internal content.

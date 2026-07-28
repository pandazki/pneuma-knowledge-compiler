# Pneuma Knowledge Compiler — Knowledge Transit Atlas

The interface explains and operates the compiler as one transit system. Raw material,
authoritative storage, lexical and semantic retrieval, the compile gate, and Canonical
Git are stations on a route—not dashboard categories.

## Sources of truth

The design assets have distinct responsibilities:

1. [`../../apps/web/src/styles/tokens.css`](../../apps/web/src/styles/tokens.css) is the
   **only runtime source of truth for design tokens**. Change theme colors, type,
   spacing, radii, shadows, and motion there.
2. [`../../apps/web/src/styles/transit.css`](../../apps/web/src/styles/transit.css)
   applies those tokens to the Knowledge Transit Atlas composition, responsive route
   map, station workbenches, and evidence journey.
3. [`../../DESIGN.md`](../../DESIGN.md) is the portable, post-build design contract for
   humans and DESIGN.md-aware tools.
4. [`tokens.css`](./tokens.css) is a documentation proxy only. It imports the runtime
   token file and intentionally duplicates no custom-property values.

Do not manually synchronize token values into documentation. A token change is complete
only after the runtime file is updated and the rendered light, dark, and 390px surfaces
have been checked.

## Visual thesis

One system, two independently authored operating environments:

- **Day / porcelain wayfinding mural:** warm porcelain canvas, navy type, soft
  blue-gray boundaries, colored routes, and a cream destination sheet.
- **Night / midnight enamel control room:** deep navy surfaces, warm enamel type,
  brighter routes, and stronger depth separation.

Theme changes preserve station order, route responsibility, evidence meaning, focus
visibility, and layout hierarchy. They are not a color inversion.

## Route language

| Route | Responsibility |
|---|---|
| Green | Source, PostgreSQL, authority, verified / success |
| Cobalt | Meilisearch L1, retrieval, information |
| Amber | Qdrant L2, context suggestion, open question |
| Scarlet | Compile gate, Canonical Git, patch, disputed / danger |
| Coral | Primary action and arrival signal; not a responsibility route |
| Violet | Inferred evidence only; not part of the six-station architecture route |

Solid segments communicate authoritative data. Dashed segments communicate rebuildable
projections. Route colors may not be rotated across arbitrary cards.

## Six-station contract

The first route is always:

1. `S0` 原始材料
2. `P0` PostgreSQL
3. `L1` Meilisearch
4. `L2` Qdrant
5. `C1` 编译门
6. `G1` Canonical Git

Desktop uses an inline SVG with the L1/L2 branch and merge. At 820px and below, the SVG
becomes a complete vertical ordered route. The 390px acceptance viewport must show all
six stations in order; responsive layout may change direction but may not remove a
branch, gate, or destination.

## Evidence and demo truth

- The opening destination sheet derives source/span, claim anchor, canonical path, and
  patch/ref from the current dataset.
- The four-step journey uses the same real model projection.
- Missing data produces an honest empty route, not fake metrics or placeholder success.
- Desktop navigation displays `OPEN DEMO / SYNTHETIC · OPC`.
- Mobile navigation displays the full word `SYNTHETIC`.
- The opening manifest states that the OPC persona and data are deterministic,
  repository-bundled simulations and not real customers.

## Component rules

1. Use semantic tokens in components. Raw theme values belong in the runtime token
   source, not JSX.
2. Use route colors for system responsibility and state; use Coral for the primary
   departure action.
3. Place complex tasks inside a named station `RouteFrame` and its destination
   workbench.
4. Use 8px controls, 14px sheets, 22px stages, route pills, and circular stations.
5. Use system sans for reading and mono only for station codes, IDs, paths, refs,
   timestamps, and lineage.
6. Keep all user-visible annotations at 12px or larger.
7. Use Lucide icons; do not use emoji as interface decoration.
8. Give every interactive state visible keyboard focus and AA-oriented contrast.
9. Honor reduced motion; route arrival resolves immediately when motion is reduced.
10. Preserve owner, snapshot, theme, navigation, and SYNTHETIC context across routes.

## Responsive contract

- **Above 1180px:** 212px navigation, full route mural, right-side destination sheet.
- **821–1180px:** 180px navigation and compact top controls.
- **820px and below:** horizontal navigation, vertical six-station route, destination
  sheet below the stations, edge-to-edge station workbench.
- **390px acceptance:** no page-level horizontal overflow, all six stations and the
  complete SYNTHETIC label remain visible and operable.

## Anti-patterns

- No KPI theatre, bento dashboard, dense admin grid, fake store logo, or decorative
  upload dropzone on the opening route.
- No generated filler, fake customer, fake benchmark, or invented evidence.
- No neon route glow or decorative motion without state meaning.
- No duplicated token tables that can drift from
  `apps/web/src/styles/tokens.css`.

import type { Model, NodeShape } from "@/lib/model";
import { typeGlyph } from "@/lib/model";

/**
 * The redundant typeGlyph encoding (shape + ink step) shared by the graph and its legend.
 *
 * Note: lib/model's typeShade resolves against the old var(--color-text), which does not
 * exist under the new tokens (§2). This derives the same ink ramp (35%→92%) from var(--ink)
 * instead, so it holds in both themes and stays pure ink (rule: no colour in the graph).
 */
export function inkShade(model: Model, type: string | null): string {
  if (!type) return "color-mix(in srgb, var(--ink) 26%, transparent)";
  const i = model.typeIndex.get(type) ?? 0;
  const total = Math.max(model.types.length, 1);
  const pct = Math.round(35 + (57 * i) / Math.max(total - 1, 1));
  return `color-mix(in srgb, var(--ink) ${pct}%, transparent)`;
}

const PENTAGON = "7,1 12.7,5.1 10.5,12 3.5,12 1.3,5.1";
const HEXAGON = "4.5,1.5 9.5,1.5 13,7 9.5,12.5 4.5,12.5 1,7";

function ShapePath({ shape }: { shape: NodeShape }) {
  switch (shape) {
    case "square":
      return <rect x="2" y="2" width="10" height="10" />;
    case "diamond":
      return <polygon points="7,1 13,7 7,13 1,7" />;
    case "triangle":
      return <polygon points="7,1.5 13,12 1,12" />;
    case "pentagon":
      return <polygon points={PENTAGON} />;
    case "hexagon":
      return <polygon points={HEXAGON} />;
    default:
      return <circle cx="7" cy="7" r="5" />;
  }
}

/** Pure shape icon with shape + shade already resolved (used by GraphCanvas nodes). */
export function ShapeIcon({
  shape,
  shade,
  size = 14,
}: {
  shape: NodeShape;
  shade: string;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      aria-hidden
      className="shrink-0"
    >
      <g fill={shade} stroke={shade} strokeWidth="1" fillOpacity="0.35">
        <ShapePath shape={shape} />
      </g>
    </svg>
  );
}

/** Type glyph swatch: shape outline + ink-step fill (one source for node and legend). */
export function GlyphSwatch({
  model,
  type,
  size = 14,
}: {
  model: Model;
  type: string | null;
  size?: number;
}) {
  const { shape } = typeGlyph(model, type);
  return <ShapeIcon shape={shape} shade={inkShade(model, type)} size={size} />;
}

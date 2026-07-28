/**
 * Per-type graph glyphs (P1-2). A monochrome shade plus a redundant shape makes
 * adjacent ontology types separable without breaking the grayscale discipline.
 * The graph node and the legend swatch render through the SAME `shapeElement`, so
 * a legend chip always matches how its nodes are drawn.
 */
import type { NodeShape } from "@/lib/model";

/** Points for a regular polygon circumscribed by radius `r`, rotated so a vertex points up. */
function polyPoints(sides: number, r: number, rotation = -Math.PI / 2): string {
  const pts: string[] = [];
  for (let i = 0; i < sides; i++) {
    const a = rotation + (i * 2 * Math.PI) / sides;
    pts.push(`${(Math.cos(a) * r).toFixed(2)},${(Math.sin(a) * r).toFixed(2)}`);
  }
  return pts.join(" ");
}

/**
 * An SVG shape element centered at (0,0), sized to radius `r`. Meant to be dropped
 * inside an existing <svg>/<g>. Fill/stroke are passed through so the caller controls
 * theming, selection and center emphasis.
 */
export function shapeElement(
  shape: NodeShape,
  r: number,
  props: React.SVGProps<SVGCircleElement & SVGRectElement & SVGPolygonElement>,
): React.ReactElement {
  switch (shape) {
    case "square": {
      const s = r * 0.9;
      return <rect x={-s} y={-s} width={s * 2} height={s * 2} {...props} />;
    }
    case "diamond":
      return <polygon points={polyPoints(4, r * 1.15)} {...props} />;
    case "triangle":
      return <polygon points={polyPoints(3, r * 1.2)} {...props} />;
    case "pentagon":
      return <polygon points={polyPoints(5, r * 1.1)} {...props} />;
    case "hexagon":
      return <polygon points={polyPoints(6, r * 1.08)} {...props} />;
    case "circle":
    default:
      return <circle r={r} {...props} />;
  }
}

/** Standalone swatch matching a node's rendering — used by legends and detail chips. */
export function GlyphSwatch({
  shape,
  shade,
  size = 12,
}: {
  shape: NodeShape;
  shade: string;
  size?: number;
}) {
  const r = size / 2 - 1;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`${-size / 2} ${-size / 2} ${size} ${size}`}
      className="inline-block flex-none"
      aria-hidden
    >
      {shapeElement(shape, r, {
        fill: shade,
        stroke: "var(--color-border-strong)",
        strokeWidth: 1,
      })}
    </svg>
  );
}

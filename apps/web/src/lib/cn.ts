import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * Out of the box tailwind-merge does not know this design system's tokens (DESIGN.md §2):
 * it reads `text-accent-ink` as a font-size class and drops it on merge — which is how the
 * primary button once lost its colour. Registering each token in its own group (colours with
 * colours, sizes with sizes, radii with radii) stops the cross-group swallowing while keeping
 * correct dedupe within a group, so a caller's override still wins.
 */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      colors: [
        "bg",
        "surface",
        "raised",
        "ink",
        "ink-2",
        "ink-3",
        "line",
        "line-2",
        "accent",
        "accent-ink",
        "accent-soft",
        "accent-line",
        "hover",
        "active",
        "ok",
        "ok-soft",
        "warn",
        "warn-soft",
        "danger",
        "danger-soft",
      ],
    },
    classGroups: {
      "font-size": [{ text: ["12", "13", "14", "16", "20", "24", "30", "38"] }],
      rounded: [{ rounded: ["1", "2", "3"] }],
      "max-w": [{ "max-w": ["measure", "content"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

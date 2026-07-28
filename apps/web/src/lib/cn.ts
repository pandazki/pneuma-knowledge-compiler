import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge 默认配置不认识本设计系统的 token（DESIGN.md §2），会把
 * `text-accent-ink` 误判为字号类并在合并时丢弃——primary 按钮曾因此丢色。
 * 这里把 token 注册进对应分组：颜色归颜色、字号归字号、圆角归圆角，
 * 跨分组不再互相误吞，同分组仍能正确去重（调用方覆盖生效）。
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

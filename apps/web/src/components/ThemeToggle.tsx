import { Sun, Moon } from "lucide-react";
import { useApp } from "@/lib/store";
import { IconButton } from "@/ui/IconButton";
import { Tooltip } from "@/ui/Tooltip";

/** 日/夜主题切换。 */
export function ThemeToggle() {
  const theme = useApp((s) => s.theme);
  const toggleTheme = useApp((s) => s.toggleTheme);
  const dark = theme === "dark";
  return (
    <Tooltip content={dark ? "切到日间「纸」" : "切到夜间「灯箱」"}>
      <IconButton aria-label="切换主题" onClick={toggleTheme}>
        {dark ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
      </IconButton>
    </Tooltip>
  );
}

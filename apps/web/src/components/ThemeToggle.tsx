import { Sun, Moon } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { IconButton } from "@/ui/IconButton";
import { Tooltip } from "@/ui/Tooltip";

/** Day / night theme switch. */
export function ThemeToggle() {
  const theme = useApp((s) => s.theme);
  const toggleTheme = useApp((s) => s.toggleTheme);
  const t = useT();
  const dark = theme === "dark";
  return (
    <Tooltip content={dark ? t("nav.theme.toLight") : t("nav.theme.toDark")}>
      <IconButton aria-label={t("nav.theme.label")} onClick={toggleTheme}>
        {dark ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
      </IconButton>
    </Tooltip>
  );
}

import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { IconButton } from "@/ui/IconButton";
import { Tooltip } from "@/ui/Tooltip";

/**
 * Interface language switch (zh | en) — the same shape as ThemeToggle, and like it, the
 * button shows the state you would move TO, not the one you are in.
 */
export function LocaleToggle() {
  const locale = useApp((s) => s.locale);
  const toggleLocale = useApp((s) => s.toggleLocale);
  const t = useT();
  const zh = locale === "zh";
  return (
    <Tooltip content={zh ? t("nav.locale.toEn") : t("nav.locale.toZh")}>
      <IconButton aria-label={t("nav.locale.label")} onClick={toggleLocale}>
        <span aria-hidden className="font-mono text-12 leading-none tracking-tight">
          {zh ? "EN" : "ZH"}
        </span>
      </IconButton>
    </Tooltip>
  );
}

import { useEffect, useState } from "react";
import { currentLibrary, type Snapshot } from "../lib/state";
import type { Locale } from "../lib/i18n";

export default function Attention({
  state,
  locale,
  settings = false,
}: {
  state: Snapshot;
  locale: Locale;
  settings?: boolean;
}) {
  const library = currentLibrary(state);
  const [theme, setTheme] = useState(() =>
    matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );
  useEffect(() => {
    const query = matchMedia("(prefers-color-scheme: dark)");
    const changed = () => setTheme(query.matches ? "dark" : "light");
    query.addEventListener("change", changed);
    return () => query.removeEventListener("change", changed);
  }, []);
  if (!library?.engine.up) return null;
  const url = `http://127.0.0.1:${library.engine.port}/home/attention/view?locale=${locale}&theme=${theme}${settings ? "&settings=1" : ""}`;
  return (
    <iframe
      className={`attention-frame${settings ? " attention-settings" : ""}`}
      title={
        locale === "zh-CN"
          ? "注意力看板与时光机"
          : "Attention board and time machine"
      }
      src={url}
      sandbox="allow-scripts allow-same-origin allow-forms"
    />
  );
}

import { Library } from "lucide-react";
import { useApp } from "@/lib/store";
import { libraryHref, type HomeLibrary, type HomeStatus } from "@/lib/home";
import { useT } from "@/lib/useT";
import { Combobox, type ComboboxItem } from "@/ui/Combobox";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * The switcher a personal edition gets in place of the raw tenant picker: the machine's
 * libraries BY NAME, with a dot for whether each one's engine is running.
 *
 * Switching is a navigation, not a request. Each library has an engine process of its own
 * and each engine serves this same console at its own port (single-machine-edition §4.10),
 * so the only honest way to "switch library" is to go to that library's console — carrying
 * the hash route across, so the switch lands on the page you were already reading.
 *
 * A library whose engine is down is listed and disabled rather than hidden: it exists, it is
 * on this machine, and a name that vanishes when a process stops teaches the wrong thing
 * about where the knowledge lives. Starting it is a `pkchome` verb, and this console has no
 * actions over the home yet — the disabled row says what is wrong and stops there.
 *
 * There is no free-text id here. With a home, the machine's tenants ARE the tenants: a box
 * that accepted any string would offer a library this engine cannot serve.
 */
export function LibraryPicker({ home }: { home: HomeStatus }) {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);

  const libraries = home.libraries;
  const active =
    libraries.find((library) => library.tenant === currentUser) ??
    libraries.find((library) => library.current) ??
    null;

  const item = (library: HomeLibrary): ComboboxItem => {
    const here = library === active;
    return {
      value: library.name,
      label: library.name,
      keywords: library.tenant,
      // The library on the bench is always selectable (choosing it is a no-op); another
      // one is only reachable if something is listening on its port.
      disabled: !here && !library.engine.up,
      render: () => (
        <span
          className="flex items-center gap-2"
          title={library.engine.up ? undefined : t("home.picker.engineDown")}
        >
          <EngineDot up={library.engine.up} />
          <span className="min-w-0 flex-1 truncate">{library.name}</span>
          <Mono className="shrink-0 text-12 text-ink-3">{library.tenant}</Mono>
        </span>
      ),
    };
  };

  return (
    <Combobox
      value={active?.name ?? null}
      onChange={(name) => {
        const library = libraries.find((candidate) => candidate.name === name);
        if (!library || library === active) return;
        const href = libraryHref(library, window.location, window.location.hash);
        if (href) window.location.assign(href);
      }}
      items={libraries.map(item)}
      trigger={
        <span className="flex items-center gap-1.5">
          <Library size={14} aria-hidden className="shrink-0 text-ink-3" />
          <span className="max-w-28 truncate">{active?.name ?? t("home.picker.choose")}</span>
        </span>
      }
      triggerAriaLabel={t("home.picker.switchAria")}
      filterPlaceholder={t("home.picker.filterPlaceholder")}
      emptyText={t("home.picker.empty")}
    />
  );
}

/** Engine up / down, as a dot. Semantic colour for a real state, which is what it is. */
export function EngineDot({ up, className }: { up: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-1.5 shrink-0 rounded-full", up ? "bg-ok" : "bg-ink-3", className)}
    />
  );
}

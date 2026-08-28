import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { ChevronDown, Search } from "lucide-react";
import { useT } from "@/lib/useT";
import { cn } from "./cn";

export interface ComboboxItem {
  value: string;
  /** Primary copy (one of the things the filter matches on). */
  label: string;
  /** Extra filter keywords (user_id, ref, …). */
  keywords?: string;
  disabled?: boolean;
  /** Group name (e.g. "recent" / "all"); consecutive items sharing one form a section. */
  group?: string;
  /** Custom row renderer; falls back to rendering `label`. */
  render?: () => ReactNode;
}

export interface ComboboxProps {
  /** Current value (null = nothing selected). */
  value: string | null;
  onChange: (value: string) => void;
  items: ComboboxItem[];
  /** Trigger content, drawn by the caller (e.g. avatar + name). */
  trigger: ReactNode;
  triggerAriaLabel: string;
  filterPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  /** Note shown beside the trigger while disabled (e.g. "no versions yet"). */
  disabledNote?: string;
  /** Footer action area; receives the live filter text and `close` (e.g. "new profile …"). */
  footer?: (query: string, close: () => void) => ReactNode;
  /** Whether the surface matches the trigger width or is fixed. Defaults to 280px. */
  contentClassName?: string;
}

/**
 * Combobox = Radix Popover + a filter input + a hand-drawn listbox (arrows move, Enter
 * selects, Esc closes). Shared by UserPicker / SnapshotPicker.
 */
export function Combobox({
  value,
  onChange,
  items,
  trigger,
  triggerAriaLabel,
  filterPlaceholder,
  emptyText,
  disabled,
  disabledNote,
  footer,
  contentClassName,
}: ComboboxProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeRef = useRef<HTMLLIElement>(null);
  const baseId = useId();
  const listboxId = `${baseId}-listbox`;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        it.label.toLowerCase().includes(q) || (it.keywords ?? "").toLowerCase().includes(q),
    );
  }, [items, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // focus the filter input once the Popover animation has settled
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => setActive(0), [query]);

  /**
   * Keep the highlighted row in the viewport. The list scrolls at eight rows and the arrow
   * keys walked the selection straight out of sight — `aria-activedescendant` told a screen
   * reader where the cursor was while the screen showed rows nobody had moved to. `nearest`
   * scrolls only when it has to, so pointing at a visible row never jumps the list.
   */
  useEffect(() => {
    if (!open) return;
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [active, open, query]);

  const choose = (item: ComboboxItem) => {
    if (item.disabled) return;
    onChange(item.value);
    setOpen(false);
  };

  const onListKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const dir = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => {
        if (filtered.length === 0) return 0;
        return (i + dir + filtered.length) % filtered.length;
      });
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = filtered[active];
      if (item) choose(item);
    }
  };

  // group heading: insert the group name before its first item
  let lastGroup: string | undefined;

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <div className="inline-flex items-center gap-1.5">
        <PopoverPrimitive.Trigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label={triggerAriaLabel}
            aria-haspopup="listbox"
            aria-expanded={open}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-2 border border-line-2 bg-surface px-2.5 text-13 text-ink",
              "transition-colors duration-120 ease-out hover:not-disabled:bg-hover",
              "disabled:cursor-not-allowed disabled:opacity-45",
            )}
          >
            {trigger}
            <ChevronDown size={13} aria-hidden className="shrink-0 text-ink-3" />
          </button>
        </PopoverPrimitive.Trigger>
        {disabled && disabledNote && <span className="text-12 text-ink-3">{disabledNote}</span>}
      </div>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="end"
          sideOffset={4}
          className={cn(
            "z-50 w-[280px] rounded-3 border border-line bg-raised shadow-overlay",
            contentClassName,
          )}
        >
          <div className="flex h-9 items-center gap-2 border-b border-line px-3">
            <Search size={14} aria-hidden className="shrink-0 text-ink-3" />
            <input
              ref={inputRef}
              type="text"
              role="combobox"
              aria-expanded={open}
              aria-controls={listboxId}
              aria-activedescendant={filtered[active] ? `${listboxId}-opt-${filtered[active].value}` : undefined}
              value={query}
              placeholder={filterPlaceholder ?? t("common.filterPlaceholder")}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onListKeyDown}
              className="h-full min-w-0 flex-1 text-13 text-ink"
            />
          </div>
          <ul
            id={listboxId}
            role="listbox"
            aria-label={triggerAriaLabel}
            className="max-h-64 overflow-y-auto p-1"
          >
            {filtered.length === 0 && (
              <li className="px-2.5 py-3 text-center text-13 text-ink-3">
                {emptyText ?? t("common.noMatches")}
              </li>
            )}
            {filtered.map((item, i) => {
              const header =
                item.group !== lastGroup && item.group ? (
                  <li
                    key={`g-${item.group}`}
                    aria-hidden
                    className="px-2.5 pt-2 pb-1 text-12 text-ink-3 first:pt-1"
                  >
                    {item.group}
                  </li>
                ) : null;
              lastGroup = item.group;
              return [
                header,
                <li
                  key={item.value}
                  ref={i === active ? activeRef : undefined}
                  id={`${listboxId}-opt-${item.value}`}
                  role="option"
                  aria-selected={item.value === value}
                  aria-disabled={item.disabled || undefined}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(item)}
                  className={cn(
                    "cursor-pointer rounded-1 px-2.5 py-1.5 text-13 text-ink",
                    i === active && "bg-accent-soft",
                    item.value === value && "font-medium",
                    item.disabled && "cursor-not-allowed opacity-45",
                  )}
                >
                  {item.render ? item.render() : item.label}
                </li>,
              ];
            })}
          </ul>
          {footer && (
            <div className="border-t border-line p-1">{footer(query, () => setOpen(false))}</div>
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

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
import { cn } from "./cn";

export interface ComboboxItem {
  value: string;
  /** 主文案（过滤依据之一）。 */
  label: string;
  /** 额外过滤关键词（如 user_id、ref）。 */
  keywords?: string;
  disabled?: boolean;
  /** 分组名（如「最近」「全部」）；相同 group 的连续项归为一节。 */
  group?: string;
  /** 自定义行渲染；缺省渲染 label。 */
  render?: () => ReactNode;
}

export interface ComboboxProps {
  /** 当前选中值（null = 未选）。 */
  value: string | null;
  onChange: (value: string) => void;
  items: ComboboxItem[];
  /** 触发按钮内容（由调用方自绘，如 avatar + 名字）。 */
  trigger: ReactNode;
  triggerAriaLabel: string;
  filterPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  /** 禁用时的说明（如「尚无版本」），显示在触发器旁。 */
  disabledNote?: string;
  /** 浮层底部动作区；收到当前过滤词与 close（用于「新建画像「query」」之类）。 */
  footer?: (query: string, close: () => void) => ReactNode;
  /** 浮层宽度对齐触发器还是固定。默认 280px。 */
  contentClassName?: string;
}

/**
 * Combobox = Radix Popover + 过滤输入 + 自绘 listbox（箭头键移动 / Enter 选中 /
 * Esc 关闭）。供 UserPicker / SnapshotPicker 复用。
 */
export function Combobox({
  value,
  onChange,
  items,
  trigger,
  triggerAriaLabel,
  filterPlaceholder = "过滤…",
  emptyText = "没有匹配项",
  disabled,
  disabledNote,
  footer,
  contentClassName,
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
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
      // Popover 动画后聚焦过滤输入
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => setActive(0), [query]);

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

  // 分组标题：某组第一项之前插入组名
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
              placeholder={filterPlaceholder}
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
              <li className="px-2.5 py-3 text-center text-13 text-ink-3">{emptyText}</li>
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

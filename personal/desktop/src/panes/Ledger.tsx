import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { edgeOption, matchOption, placeMenu, stepOption, type MenuOption, type Placement } from '../lib/menu';

export function Leader() { return <span className="leader" aria-hidden="true" />; }

export type { MenuOption };

/**
 * A ledger's own drop-down: a value with a chevron that opens a list drawn by this page,
 * never the platform's popup. The list is fixed in the viewport (the panel is only as tall
 * as its content, so it flips upward near the bottom), and the trigger keeps focus while
 * `aria-activedescendant` names the highlighted option. The list is portalled to the body:
 * the page's settle animation leaves a transform on `main`, which would otherwise become
 * the containing block of anything fixed inside it.
 */
export function LedgerSelect({ id, value, options, disabled, placeholder, onChange }: {
  id: string; value: string; options: MenuOption[]; disabled?: boolean; placeholder?: string; onChange: (value: string) => void;
}) {
  const listId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const typed = useRef({ prefix: '', at: 0 });
  const selectedIndex = options.findIndex(option => option.value === value);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  const close = useCallback(() => { setOpen(false); setPlacement(null); }, []);
  const openList = useCallback(() => {
    if (disabled) return;
    setActive(selectedIndex >= 0 && !options[selectedIndex].disabled ? selectedIndex : edgeOption(options, 'first'));
    setOpen(true);
  }, [disabled, options, selectedIndex]);
  const choose = useCallback((index: number) => {
    const option = options[index];
    close();
    trigger.current?.focus();
    if (option && !option.disabled && option.value !== value) onChange(option.value);
  }, [close, onChange, options, value]);

  // Place the list after it exists (its height is only known once laid out).
  useLayoutEffect(() => {
    if (!open || !trigger.current || !list.current) return;
    const rect = trigger.current.getBoundingClientRect();
    setPlacement(placeMenu(rect, list.current.offsetHeight, window.innerHeight));
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !list.current?.contains(target)) close();
    };
    const scrolled = (event: Event) => { if (!list.current?.contains(event.target as Node)) close(); };
    document.addEventListener('pointerdown', outside, true);
    document.addEventListener('scroll', scrolled, true);
    window.addEventListener('resize', close);
    window.addEventListener('blur', close);
    return () => {
      document.removeEventListener('pointerdown', outside, true);
      document.removeEventListener('scroll', scrolled, true);
      window.removeEventListener('resize', close);
      window.removeEventListener('blur', close);
    };
  }, [open, close]);

  useEffect(() => {
    if (!open || active < 0) return;
    list.current?.children[active]?.scrollIntoView({ block: 'nearest' });
  }, [open, active]);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const move = (index: number) => { if (index >= 0) setActive(index); };
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) { event.preventDefault(); openList(); }
      return;
    }
    switch (event.key) {
      case 'ArrowDown': event.preventDefault(); move(stepOption(options, active, 1)); break;
      case 'ArrowUp': event.preventDefault(); move(stepOption(options, active, -1)); break;
      case 'Home': case 'PageUp': event.preventDefault(); move(edgeOption(options, 'first')); break;
      case 'End': case 'PageDown': event.preventDefault(); move(edgeOption(options, 'last')); break;
      case 'Enter': case ' ': event.preventDefault(); if (active >= 0) choose(active); else close(); break;
      case 'Escape': event.preventDefault(); event.stopPropagation(); close(); break;
      case 'Tab': close(); break;
      default: {
        if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return;
        const now = Date.now();
        const prefix = (now - typed.current.at < 700 ? typed.current.prefix : '') + event.key;
        typed.current = { prefix, at: now };
        move(matchOption(options, prefix, prefix.length > 1 ? active - 1 : active));
      }
    }
  };

  const activeId = active >= 0 ? `${listId}-${active}` : undefined;
  return <span className="select-value" data-open={open}>
    <button id={id} ref={trigger} type="button" className="select-trigger" role="combobox" aria-haspopup="listbox"
      aria-expanded={open} aria-controls={open ? listId : undefined} aria-activedescendant={open ? activeId : undefined}
      aria-labelledby={`${id}-label`} disabled={disabled} lang={selected?.lang}
      onClick={() => (open ? close() : openList())} onKeyDown={onKeyDown}>
      <span className="select-label" data-placeholder={!selected}>{selected?.label ?? placeholder ?? ''}</span>
    </button>
    {open && createPortal(<ul id={listId} ref={list} role="listbox" className="menu" aria-labelledby={`${id}-label`} data-side={placement?.side ?? 'below'}
      style={placement ? { top: placement.top, maxHeight: placement.maxHeight } : { visibility: 'hidden' }}
      onPointerMove={event => {
        const item = (event.target as HTMLElement).closest<HTMLElement>('[data-index]');
        if (item) setActive(Number(item.dataset.index));
      }}>
      {options.map((option, index) => <li key={option.value} id={`${listId}-${index}`} role="option" data-index={index} lang={option.lang}
        aria-selected={index === selectedIndex} aria-disabled={option.disabled || undefined} data-active={index === active}
        onPointerDown={event => event.preventDefault()} onClick={() => { if (!option.disabled) choose(index); }}>
        <span className="menu-mark" aria-hidden="true">{index === selectedIndex ? '•' : ''}</span>
        <span className="menu-label">{option.label}</span>
      </li>)}
    </ul>, document.body)}
  </span>;
}

export function SettingRow({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return <div className="setting-row">
    <label id={`${id}-label`} className="small-caps" htmlFor={id}>{label}</label><Leader /><div className="setting-control">{children}</div>
  </div>;
}

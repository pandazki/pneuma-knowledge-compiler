/** Route-oriented primitives for the Pneuma Knowledge Transit Atlas. */
import React from "react";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ Eyebrow */
export function Eyebrow({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("pneuma-eyebrow", className)}>{children}</div>;
}

/* --------------------------------------------------------------------- Card */
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-card rounded-[var(--radius-md)] shadow-[var(--shadow-subtle)]",
        className,
      )}
      {...props}
    />
  );
}

/* ------------------------------------------------------------------- Button */
type ButtonVariant = "primary" | "secondary" | "ghost" | "outline";
type ButtonSize = "sm" | "md" | "icon";

const BTN_BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-full font-medium select-none " +
  "transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap";

const BTN_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground hover:opacity-90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-accent",
  ghost: "bg-transparent text-foreground hover:bg-accent",
  outline: "bg-transparent text-foreground ring-1 ring-inset ring-border hover:bg-accent",
};

const BTN_SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-10 px-4 text-[length:var(--text-sm)]",
  icon: "h-10 w-10 text-sm",
};

export const Button = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    size?: ButtonSize;
  }
>(function Button({ className, variant = "secondary", size = "md", ...props }, ref) {
  return (
    <button
      ref={ref}
      className={cn(BTN_BASE, BTN_VARIANT[variant], BTN_SIZE[size], className)}
      {...props}
    />
  );
});

/* --------------------------------------------------------------- StatusDot */
export function StatusDot({ color, className }: { color: string; className?: string }) {
  return (
    <span
      className={cn("inline-block rounded-full", className)}
      style={{ width: 7, height: 7, background: color, flex: "none" }}
    />
  );
}

/* --------------------------------------------------------------------- Chip */
export function Chip({
  children,
  dotColor,
  title,
  onClick,
  className,
}: {
  children: React.ReactNode;
  dotColor?: string;
  title?: string;
  onClick?: () => void;
  className?: string;
}) {
  const interactive = !!onClick;
  return (
    <span
      title={title}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full",
        "px-2.5 py-1 text-[length:var(--text-2xs)] leading-none text-foreground bg-[var(--color-surface-muted)]",
        interactive && "cursor-pointer hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
    >
      {dotColor && <StatusDot color={dotColor} />}
      {children}
    </span>
  );
}

/* ---------------------------------------------------------- SegmentedControl */
export interface Segment<T extends string> {
  value: T;
  label: React.ReactNode;
}
export function SegmentedControl<T extends string>({
  segments,
  value,
  onChange,
  className,
}: {
  segments: Segment<T>[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex rounded-full bg-[var(--color-surface-muted)] p-1",
        className,
      )}
      role="tablist"
    >
      {segments.map((seg) => {
        const active = seg.value === value;
        return (
          <button
            key={seg.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(seg.value)}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 h-8 text-[length:var(--text-sm)] font-medium",
              "transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:z-10",
              active
                ? "rounded-full bg-[var(--color-surface-inverse)] text-[var(--color-text-inverse)] shadow-sm"
                : "rounded-full bg-transparent text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            {seg.label}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------- Hover */
/**
 * Hover-intent card. The trigger and the card are one contiguous hover region:
 * leaving either starts a ~250ms grace timer (so crossing the small gap between
 * chip and card does not dismiss it), and entering either cancels it. Clicking the
 * trigger PINS the card open — it then stays until you click the trigger again,
 * click outside, or press Esc. Positioned `fixed` off the trigger rect so it
 * escapes overflow clipping. (User feedback: the old card vanished the moment the
 * pointer moved toward its "在时间轴定位来源" link.)
 */
const HOVER_GRACE_MS = 250;

// Cross-instance pin mutex: pinning one card broadcasts its id; every
// other pinned instance hears it and closes itself. This covers the keyboard path
// (Enter-pin on a second trigger emits no outside `mousedown`, so click-outside
// alone could not dismiss the first) as well as the mouse path.
const PIN_EVENT = "pneuma-hover-pin";

export function Hover({
  trigger,
  children,
  width = 320,
}: {
  trigger: React.ReactNode;
  children: React.ReactNode;
  width?: number;
}) {
  const uid = React.useId();
  const [open, setOpen] = React.useState(false);
  const [pinned, setPinned] = React.useState(false);
  const [pos, setPos] = React.useState<{ top: number; left: number } | null>(null);
  const wrapRef = React.useRef<HTMLSpanElement>(null);
  const cardRef = React.useRef<HTMLDivElement>(null);
  const hideTimer = React.useRef<number | null>(null);

  const clearHide = React.useCallback(() => {
    if (hideTimer.current != null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }, []);

  const place = React.useCallback(() => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    let left = r.left;
    if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
    setPos({ top: r.bottom + 6, left: Math.max(12, left) });
  }, [width]);

  // Flip above the trigger when the card would overflow the viewport bottom (fable
  // F4) — keeps the important "在时间轴定位来源" link reachable. Runs after render so
  // the real card height is known; guarded to fire only from the below position, so
  // the resulting setPos does not loop.
  React.useLayoutEffect(() => {
    if (!open || !pos) return;
    const card = cardRef.current;
    const wrap = wrapRef.current;
    if (!card || !wrap) return;
    const cr = card.getBoundingClientRect();
    const wr = wrap.getBoundingClientRect();
    const isBelow = pos.top >= wr.bottom;
    const overflowsBottom = cr.bottom > window.innerHeight - 12;
    const fitsAbove = wr.top - cr.height - 6 > 12;
    if (isBelow && overflowsBottom && fitsAbove) {
      setPos({ top: wr.top - cr.height - 6, left: pos.left });
    }
  }, [open, pos]);

  const show = React.useCallback(() => {
    clearHide();
    place();
    setOpen(true);
  }, [clearHide, place]);

  const scheduleHide = React.useCallback(() => {
    if (pinned) return;
    clearHide();
    hideTimer.current = window.setTimeout(() => setOpen(false), HOVER_GRACE_MS);
  }, [pinned, clearHide]);

  const close = React.useCallback(() => {
    clearHide();
    setPinned(false);
    setOpen(false);
  }, [clearHide]);

  const togglePin = React.useCallback(() => {
    if (pinned) {
      close();
    } else {
      clearHide();
      place();
      setPinned(true);
      setOpen(true);
      // tell any other pinned card to close (mouse + keyboard paths).
      window.dispatchEvent(new CustomEvent(PIN_EVENT, { detail: uid }));
    }
  }, [pinned, close, clearHide, place, uid]);

  // Close when another Hover instance pins.
  React.useEffect(() => {
    if (!pinned) return;
    const onOtherPin = (e: Event) => {
      if ((e as CustomEvent<string>).detail !== uid) close();
    };
    window.addEventListener(PIN_EVENT, onOtherPin);
    return () => window.removeEventListener(PIN_EVENT, onOtherPin);
  }, [pinned, uid, close]);

  // While pinned: click-outside and Esc dismiss. Keep in sync with the pinned flag.
  React.useEffect(() => {
    if (!pinned) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (wrapRef.current?.contains(t) || cardRef.current?.contains(t)) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [pinned, close]);

  React.useEffect(() => () => clearHide(), [clearHide]);

  return (
    <span
      ref={wrapRef}
      onMouseEnter={show}
      onMouseLeave={scheduleHide}
      onFocus={show}
      onBlur={scheduleHide}
      onClick={togglePin}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          togglePin();
        } else if (e.key === "Escape") {
          close();
        }
      }}
      className="relative inline-flex"
      tabIndex={0}
    >
      {trigger}
      {open && pos && (
        <div
          ref={cardRef}
          role="tooltip"
          onMouseEnter={clearHide}
          onMouseLeave={scheduleHide}
          onClick={(e) => e.stopPropagation()}
          style={{
            position: "fixed",
            top: pos.top,
            left: pos.left,
            width,
            boxShadow: "var(--shadow-overlay)",
            borderColor: pinned ? "var(--color-accent)" : undefined,
          }}
          className="z-50 border border-border bg-popover text-popover-foreground rounded-sm p-3 text-[length:var(--text-sm)]"
        >
          {children}
        </div>
      )}
    </span>
  );
}

/* -------------------------------------------------------------- Empty state */
export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon?: React.ReactNode;
  title: string;
  hint?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center gap-3 p-8 text-muted-foreground">
      {icon}
      <div className="text-[length:var(--text-lg)] font-light text-foreground">{title}</div>
      {hint && <div className="text-sm max-w-sm">{hint}</div>}
    </div>
  );
}

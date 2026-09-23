/** Secondary run details, available on hover, keyboard focus and touch. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-popover";
import { IconButton } from "@/ui/IconButton";

export function StewardDetails({ label, icon, children, className, align = "end" }: {
  label: string;
  icon: ReactNode;
  children: ReactNode;
  className?: string;
  align?: "start" | "end";
}) {
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelClose = () => { if (timer.current) clearTimeout(timer.current); };
  const show = () => { cancelClose(); setOpen(true); };
  const closeSoon = () => { cancelClose(); timer.current = setTimeout(() => setOpen(false), 120); };
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <IconButton type="button" size="sm" aria-label={label} className={className}
          onMouseEnter={show} onMouseLeave={closeSoon}
          onFocus={(event) => { if (event.currentTarget.matches(":focus-visible")) show(); }} onBlur={closeSoon}>
          {icon}
        </IconButton>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content aria-label={label} side="top" align={align} sideOffset={6} collisionPadding={16}
          onMouseEnter={show} onMouseLeave={closeSoon}
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          className="z-50 max-w-[calc(100vw-2rem)] rounded-3 border border-line bg-raised p-3 text-12 text-ink shadow-overlay">
          <p className="mb-2 font-medium">{label}</p>
          {children}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

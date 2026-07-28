import * as RadixMenu from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";
import { cn } from "./cn";

export interface MenuItem {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect?: () => void;
  /** true → 该项渲染为分隔线（忽略其余字段）。 */
  separator?: boolean;
}

export interface MenuProps {
  trigger: ReactNode;
  items: MenuItem[];
  align?: "start" | "center" | "end";
  side?: "top" | "right" | "bottom" | "left";
  contentClassName?: string;
}

/** Radix DropdownMenu：trigger 走 asChild。 */
export function Menu({
  trigger,
  items,
  align = "end",
  side = "bottom",
  contentClassName,
}: MenuProps) {
  return (
    <RadixMenu.Root>
      <RadixMenu.Trigger asChild>{trigger}</RadixMenu.Trigger>
      <RadixMenu.Portal>
        <RadixMenu.Content
          align={align}
          side={side}
          sideOffset={4}
          className={cn(
            "z-50 min-w-44 rounded-3 border border-line bg-raised p-1 shadow-overlay",
            contentClassName,
          )}
        >
          {items.map((item) =>
            item.separator ? (
              <RadixMenu.Separator key={item.key} className="my-1 h-px bg-line" />
            ) : (
              <RadixMenu.Item
                key={item.key}
                disabled={item.disabled}
                onSelect={item.onSelect}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-1 px-2.5 py-1.5 text-13 outline-none select-none",
                  item.danger ? "text-danger" : "text-ink",
                  "data-[highlighted]:bg-accent-soft",
                  "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45",
                )}
              >
                {item.icon}
                {item.label}
              </RadixMenu.Item>
            ),
          )}
        </RadixMenu.Content>
      </RadixMenu.Portal>
    </RadixMenu.Root>
  );
}

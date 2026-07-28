import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "./cn";
import { IconButton } from "./IconButton";

export type DrawerSide = "left" | "right" | "bottom";

export interface DrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: ReactNode;
  children: ReactNode;
  side?: DrawerSide;
  contentClassName?: string;
}

const SIDE_CLASSES: Record<DrawerSide, string> = {
  left: "inset-y-0 left-0 h-full w-[280px] max-w-[85vw] border-r",
  right: "inset-y-0 right-0 h-full w-[min(420px,100vw)] border-l",
  bottom: "inset-x-0 bottom-0 max-h-[80vh] w-full rounded-t-3 border-t",
};

/**
 * Drawer = Dialog 变体：从侧 / 底部滑入（移动端目录、SourceSpanSheet 等）。
 */
export function Drawer({
  open,
  onOpenChange,
  title,
  children,
  side = "left",
  contentClassName,
}: DrawerProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-50 bg-[color-mix(in_srgb,var(--ink)_32%,transparent)]" />
        <RadixDialog.Content
          className={cn(
            "fixed z-50 flex flex-col border-line bg-raised shadow-overlay",
            SIDE_CLASSES[side],
            contentClassName,
          )}
        >
          <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-line px-4">
            {title != null ? (
              <RadixDialog.Title className="text-14 font-medium text-ink">
                {title}
              </RadixDialog.Title>
            ) : (
              <RadixDialog.Title className="sr-only">抽屉面板</RadixDialog.Title>
            )}
            <RadixDialog.Close asChild>
              <IconButton aria-label="关闭" size="sm">
                <X size={15} aria-hidden />
              </IconButton>
            </RadixDialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

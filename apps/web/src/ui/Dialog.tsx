import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "./cn";
import { IconButton } from "./IconButton";

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** 内容最大宽度，默认 max-w-md。 */
  contentClassName?: string;
}

/** Radix Dialog：overlay + 居中面板，Esc/点遮罩关闭。 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  contentClassName,
}: DialogProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-50 bg-[color-mix(in_srgb,var(--ink)_32%,transparent)]" />
        <RadixDialog.Content
          className={cn(
            "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-32px)] max-w-md -translate-x-1/2 -translate-y-1/2",
            "rounded-3 border border-line bg-raised p-6 shadow-overlay",
            "flex max-h-[85vh] flex-col gap-4 overflow-y-auto",
            contentClassName,
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <RadixDialog.Title className="font-serif text-20 text-ink">
                {title}
              </RadixDialog.Title>
              {description != null && (
                <RadixDialog.Description className="text-13 text-ink-2">
                  {description}
                </RadixDialog.Description>
              )}
            </div>
            <RadixDialog.Close asChild>
              <IconButton aria-label="关闭" size="sm">
                <X size={15} aria-hidden />
              </IconButton>
            </RadixDialog.Close>
          </div>
          <div className="min-h-0">{children}</div>
          {footer != null && (
            <div className="flex items-center justify-end gap-2 border-t border-line pt-4">
              {footer}
            </div>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

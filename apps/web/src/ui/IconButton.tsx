import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "./cn";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required: an icon button has no visible text. */
  "aria-label": string;
  size?: "sm" | "md";
  children: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { size = "md", className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-2 text-ink-2",
        "transition-colors duration-120 ease-out",
        "hover:not-disabled:bg-hover hover:not-disabled:text-ink active:not-disabled:bg-active",
        "disabled:cursor-not-allowed disabled:opacity-45",
        size === "sm" ? "size-7" : "size-8",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

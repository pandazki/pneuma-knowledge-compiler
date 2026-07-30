import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "./cn";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "default" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** In flight: the spinner moves into the button and re-submission is blocked. */
  loading?: boolean;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary: cn(
    "border border-accent bg-accent text-accent-ink",
    "hover:not-disabled:bg-[color-mix(in_srgb,var(--accent)_88%,var(--ink))]",
    "active:not-disabled:bg-[color-mix(in_srgb,var(--accent)_78%,var(--ink))]",
  ),
  default: cn(
    "border border-line-2 bg-surface text-ink",
    "hover:not-disabled:bg-hover active:not-disabled:bg-active",
  ),
  ghost: cn(
    "border border-transparent bg-transparent text-ink-2",
    "hover:not-disabled:bg-hover hover:not-disabled:text-ink active:not-disabled:bg-active",
  ),
  danger: cn(
    "border border-danger bg-transparent text-danger",
    "hover:not-disabled:bg-danger-soft active:not-disabled:bg-active",
  ),
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-7 gap-1.5 px-2.5 text-13",
  md: "h-9 gap-2 px-3.5 text-14",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", loading = false, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-2 font-medium",
        "transition-colors duration-120 ease-out select-none",
        "disabled:cursor-not-allowed disabled:opacity-45",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading && <Spinner size={size === "sm" ? 12 : 14} />}
      {children}
    </button>
  );
});

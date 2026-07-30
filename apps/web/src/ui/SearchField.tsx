import { forwardRef, type InputHTMLAttributes } from "react";
import { Search, X } from "lucide-react";
import { useT } from "@/lib/useT";
import { cn } from "./cn";

export interface SearchFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> {
  value: string;
  onChange: (value: string) => void;
  /** aria-label for the clear button; defaults to the shared "clear" copy. */
  clearLabel?: string;
  wrapperClassName?: string;
}

/**
 * Search input: Search-icon prefix + a hand-drawn clear button (the native clear button is
 * already stripped in the base layer).
 */
export const SearchField = forwardRef<HTMLInputElement, SearchFieldProps>(
  function SearchField(
    { value, onChange, clearLabel, wrapperClassName, className, disabled, ...rest },
    ref,
  ) {
    const t = useT();
    return (
      <div
        className={cn(
          "flex h-9 items-center gap-2 rounded-2 border border-line-2 bg-surface px-3",
          "transition-colors duration-120 ease-out",
          "focus-within:outline-2 focus-within:outline-accent focus-within:outline-offset-2",
          "hover:not-focus-within:border-ink-3",
          disabled && "opacity-45",
          wrapperClassName,
        )}
      >
        <Search size={15} aria-hidden className="shrink-0 text-ink-3" />
        <input
          ref={ref}
          type="search"
          role="searchbox"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className={cn(
            "h-full min-w-0 flex-1 text-14 text-ink focus-visible:outline-none",
            className,
          )}
          {...rest}
        />
        {value !== "" && !disabled && (
          <button
            type="button"
            aria-label={clearLabel ?? t("common.clear")}
            onClick={() => onChange("")}
            className="inline-flex size-5 shrink-0 items-center justify-center rounded-1 text-ink-3 hover:bg-hover hover:text-ink"
          >
            <X size={13} aria-hidden />
          </button>
        )}
      </div>
    );
  },
);

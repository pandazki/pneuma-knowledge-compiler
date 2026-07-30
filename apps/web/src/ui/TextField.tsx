import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { cn } from "./cn";

export interface TextFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "prefix" | "size"> {
  label?: ReactNode;
  hint?: ReactNode;
  /** Non-empty means the error state, and doubles as the error copy. */
  error?: ReactNode;
  prefix?: ReactNode;
  suffix?: ReactNode;
  /** className for the outer wrapper (layout). */
  wrapperClassName?: string;
}

/**
 * Controlled text input. The native appearance is stripped in the index.css base layer; the
 * focus ring sits on the wrapper (focus-within), the input itself has no outline.
 */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, prefix, suffix, id, className, wrapperClassName, disabled, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint || error ? `${inputId}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      {label != null && (
        <label htmlFor={inputId} className="text-13 font-medium text-ink-2">
          {label}
        </label>
      )}
      <div
        className={cn(
          "flex h-9 items-center gap-2 rounded-2 border bg-surface px-3",
          "transition-colors duration-120 ease-out",
          "focus-within:outline-2 focus-within:outline-accent focus-within:outline-offset-2",
          error ? "border-danger" : "border-line-2 hover:not-focus-within:border-ink-3",
          disabled && "opacity-45",
        )}
      >
        {prefix != null && <span className="shrink-0 text-ink-3">{prefix}</span>}
        <input
          ref={ref}
          id={inputId}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={hintId}
          className={cn(
            "h-full min-w-0 flex-1 text-14 text-ink focus-visible:outline-none",
            className,
          )}
          {...rest}
        />
        {suffix != null && <span className="shrink-0 text-ink-3">{suffix}</span>}
      </div>
      {(error || hint) && (
        <p id={hintId} className={cn("text-12", error ? "text-danger" : "text-ink-3")}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
});

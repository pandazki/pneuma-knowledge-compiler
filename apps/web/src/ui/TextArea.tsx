import {
  forwardRef,
  useId,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "./cn";

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Grow with the content, capped by maxRows. Do not pass `rows` alongside it. */
  autoRows?: boolean;
  maxRows?: number;
  wrapperClassName?: string;
}

/**
 * Multi-line input: native resize is disabled (resize-none); use autoRows when the height
 * needs to follow the content.
 */
export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  {
    label,
    hint,
    error,
    autoRows = false,
    maxRows,
    id,
    rows = 4,
    className,
    wrapperClassName,
    disabled,
    onChange,
    ...rest
  },
  ref,
) {
  const autoId = useId();
  const areaId = id ?? autoId;
  const hintId = hint || error ? `${areaId}-hint` : undefined;
  const innerRef = useRef<HTMLTextAreaElement | null>(null);

  const resize = () => {
    const el = innerRef.current;
    if (!el || !autoRows) return;
    el.style.height = "auto";
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 21;
    const max = maxRows ? maxRows * lineHeight + 16 : Infinity;
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
  };

  useLayoutEffect(resize, [rest.value, autoRows, maxRows]);

  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      {label != null && (
        <label htmlFor={areaId} className="text-13 font-medium text-ink-2">
          {label}
        </label>
      )}
      <textarea
        ref={(el) => {
          innerRef.current = el;
          if (typeof ref === "function") ref(el);
          else if (ref) ref.current = el;
        }}
        id={areaId}
        rows={autoRows ? Math.min(rows, maxRows ?? rows) : rows}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={hintId}
        onChange={(e) => {
          resize();
          onChange?.(e);
        }}
        className={cn(
          "w-full resize-none rounded-2 border bg-surface px-3 py-2 text-14 leading-[1.75] text-ink",
          "transition-colors duration-120 ease-out",
          "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
          error ? "border-danger" : "border-line-2 hover:not-focus-visible:border-ink-3",
          disabled && "opacity-45",
          autoRows && "overflow-y-auto",
          className,
        )}
        {...rest}
      />
      {(error || hint) && (
        <p id={hintId} className={cn("text-12", error ? "text-danger" : "text-ink-3")}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
});

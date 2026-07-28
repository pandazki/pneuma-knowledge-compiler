import { useId, type ReactNode } from "react";
import { Minus, Plus } from "lucide-react";
import { cn } from "./cn";

export interface NumberFieldProps {
  value: number | null;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  wrapperClassName?: string;
}

function clamp(v: number, min?: number, max?: number): number {
  if (min != null && v < min) return min;
  if (max != null && v > max) return max;
  return v;
}

/**
 * 数值输入：type=text + inputMode 自绘（原生 spinner 已全局清除），
 * ± stepper 按钮与 ArrowUp/Down 键盘步进，blur 时 clamp。
 */
export function NumberField({
  value,
  onChange,
  min,
  max,
  step = 1,
  label,
  hint,
  error,
  disabled,
  id,
  wrapperClassName,
  ...rest
}: NumberFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint || error ? `${inputId}-hint` : undefined;

  const commit = (next: number | null) => {
    if (next == null || Number.isNaN(next)) {
      onChange(null);
      return;
    }
    onChange(clamp(next, min, max));
  };

  const stepBy = (dir: 1 | -1) => {
    const base = value ?? min ?? 0;
    commit(base + dir * step);
  };

  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      {label != null && (
        <label htmlFor={inputId} className="text-13 font-medium text-ink-2">
          {label}
        </label>
      )}
      <div
        className={cn(
          "flex h-9 items-stretch rounded-2 border bg-surface",
          "transition-colors duration-120 ease-out",
          "focus-within:outline-2 focus-within:outline-accent focus-within:outline-offset-2",
          error ? "border-danger" : "border-line-2 hover:not-focus-within:border-ink-3",
          disabled && "opacity-45",
        )}
      >
        <input
          id={inputId}
          type="text"
          inputMode="numeric"
          role="spinbutton"
          aria-valuenow={value ?? undefined}
          aria-valuemin={min}
          aria-valuemax={max}
          aria-invalid={error ? true : undefined}
          aria-describedby={hintId}
          disabled={disabled}
          value={value ?? ""}
          onChange={(e) => {
            const raw = e.target.value.trim();
            if (raw === "") onChange(null);
            else if (/^-?\d*\.?\d*$/.test(raw)) onChange(Number(raw));
          }}
          onBlur={(e) => commit(e.target.value.trim() === "" ? null : Number(e.target.value))}
          onKeyDown={(e) => {
            if (e.key === "ArrowUp") {
              e.preventDefault();
              stepBy(1);
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              stepBy(-1);
            }
          }}
          className="h-full min-w-0 flex-1 px-3 text-14 text-ink tabular-nums"
          {...rest}
        />
        <div className="flex shrink-0 items-center border-l border-line">
          <button
            type="button"
            tabIndex={-1}
            aria-label="减少"
            disabled={disabled || (min != null && value != null && value <= min)}
            onClick={() => stepBy(-1)}
            className="inline-flex h-full w-8 items-center justify-center text-ink-2 hover:not-disabled:bg-hover disabled:opacity-40"
          >
            <Minus size={13} aria-hidden />
          </button>
          <button
            type="button"
            tabIndex={-1}
            aria-label="增加"
            disabled={disabled || (max != null && value != null && value >= max)}
            onClick={() => stepBy(1)}
            className="inline-flex h-full w-8 items-center justify-center border-l border-line text-ink-2 hover:not-disabled:bg-hover disabled:opacity-40"
          >
            <Plus size={13} aria-hidden />
          </button>
        </div>
      </div>
      {(error || hint) && (
        <p id={hintId} className={cn("text-12", error ? "text-danger" : "text-ink-3")}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

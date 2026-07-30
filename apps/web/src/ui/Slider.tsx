import * as RadixSlider from "@radix-ui/react-slider";
import type { ReactNode } from "react";
import { cn } from "./cn";

export interface SliderProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  label?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  /** Show the current value in mono on the right (on by default). */
  showValue?: boolean;
  formatValue?: (value: number) => string;
  "aria-label"?: string;
  wrapperClassName?: string;
}

/** Radix Slider: track / range / thumb all drawn here; current value on the right. */
export function Slider({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  label,
  hint,
  disabled,
  showValue = true,
  formatValue = (v) => String(v),
  wrapperClassName,
  ...rest
}: SliderProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      {(label != null || showValue) && (
        <div className="flex items-baseline justify-between gap-3">
          {label != null && <span className="text-13 font-medium text-ink-2">{label}</span>}
          {showValue && (
            <span className="font-mono text-13 text-ink tabular-nums">{formatValue(value)}</span>
          )}
        </div>
      )}
      <RadixSlider.Root
        className="relative flex h-5 w-full touch-none items-center select-none"
        value={[value]}
        onValueChange={([v]) => onChange(v)}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        aria-label={rest["aria-label"]}
      >
        <RadixSlider.Track className="relative h-0.5 grow overflow-visible rounded-full bg-line-2">
          <RadixSlider.Range className="absolute h-full bg-accent" />
        </RadixSlider.Track>
        <RadixSlider.Thumb
          className={cn(
            "block size-3.5 rounded-full border border-line-2 bg-raised",
            "transition-colors duration-120 hover:border-accent",
            "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2",
            "disabled:opacity-45",
          )}
          aria-label={rest["aria-label"]}
        />
      </RadixSlider.Root>
      {hint != null && <p className="text-12 text-ink-3">{hint}</p>}
    </div>
  );
}

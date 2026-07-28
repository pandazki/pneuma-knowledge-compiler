import * as RadixRadio from "@radix-ui/react-radio-group";
import type { ReactNode } from "react";
import { cn } from "./cn";

export interface RadioOption {
  value: string;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}

export interface RadioGroupProps {
  value: string | null;
  onChange: (value: string) => void;
  options: RadioOption[];
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  "aria-label"?: string;
  wrapperClassName?: string;
}

export function RadioGroup({
  value,
  onChange,
  options,
  label,
  hint,
  error,
  disabled,
  wrapperClassName,
  ...rest
}: RadioGroupProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      {label != null && <span className="text-13 font-medium text-ink-2">{label}</span>}
      <RadixRadio.Root
        value={value ?? undefined}
        onValueChange={onChange}
        disabled={disabled}
        aria-label={rest["aria-label"]}
        className="flex flex-col gap-2"
      >
        {options.map((opt) => (
          <div key={opt.value} className="flex items-start gap-2.5">
            <RadixRadio.Item
              value={opt.value}
              disabled={opt.disabled}
              className={cn(
                "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border border-line-2 bg-surface",
                "transition-colors duration-120 ease-out hover:not-disabled:border-ink-3",
                "data-[state=checked]:border-accent",
                "disabled:cursor-not-allowed disabled:opacity-45",
              )}
            >
              <RadixRadio.Indicator className="block size-2 rounded-full bg-accent" />
            </RadixRadio.Item>
            <div className="flex flex-col">
              <label
                className={cn(
                  "text-14 text-ink",
                  (disabled || opt.disabled) && "opacity-45",
                )}
              >
                {opt.label}
              </label>
              {opt.description != null && (
                <span className="text-12 text-ink-3">{opt.description}</span>
              )}
            </div>
          </div>
        ))}
      </RadixRadio.Root>
      {(error || hint) && (
        <p className={cn("text-12", error ? "text-danger" : "text-ink-3")}>{error ?? hint}</p>
      )}
    </div>
  );
}

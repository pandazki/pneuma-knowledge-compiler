import * as RadixCheckbox from "@radix-ui/react-checkbox";
import { useId, type ReactNode } from "react";
import { Check, Minus } from "lucide-react";
import { cn } from "./cn";

export interface CheckboxProps {
  checked: boolean | "indeterminate";
  onCheckedChange: (checked: boolean | "indeterminate") => void;
  label?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  wrapperClassName?: string;
}

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
  id,
  wrapperClassName,
  ...rest
}: CheckboxProps) {
  const autoId = useId();
  const boxId = id ?? autoId;
  return (
    <div className={cn("flex flex-col gap-1", wrapperClassName)}>
      <div className="flex items-center gap-2.5">
        <RadixCheckbox.Root
          id={boxId}
          checked={checked}
          onCheckedChange={onCheckedChange}
          disabled={disabled}
          aria-label={rest["aria-label"]}
          className={cn(
            "flex size-4 shrink-0 items-center justify-center rounded-1 border border-line-2 bg-surface",
            "transition-colors duration-120 ease-out hover:not-disabled:border-ink-3",
            "data-[state=checked]:border-accent data-[state=checked]:bg-accent",
            "data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent",
            "disabled:cursor-not-allowed disabled:opacity-45",
          )}
        >
          <RadixCheckbox.Indicator className="text-accent-ink">
            {checked === "indeterminate" ? (
              <Minus size={12} aria-hidden />
            ) : (
              <Check size={12} aria-hidden />
            )}
          </RadixCheckbox.Indicator>
        </RadixCheckbox.Root>
        {label != null && (
          <label htmlFor={boxId} className="text-14 text-ink">
            {label}
          </label>
        )}
      </div>
      {hint != null && <p className="pl-[26px] text-12 text-ink-3">{hint}</p>}
    </div>
  );
}

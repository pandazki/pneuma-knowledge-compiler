import * as RadixSwitch from "@radix-ui/react-switch";
import { useId, type ReactNode } from "react";
import { cn } from "./cn";

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  wrapperClassName?: string;
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
  id,
  wrapperClassName,
  ...rest
}: SwitchProps) {
  const autoId = useId();
  const switchId = id ?? autoId;
  return (
    <div className={cn("flex flex-col gap-1", wrapperClassName)}>
      <div className="flex items-center gap-2.5">
        <RadixSwitch.Root
          id={switchId}
          checked={checked}
          onCheckedChange={onCheckedChange}
          disabled={disabled}
          aria-label={rest["aria-label"]}
          className={cn(
            "relative h-[18px] w-8 shrink-0 rounded-full border border-line-2 bg-line",
            "transition-colors duration-120 ease-out",
            "data-[state=checked]:border-accent data-[state=checked]:bg-accent",
            "disabled:cursor-not-allowed disabled:opacity-45",
          )}
        >
          <RadixSwitch.Thumb
            className={cn(
              "block size-3 rounded-full bg-raised transition-transform duration-120 ease-out",
              "translate-x-[3px] data-[state=checked]:translate-x-[17px]",
            )}
          />
        </RadixSwitch.Root>
        {label != null && (
          <label htmlFor={switchId} className="text-14 text-ink">
            {label}
          </label>
        )}
      </div>
      {hint != null && <p className="pl-[42px] text-12 text-ink-3">{hint}</p>}
    </div>
  );
}

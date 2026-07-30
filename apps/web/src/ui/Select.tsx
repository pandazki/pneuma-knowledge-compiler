import { useId, type ReactNode } from "react";
import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { useT } from "@/lib/useT";
import { cn } from "./cn";

export interface SelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
}

export interface SelectProps {
  value: string | null;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  wrapperClassName?: string;
}

/** Radix Select with a hand-drawn trigger / listbox / item (check mark + scroll buttons). */
export function Select({
  value,
  onChange,
  options,
  placeholder,
  label,
  hint,
  error,
  disabled,
  id,
  wrapperClassName,
  ...rest
}: SelectProps) {
  const t = useT();
  const autoId = useId();
  const triggerId = id ?? autoId;
  const hintId = hint || error ? `${triggerId}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      {label != null && (
        <label htmlFor={triggerId} className="text-13 font-medium text-ink-2">
          {label}
        </label>
      )}
      <RadixSelect.Root
        // null is normalised to "": Radix reads undefined as uncontrolled, so an async
        // vocabulary arriving later would flip uncontrolled → controlled and warn. "" is a
        // legitimate controlled empty value (the placeholder still shows).
        value={value ?? ""}
        onValueChange={onChange}
        disabled={disabled}
      >
        <RadixSelect.Trigger
          id={triggerId}
          aria-invalid={error ? true : undefined}
          aria-describedby={hintId}
          aria-label={rest["aria-label"]}
          className={cn(
            "flex h-9 w-full items-center justify-between gap-2 rounded-2 border bg-surface px-3 text-14 text-ink",
            "transition-colors duration-120 ease-out",
            error ? "border-danger" : "border-line-2 hover:not-focus-visible:border-ink-3",
            "disabled:cursor-not-allowed disabled:opacity-45",
            "data-[placeholder]:text-ink-3",
          )}
        >
          <RadixSelect.Value placeholder={placeholder ?? t("common.selectPlaceholder")} />
          <RadixSelect.Icon>
            <ChevronDown size={15} aria-hidden className="text-ink-3" />
          </RadixSelect.Icon>
        </RadixSelect.Trigger>
        <RadixSelect.Portal>
          <RadixSelect.Content
            position="popper"
            sideOffset={4}
            className={cn(
              "z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-3 border border-line bg-raised shadow-overlay",
            )}
          >
            <RadixSelect.ScrollUpButton className="flex h-6 items-center justify-center text-ink-3">
              <ChevronUp size={14} aria-hidden />
            </RadixSelect.ScrollUpButton>
            <RadixSelect.Viewport className="p-1">
              {options.map((opt) => (
                <RadixSelect.Item
                  key={opt.value}
                  value={opt.value}
                  disabled={opt.disabled}
                  className={cn(
                    "flex cursor-pointer items-center justify-between gap-2 rounded-1 px-2.5 py-1.5 text-14 text-ink",
                    "outline-none data-[highlighted]:bg-accent-soft",
                    "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45",
                  )}
                >
                  <RadixSelect.ItemText>{opt.label}</RadixSelect.ItemText>
                  <RadixSelect.ItemIndicator>
                    <Check size={14} aria-hidden className="text-accent" />
                  </RadixSelect.ItemIndicator>
                </RadixSelect.Item>
              ))}
            </RadixSelect.Viewport>
            <RadixSelect.ScrollDownButton className="flex h-6 items-center justify-center text-ink-3">
              <ChevronDown size={14} aria-hidden />
            </RadixSelect.ScrollDownButton>
          </RadixSelect.Content>
        </RadixSelect.Portal>
      </RadixSelect.Root>
      {(error || hint) && (
        <p id={hintId} className={cn("text-12", error ? "text-danger" : "text-ink-3")}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

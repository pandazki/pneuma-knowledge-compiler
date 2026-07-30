import * as RadixTabs from "@radix-ui/react-tabs";
import { cn } from "./cn";

export interface SegmentedControlProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; disabled?: boolean }[];
  "aria-label": string;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Segmented picker built on Radix Tabs (fast/deep/rag mode switching). It renders only the
 * triggers, never a panel — the caller switches its own content off `value`.
 */
export function SegmentedControl({
  value,
  onChange,
  options,
  size = "md",
  className,
  ...rest
}: SegmentedControlProps) {
  return (
    <RadixTabs.Root value={value} onValueChange={onChange}>
      <RadixTabs.List
        aria-label={rest["aria-label"]}
        className={cn(
          "inline-flex items-stretch overflow-hidden rounded-2 border border-line-2 bg-surface",
          className,
        )}
      >
        {options.map((opt, i) => (
          <RadixTabs.Trigger
            key={opt.value}
            value={opt.value}
            disabled={opt.disabled}
            className={cn(
              "px-3 text-13 text-ink-2 transition-colors duration-120 ease-out",
              size === "sm" ? "h-7" : "h-8",
              i > 0 && "border-l border-line",
              "hover:not-disabled:not-data-[state=active]:bg-hover",
              "data-[state=active]:bg-accent-soft data-[state=active]:font-medium data-[state=active]:text-ink",
              "disabled:cursor-not-allowed disabled:opacity-45",
            )}
          >
            {opt.label}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
    </RadixTabs.Root>
  );
}

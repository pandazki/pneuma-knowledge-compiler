import * as RadixTabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cn } from "./cn";

export interface TabItem {
  value: string;
  label: ReactNode;
  panel: ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  value: string;
  onChange: (value: string) => void;
  tabs: TabItem[];
  "aria-label": string;
  className?: string;
  /**
   * Sizing for the active panel. Needed by a tab set inside a pinned pane, where the panel
   * has to fill the remaining height (`flex-1 min-h-0 flex flex-col`) so its own ScrollRegion
   * has a bound to scroll within; in ordinary page flow the default padding is right.
   */
  contentClassName?: string;
}

/** Radix Tabs: underline style, hairline separator. */
export function Tabs({ value, onChange, tabs, className, contentClassName, ...rest }: TabsProps) {
  return (
    <RadixTabs.Root value={value} onValueChange={onChange} className={className}>
      <RadixTabs.List
        aria-label={rest["aria-label"]}
        className="flex shrink-0 items-stretch gap-1 border-b border-line"
      >
        {tabs.map((tab) => (
          <RadixTabs.Trigger
            key={tab.value}
            value={tab.value}
            disabled={tab.disabled}
            className={cn(
              "-mb-px h-9 border-b-2 border-transparent px-3 text-14 text-ink-2",
              "transition-colors duration-120 ease-out",
              "hover:not-disabled:not-data-[state=active]:text-ink",
              "data-[state=active]:border-accent data-[state=active]:font-medium data-[state=active]:text-ink",
              "disabled:cursor-not-allowed disabled:opacity-45",
            )}
          >
            {tab.label}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {tabs.map((tab) => (
        <RadixTabs.Content
          key={tab.value}
          value={tab.value}
          className={cn("outline-none", contentClassName ?? "pt-4")}
        >
          {tab.panel}
        </RadixTabs.Content>
      ))}
    </RadixTabs.Root>
  );
}

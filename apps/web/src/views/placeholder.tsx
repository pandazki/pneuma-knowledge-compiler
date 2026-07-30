import type { LucideIcon } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { useT } from "@/lib/useT";
import { EmptyState } from "@/ui/EmptyState";

export interface PlaceholderViewProps {
  title: string;
  description: string;
  icon: LucideIcon;
}

/** The shared stand-in for a view not yet built: PageHeader + a "being typeset" EmptyState. */
export function PlaceholderView({ title, description, icon }: PlaceholderViewProps) {
  const t = useT();
  return (
    <>
      <PageHeader title={title} description={description} />
      <EmptyState
        icon={icon}
        title={t("common.placeholder.title")}
        description={t("common.placeholder.description")}
      />
    </>
  );
}

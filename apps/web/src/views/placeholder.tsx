import type { LucideIcon } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/ui/EmptyState";

export interface PlaceholderViewProps {
  title: string;
  description: string;
  icon: LucideIcon;
}

/** 视图阶段替换实现前的统一占位：PageHeader + EmptyState「本篇正在排版」。 */
export function PlaceholderView({ title, description, icon }: PlaceholderViewProps) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <EmptyState
        icon={icon}
        title="本篇正在排版"
        description="地基阶段已铺好设计系统与应用外壳，本视图将在下一阶段实现。"
      />
    </>
  );
}

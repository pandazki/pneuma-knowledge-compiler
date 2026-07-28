import type { CSSProperties, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  Bot,
  Database,
  History,
  MessageSquarePlus,
  MessagesSquare,
  Network,
  Radar,
  Sparkles,
  UserRound,
  Workflow,
} from "lucide-react";
import type { ViewName } from "@/lib/types";

export interface RouteMeta {
  code: string;
  name: string;
  description: string;
  color: string;
  icon: LucideIcon;
}

export const ROUTE_META: Record<Exclude<ViewName, "overview">, RouteMeta> = {
  ingest: {
    code: "R1",
    name: "材料入口",
    description: "把对话或文档送入编译网络，先预览计划，再决定是否落库。",
    color: "var(--route-scarlet)",
    icon: MessageSquarePlus,
  },
  recall: {
    code: "R2",
    name: "双层检索",
    description: "并排观察 Meilisearch L1 与 Qdrant L2 怎样召回可引用的证据。",
    color: "var(--route-cobalt)",
    icon: Radar,
  },
  context_stream: {
    code: "R3",
    name: "主动提示",
    description: "模拟 AI 在上下文变化时，何时选择提示、沉默或丢弃候选。",
    color: "var(--route-amber)",
    icon: Bot,
  },
  sources: {
    code: "S0",
    name: "来源档案",
    description: "回到不可替代的原始材料，逐段核对摄取计划与引用位置。",
    color: "var(--route-green)",
    icon: Database,
  },
  library: {
    code: "C1",
    name: "Canonical",
    description: "阅读编译后的知识文档，并沿 claim 的稳定锚点回到证据。",
    color: "var(--route-scarlet)",
    icon: BookOpen,
  },
  history: {
    code: "G1",
    name: "版本轨道",
    description: "检查每次 patch、bundle 与 Git 快照怎样改变 canonical。",
    color: "var(--route-cobalt)",
    icon: History,
  },
  process: {
    code: "P1",
    name: "编译作业",
    description: "观察 source、job、patch 与 lineage 的运行状态和处理边界。",
    color: "var(--route-amber)",
    icon: Workflow,
  },
  graph: {
    code: "X1",
    name: "关系换乘",
    description: "从一份文档出发，查看知识对象之间可追踪的链接与关系。",
    color: "var(--route-green)",
    icon: Network,
  },
  ask: {
    code: "A1",
    name: "连续问答",
    description: "先冻结证据包，再进行可回溯的多轮问答。",
    color: "var(--route-cobalt)",
    icon: MessagesSquare,
  },
  profile: {
    code: "U1",
    name: "工作画像",
    description: "设定个人开发者的工作语境、回答层级与隐私偏好。",
    color: "var(--route-green)",
    icon: UserRound,
  },
  evolve: {
    code: "E1",
    name: "策略演化",
    description: "审阅结构变化建议，让策略保持显式、可比较、可回滚。",
    color: "var(--route-scarlet)",
    icon: Sparkles,
  },
};

export function RouteFrame({
  view,
  children,
}: {
  view: Exclude<ViewName, "overview">;
  children: ReactNode;
}) {
  const meta = ROUTE_META[view];
  const Icon = meta.icon;

  return (
    <section
      className="pneuma-station-page"
      style={{ "--station-color": meta.color } as CSSProperties}
    >
      <header className="pneuma-station-intro">
        <span className="pneuma-station-code">
          <i aria-hidden />
          {meta.code}
        </span>
        <span className="pneuma-station-icon" aria-hidden>
          <Icon size={17} strokeWidth={1.8} />
        </span>
        <div>
          <h2>{meta.name}</h2>
          <p>{meta.description}</p>
        </div>
      </header>
      <div className="pneuma-station-workbench">{children}</div>
    </section>
  );
}

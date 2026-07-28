import { useEffect, useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { useApp } from "@/lib/store";
import { listJobs, listSources } from "@/lib/api";
import type { ViewName } from "@/lib/types";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { Skeleton } from "@/ui/Skeleton";
import { Stamp } from "@/ui/Stamp";
import { cn } from "@/ui/cn";

/* ---------------------------------------------------------- 标尺线生产流程图 */

interface FlowNode {
  no: string;
  name: string;
  caption: string;
  view: ViewName;
  /** null = 加载中（Skeleton）；undefined = 无数据 / 无用户（—）。 */
  count: number | null | undefined;
  unit: string;
}

function FlowChart({ nodes }: { nodes: FlowNode[] }) {
  const setView = useApp((s) => s.setView);
  return (
    <ol
      aria-label="生产流程：原料、编译、正典、取用"
      className="flex flex-col border-l border-line sm:grid sm:grid-cols-4 sm:gap-x-6 sm:border-t sm:border-l-0"
    >
      {nodes.map((node) => (
        <li key={node.no} className="min-w-0">
          <button
            type="button"
            onClick={() => setView(node.view)}
            className={cn(
              "group flex w-full flex-col items-start gap-1 py-4 pl-4 text-left sm:py-0 sm:pt-4 sm:pl-0",
              "transition-colors duration-120 ease-out",
            )}
          >
            {/* 标尺刻度：宽屏竖刻度挂在顶线上，窄屏横刻度挂在左线上 */}
            <span
              aria-hidden
              className="hidden h-3 w-px bg-line-2 sm:-mt-4 sm:block"
            />
            <span className="flex items-baseline gap-2">
              <span className="font-mono text-12 text-accent">{node.no}</span>
              <span className="font-serif text-20 text-ink group-hover:text-accent">
                {node.name}
              </span>
            </span>
            <span className="text-13 text-ink-3">{node.caption}</span>
            <span className="mt-2 flex items-baseline gap-2" aria-live="polite">
              {node.count === null ? (
                <Skeleton className="h-7 w-12" />
              ) : node.count === undefined ? (
                <span className="font-serif text-24 text-ink-3">—</span>
              ) : (
                <span className="font-serif text-24 text-accent tabular-nums">
                  {node.count}
                </span>
              )}
              <span className="text-12 text-ink-3">{node.unit}</span>
            </span>
            <span className="mt-1 inline-flex items-center gap-1 text-12 text-accent opacity-0 transition-opacity duration-120 group-hover:opacity-100 group-focus-visible:opacity-100">
              进入本篇 <ArrowRight size={12} aria-hidden />
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

/* --------------------------------------------------------------- 翻阅指引 */

interface GuideItem {
  no: string;
  title: string;
  body: string;
  view: ViewName;
}

const GUIDE: GuideItem[] = [
  {
    no: "01",
    title: "导入一份材料",
    body: "从粘贴文本、文件或一段会话开始，先看机械预览与编译计划，再确认入库。",
    view: "ingest",
  },
  {
    no: "02",
    title: "看编译如何发生",
    body: "每次 compile 都是一行账：来源、状态、耗时与模型 lineage，逐条可查。",
    view: "process",
  },
  {
    no: "03",
    title: "读编译出的正典",
    body: "每条 claim 带稳定锚点与脚注，随手一条都能回到精确的 source span。",
    view: "library",
  },
  {
    no: "04",
    title: "试三个取用面",
    body: "同一句问题，对比检索、连续问答与主动提示——全都受引用门禁约束。",
    view: "recall",
  },
  {
    no: "05",
    title: "核对版本历史",
    body: "快照、job 与 patch 在同一条 Git 时间线上，任何版本都可只读回看。",
    view: "history",
  },
  {
    no: "06",
    title: "看 skill 如何演化",
    body: "schema-evolve 的提案、对照与采纳 / 放弃，决定正典下一步怎么长。",
    view: "evolve",
  },
];

/* -------------------------------------------------------------------- 视图 */

export default function OverviewView() {
  const currentUser = useApp((s) => s.currentUser);
  const usersError = useApp((s) => s.usersError);
  const dataset = useApp((s) => s.dataset);
  const snapshots = useApp((s) => s.snapshots);
  const setView = useApp((s) => s.setView);

  // 流程图实时计数：sources / jobs 走服务 API；documents+claims / snapshots 读 store。
  const [sourceCount, setSourceCount] = useState<number | null>(null);
  const [jobCount, setJobCount] = useState<number | null>(null);
  const [countsLoaded, setCountsLoaded] = useState(false);

  useEffect(() => {
    if (!currentUser) {
      setSourceCount(null);
      setJobCount(null);
      setCountsLoaded(false);
      return;
    }
    let live = true;
    setCountsLoaded(false);
    Promise.allSettled([listSources(currentUser), listJobs(currentUser)]).then(
      ([sources, jobs]) => {
        if (!live) return;
        setSourceCount(sources.status === "fulfilled" ? sources.value.length : null);
        setJobCount(jobs.status === "fulfilled" ? jobs.value.length : null);
        setCountsLoaded(true);
      },
    );
    return () => {
      live = false;
    };
  }, [currentUser]);

  const docClaimCount = useMemo(() => {
    if (!dataset) return undefined;
    const docs = dataset.documents?.documents ?? [];
    return docs.reduce((sum, d) => sum + (d.claims?.length ?? 0), 0) + docs.length;
  }, [dataset]);

  /** 计数三态：加载中 null→Skeleton；无用户 / 加载失败 undefined→—；否则数字。 */
  const asCount = (loaded: boolean, value: number | null): number | null | undefined => {
    if (!currentUser) return undefined;
    if (!loaded) return null;
    return value ?? undefined;
  };

  const nodes: FlowNode[] = [
    {
      no: "§1",
      name: "原料",
      caption: "source 按原貌入库，可定位",
      view: "sources",
      count: asCount(countsLoaded, sourceCount),
      unit: "条 source",
    },
    {
      no: "§2",
      name: "编译",
      caption: "compile job 取证与合并",
      view: "process",
      count: asCount(countsLoaded, jobCount),
      unit: "个 job",
    },
    {
      no: "§3",
      name: "正典",
      caption: "canonical 文档与 claim",
      view: "library",
      count: currentUser ? docClaimCount : undefined,
      unit: "文档 + claim",
    },
    {
      no: "§4",
      name: "取用",
      caption: "检索 / 问答 / 提示，带门禁",
      view: "recall",
      count: currentUser ? snapshots.length : undefined,
      unit: "个版本快照",
    },
  ];

  return (
    <div className="flex flex-col gap-10">
      {usersError && (
        <Callout tone="warn" title="服务不可达">
          无法连接 pneuma-knowledge 服务（{usersError}），下方实时计数暂不可用，翻阅指引仍可使用。
        </Callout>
      )}

      {/* 题字 + 编者说明 */}
      <header className="max-w-measure">
        <h1 className="font-serif text-30 text-balance text-ink sm:text-38">
          把持续产生的材料，编译成可追溯的知识。
        </h1>
        <p className="prose-lede mt-4">
          这是一台知识编译器：对话、文档与实验材料先落成可定位的原料（source），
          经编译工序取证、合并、标注争议，产出带稳定锚点的正典（canonical），
          再经检索、问答与主动提示三个取用面回到手边。每个 claim 都能回到精确的
          source span，取用面受引用门禁约束——没有出处的内容不会被当作事实递出。
          本页与全部演示数据均为可复现的合成数据。
        </p>
      </header>

      {/* 标尺线生产流程图 */}
      <section>
        <SectionRule no={1} title="生产流程" className="mb-6" />
        <FlowChart nodes={nodes} />
        <p className="mt-3 text-12 text-ink-3">
          计数来自当前选中用户的实时数据；未选择用户或尚无数据时显示 —。
        </p>
      </section>

      {/* L0–L3 定义表 */}
      <section>
        <SectionRule no={2} title="四层结构" className="mb-2" />
        <DefinitionList
          termClassName="sm:w-28"
          items={[
            {
              term: <Mono>L0</Mono>,
              definition:
                "原始来源。对话、文档、代码片段按原貌入库，每段都有可定位的 source_id 与 block 编号——证据层，不可伪造。",
            },
            {
              term: <Mono>L1</Mono>,
              definition:
                "词法索引。Meilisearch 低延迟字面检索；索引只是投影，随时可从 L0 重建，不反向定义事实。",
            },
            {
              term: <Mono>L2</Mono>,
              definition:
                "语义索引。向量召回与 L1 融合排序，补上字面之外的邻近；同为可重建投影。",
            },
            {
              term: <Mono>L3</Mono>,
              definition:
                "canonical Git 仓库。编译产物的唯一事实形态——文档、claim 锚点与 patch 全部进 Git，可审阅、比较、回滚、快照。",
            },
          ]}
        />
      </section>

      {/* 翻阅指引 */}
      <section>
        <SectionRule no={3} title="翻阅指引" className="mb-2" />
        <ol className="flex flex-col">
          {GUIDE.map((item) => (
            <li key={item.no} className="border-t border-line first:border-t-0">
              <button
                type="button"
                onClick={() => setView(item.view)}
                className={cn(
                  "group flex w-full items-baseline gap-3 py-3 text-left",
                  "transition-colors duration-120 ease-out hover:bg-hover",
                )}
              >
                <span className="w-7 shrink-0 font-mono text-12 text-accent">{item.no}</span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
                  <span className="shrink-0 font-serif text-16 text-ink group-hover:text-accent sm:w-40">
                    {item.title}
                  </span>
                  <span className="min-w-0 flex-1 text-13 text-ink-2">{item.body}</span>
                </span>
                <ArrowRight
                  size={14}
                  aria-hidden
                  className="shrink-0 self-center text-ink-3 group-hover:text-accent"
                />
              </button>
            </li>
          ))}
        </ol>
      </section>

      {/* synthetic 披露 */}
      <section className="border-t border-line pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <Stamp tone="neutral">SYNTHETIC DEMO DATA</Stamp>
          <p className="max-w-measure text-13 text-ink-2">
            演示数据全部可复现合成：用户画像、source、canonical 与版本历史均由确定性生成器产出，
            可在本地完整重放，不包含任何真实用户内容。
          </p>
        </div>
      </section>
    </div>
  );
}

import { useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  Braces,
  Check,
  FlaskConical,
  GitCommitHorizontal,
  Layers3,
  Play,
  Route,
} from "lucide-react";
import { useApp } from "@/lib/store";
import {
  KnowledgeRouteMap,
  KNOWLEDGE_STATIONS,
  type StationId,
} from "@/components/KnowledgeRouteMap";
import { Button, Chip } from "@/components/ui";

const STATION_COPY: Record<StationId, { title: string; body: string; status: string }> = {
  source: {
    title: "材料先保持原貌",
    body: "对话、文档和代码片段先成为可定位的 source。编译结果可以重做，原始证据不可伪造。",
    status: "AUTHORITATIVE",
  },
  postgres: {
    title: "权威事实落在一处",
    body: "PostgreSQL 保存 source、摄取计划、job 和状态机；它是服务层的事实来源。",
    status: "AUTHORITATIVE",
  },
  meili: {
    title: "L1 找到准确字面",
    body: "Meilisearch 负责低延迟词法检索。索引随时可以从权威来源重建，不反向定义事实。",
    status: "REBUILDABLE",
  },
  qdrant: {
    title: "L2 补上语义邻近",
    body: "Qdrant 承担向量召回，与 L1 合并后交给排序和引用门禁。",
    status: "REBUILDABLE",
  },
  compile: {
    title: "编译门不直接相信生成",
    body: "编译器取证、合并、标注争议并记录 lineage；不能证明的内容不会伪装成 canonical。",
    status: "GATED",
  },
  git: {
    title: "知识最终成为版本",
    body: "Canonical 文档、稳定锚点和 patch 进入 Git，支持审阅、比较、回滚与历史快照。",
    status: "VERSIONED",
  },
};

export function OverviewView() {
  const { model, currentProfile, currentUser, snapshots, setView, jump } = useApp();
  const [selected, setSelected] = useState<StationId>("source");
  const station = KNOWLEDGE_STATIONS.find((item) => item.id === selected)!;
  const copy = STATION_COPY[selected];

  const counts = useMemo(() => {
    const dataset = model?.dataset;
    const documents = dataset?.documents.documents ?? [];
    return {
      sources: dataset?.timeline.snapshots.length ?? 0,
      documents: documents.length,
      claims: documents.reduce((sum, document) => sum + document.claims.length, 0),
      patches: dataset?.timeline.patches.length ?? 0,
    };
  }, [model]);

  const trace = useMemo(() => {
    if (!model) return null;
    for (const document of model.dataset.documents.documents) {
      for (const claim of document.claims) {
        const citation = claim.citations[0];
        if (!citation) continue;
        const patches = document.document_id
          ? model.patchesByDocId.get(document.document_id) ?? []
          : model.patchesByPath.get(document.path) ?? [];
        return {
          source: citation.source_id,
          span: `¶${citation.from}–${citation.to}`,
          snippet: citation.snippet || claim.text,
          claim: claim.anchor ?? "claim",
          document,
          patch: patches[patches.length - 1] ?? null,
        };
      }
    }
    return null;
  }, [model]);

  return (
    <div className="pneuma-overview">
      <section className="overview-opening">
        <div className="overview-opening-copy">
          <span className="overview-kicker">
            <Route size={14} /> OPEN-SOURCE SYSTEM MAP
          </span>
          <h2>
            把个人知识
            <br />
            编译成可验证的版本。
          </h2>
          <p>
            Pneuma 不是一块堆资料的面板。它把 source、双层检索、编译门与 Git
            串成一条可运行、可重建、可追溯的个人知识线路。
          </p>
        </div>

        <div className="overview-route-actions" aria-label="演示路线">
          <span>从这里开始</span>
          <Button variant="primary" onClick={() => setView("ingest")}>
            <Play size={14} fill="currentColor" /> 回放一份材料
          </Button>
          <Button variant="ghost" onClick={() => setView("recall")}>
            运行检索实验 <ArrowRight size={14} />
          </Button>
        </div>
      </section>

      <section className="overview-map-stage" aria-label="知识编译系统线路">
        <KnowledgeRouteMap
          selected={selected}
          onSelect={setSelected}
          activeTrace={selected === "source" && Boolean(trace)}
        />
        <aside className="station-destination-sheet" aria-live="polite">
          <div className="destination-sheet-head">
            <span style={{ background: station.color }} aria-hidden />
            <b>{station.code}</b>
            <small>{selected === "source" && trace ? "LIVE TRACE" : copy.status}</small>
          </div>
          {selected === "source" && trace ? (
            <>
              <h3>一条真实证据线路已点亮</h3>
              <blockquote className="destination-trace-quote">“{trace.snippet}”</blockquote>
              <dl className="destination-trace-list">
                <div>
                  <dt>SOURCE / SPAN</dt>
                  <dd>
                    {trace.source} · {trace.span}
                  </dd>
                </div>
                <div>
                  <dt>CLAIM ANCHOR</dt>
                  <dd>{trace.claim}</dd>
                </div>
                <div>
                  <dt>CANONICAL</dt>
                  <dd>{trace.document.path}</dd>
                </div>
                <div>
                  <dt>PATCH / REF</dt>
                  <dd>{trace.patch?.patch_id ?? snapshots[0]?.ref ?? "HEAD"}</dd>
                </div>
              </dl>
              <button
                type="button"
                onClick={() => jump({ kind: "source", id: trace.source }, "sources")}
              >
                查验这段原文 <ArrowRight size={14} />
              </button>
            </>
          ) : (
            <>
              <h3>{copy.title}</h3>
              <p>{copy.body}</p>
              <button
                type="button"
                onClick={() =>
                  setView(
                    selected === "source" || selected === "postgres"
                      ? "sources"
                      : selected === "meili" || selected === "qdrant"
                        ? "recall"
                        : selected === "compile"
                          ? "process"
                          : "history",
                  )
                }
              >
                打开这个站点 <ArrowRight size={14} />
              </button>
            </>
          )}
        </aside>
      </section>

      <section className="overview-manifest">
        <div className="manifest-identity">
          <span className="manifest-mark">
            <Braces size={17} />
          </span>
          <div>
            <small>SYNTHETIC OPC OPERATOR</small>
            <strong>{currentProfile?.display_name ?? currentUser ?? "未选择演示用户"}</strong>
            <p>确定性中文人设 · 仓库内置演示数据 · 不代表真实用户</p>
          </div>
        </div>

        <dl className="manifest-counts">
          <div>
            <dt>sources</dt>
            <dd>{counts.sources}</dd>
          </div>
          <div>
            <dt>documents</dt>
            <dd>{counts.documents}</dd>
          </div>
          <div>
            <dt>claims</dt>
            <dd>{counts.claims}</dd>
          </div>
          <div>
            <dt>patches</dt>
            <dd>{counts.patches}</dd>
          </div>
        </dl>
      </section>

      <section className="overview-demo-journey">
        <div className="journey-heading">
          <span>DETERMINISTIC WALKTHROUGH</span>
          <h3>一条证据，走完整条线路</h3>
          <p>这段路径完全来自当前演示数据，不用虚构 KPI，也不隐藏中间层。</p>
        </div>

        {trace ? (
          <ol className="journey-route">
            <li>
              <span className="journey-node journey-green">01</span>
              <small>SOURCE</small>
              <strong>{trace.source.slice(0, 12)}</strong>
              <p>{trace.span}</p>
              <button
                type="button"
                onClick={() => jump({ kind: "source", id: trace.source }, "sources")}
              >
                查原文
              </button>
            </li>
            <li>
              <span className="journey-node journey-cobalt">02</span>
              <small>CLAIM</small>
              <strong>{trace.claim}</strong>
              <p>稳定锚点</p>
            </li>
            <li>
              <span className="journey-node journey-amber">03</span>
              <small>CANONICAL</small>
              <strong>{trace.document.title}</strong>
              <p>{trace.document.path}</p>
              {trace.document.document_id && (
                <button
                  type="button"
                  onClick={() =>
                    jump({ kind: "document", id: trace.document.document_id! }, "library")
                  }
                >
                  读文档
                </button>
              )}
            </li>
            <li>
              <span className="journey-node journey-scarlet">04</span>
              <small>PATCH / GIT</small>
              <strong>{trace.patch?.patch_id ?? snapshots[0]?.ref.slice(0, 10) ?? "HEAD"}</strong>
              <p>{trace.patch?.lineage.model ?? "versioned output"}</p>
              <button type="button" onClick={() => setView("history")}>
                看版本
              </button>
            </li>
          </ol>
        ) : (
          <div className="journey-empty">
            <Layers3 size={24} />
            <div>
              <strong>线路已经就绪，等待第一份材料。</strong>
              <p>导入演示材料后，这里会出现 source → claim → canonical → Git 的真实路径。</p>
            </div>
            <Button variant="primary" onClick={() => setView("ingest")}>
              导入材料
            </Button>
          </div>
        )}
      </section>

      <section className="overview-next-routes">
        <button type="button" onClick={() => setView("ingest")}>
          <FlaskConical size={18} />
          <span>
            <small>01 / REPLAY</small>
            <strong>导入一份材料</strong>
          </span>
          <ArrowRight size={15} />
        </button>
        <button type="button" onClick={() => setView("context_stream")}>
          <BookOpenCheck size={18} />
          <span>
            <small>02 / EXPERIMENT</small>
            <strong>观察主动提示门禁</strong>
          </span>
          <ArrowRight size={15} />
        </button>
        <button type="button" onClick={() => setView("history")}>
          <GitCommitHorizontal size={18} />
          <span>
            <small>03 / VERIFY</small>
            <strong>核对版本与 lineage</strong>
          </span>
          <ArrowRight size={15} />
        </button>
        <div className="next-routes-note">
          <Check size={15} />
          <span>
            <strong>默认演示只使用合成数据</strong>
            <small>所有实验都可以在本地完整重放</small>
          </span>
        </div>
      </section>

      <div className="overview-legend">
        <span>
          <i className="legend-solid" /> 权威数据
        </span>
        <span>
          <i className="legend-dashed" /> 可重建投影
        </span>
        <Chip>OPC · AI-native 个人开发者</Chip>
      </div>
    </div>
  );
}

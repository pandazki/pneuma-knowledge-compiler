import type { CSSProperties } from "react";

export type StationId = "source" | "postgres" | "meili" | "qdrant" | "compile" | "git";

export interface KnowledgeStation {
  id: StationId;
  code: string;
  label: string;
  detail: string;
  x: number;
  y: number;
  color: string;
}

export const KNOWLEDGE_STATIONS: KnowledgeStation[] = [
  {
    id: "source",
    code: "S0",
    label: "原始材料",
    detail: "对话、文档与代码片段",
    x: 104,
    y: 250,
    color: "var(--route-green)",
  },
  {
    id: "postgres",
    code: "P0",
    label: "PostgreSQL",
    detail: "权威来源与摄取计划",
    x: 286,
    y: 250,
    color: "var(--route-green)",
  },
  {
    id: "meili",
    code: "L1",
    label: "Meilisearch",
    detail: "词法层，可重建",
    x: 468,
    y: 136,
    color: "var(--route-cobalt)",
  },
  {
    id: "qdrant",
    code: "L2",
    label: "Qdrant",
    detail: "语义层，可重建",
    x: 468,
    y: 330,
    color: "var(--route-amber)",
  },
  {
    id: "compile",
    code: "C1",
    label: "编译门",
    detail: "取证、合并与结构化",
    x: 704,
    y: 250,
    color: "var(--route-scarlet)",
  },
  {
    id: "git",
    code: "G1",
    label: "Canonical Git",
    detail: "可审阅、可回滚的版本",
    x: 920,
    y: 250,
    color: "var(--route-scarlet)",
  },
];

export function KnowledgeRouteMap({
  selected,
  onSelect,
  activeTrace = false,
}: {
  selected: StationId;
  onSelect: (station: StationId) => void;
  activeTrace?: boolean;
}) {
  return (
    <div className={`knowledge-route-map ${activeTrace ? "is-tracing" : ""}`}>
      <svg
        viewBox="0 0 1040 470"
        role="img"
        aria-labelledby="knowledge-route-title knowledge-route-description"
      >
        <title id="knowledge-route-title">Pneuma 知识编译线路</title>
        <desc id="knowledge-route-description">
          原始材料进入 PostgreSQL，经词法与语义双层索引，穿过编译门，落入 Canonical Git。
        </desc>

        <path
          className="route-line route-line-green route-trace-segment"
          d="M104 250 H286"
        />
        <path
          className="route-line route-line-cobalt route-trace-segment"
          d="M286 250 C350 250 378 136 468 136"
        />
        <path className="route-line route-line-amber" d="M286 250 C350 250 378 330 468 330" />
        <path
          className="route-line route-line-cobalt route-trace-segment"
          d="M468 136 C568 136 604 250 704 250"
        />
        <path className="route-line route-line-amber" d="M468 330 C568 330 604 250 704 250" />
        <path
          className="route-line route-line-scarlet route-line-arriving route-trace-segment"
          d="M704 250 H920"
        />
        <path className="route-line route-line-ghost" d="M920 250 H1000" />

        <text className="route-map-label" x="104" y="68">
          KNOWLEDGE TRANSIT / OPC
        </text>
        <text className="route-map-caption" x="104" y="94">
          实线为权威数据 · 虚线为可重建投影
        </text>

        {KNOWLEDGE_STATIONS.map((station) => {
          const active = selected === station.id;
          return (
            <g
              key={station.id}
              className={`route-station ${active ? "is-selected" : ""}`}
              role="button"
              tabIndex={0}
              aria-label={`${station.code} ${station.label}：${station.detail}`}
              aria-pressed={active}
              onClick={() => onSelect(station.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(station.id);
                }
              }}
              style={{ "--station-color": station.color } as CSSProperties}
            >
              <circle className="route-station-halo" cx={station.x} cy={station.y} r="26" />
              <circle className="route-station-node" cx={station.x} cy={station.y} r="13" />
              <circle className="route-station-core" cx={station.x} cy={station.y} r="5" />
              <text className="route-station-code" x={station.x} y={station.y + 52}>
                {station.code}
              </text>
              <text className="route-station-name" x={station.x} y={station.y + 76}>
                {station.label}
              </text>
            </g>
          );
        })}
      </svg>
      <ol className="mobile-knowledge-route" aria-label="六站知识编译线路">
        {KNOWLEDGE_STATIONS.map((station) => {
          const active = selected === station.id;
          return (
            <li key={station.id}>
              <button
                type="button"
                className={active ? "is-selected" : ""}
                aria-pressed={active}
                onClick={() => onSelect(station.id)}
                style={{ "--station-color": station.color } as CSSProperties}
              >
                <span className="mobile-route-node">{station.code}</span>
                <span>
                  <strong>{station.label}</strong>
                  <small>{station.detail}</small>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

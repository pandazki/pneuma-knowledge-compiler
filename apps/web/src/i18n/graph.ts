import { defineMessages } from "./define";

/**
 * The relationship graph: the canvas, the selected-node panel and the type legend. Node
 * titles, ids, paths and edge / node `type` strings are canonical data and render as they
 * come.
 *
 * `graph.summary` reads the trimming clause in as `{trimmed}` (empty when the neighbourhood
 * fits) rather than assembling two sentences, so each language keeps control of its own
 * punctuation — zh joins with a full-width parenthesis, en with a leading space.
 */
export const graph = defineMessages({
  zh: {
    "graph.description": "canonical 文档之间的关系图：墨色节点 + 发丝线边。",
    "graph.summary":
      "全库 {nodes} 节点 / {edges} 条边 · 当前聚焦 {visibleNodes} 节点 / {visibleEdges} 条边{trimmed}；单击节点切换中心。",
    "graph.summary.trimmed": "（从 {count} 个邻域节点中择取）",

    "graph.empty.title": "还没有图谱",
    "graph.empty.description":
      "这个知识库尚未编译——先去「导入 Ingest」添加原料并编译，图谱随正典一起产出。",
    "graph.empty.action": "去导入",

    "graph.noNodes.title": "图为空",
    "graph.noNodes.description": "graph 没有节点——文档间尚未建立链接。",

    "graph.degree.aria": "邻域度数",
    "graph.degree.one": "1 度",
    "graph.degree.two": "2 度",

    "graph.canvas.aria": "知识图谱画布",

    "graph.node.detailAria": "节点详情",
    "graph.node.openDocument": "打开文档",
    "graph.node.visibleEdges": "当前可见相邻边 · {count}",
    "graph.node.allEdges": " / 全部 {count}",
    "graph.node.noEdges": "无出入链接。",
    "graph.node.hint": "在图中单击一个节点，这里显示它的类型、路径与相邻边。",

    "graph.legend.title": "图例 · 类型",
  },
  en: {
    "graph.description":
      "How the canonical documents relate: ink nodes joined by hairline edges.",
    "graph.summary":
      "{nodes} node{nodes||s} / {edges} edge{edges||s} in the base · focused on {visibleNodes} node{visibleNodes||s} / {visibleEdges} edge{visibleEdges||s}{trimmed}; click a node to recentre.",
    "graph.summary.trimmed": " (picked from {count} neighbourhood nodes)",

    "graph.empty.title": "No graph yet",
    "graph.empty.description":
      "This knowledge base has not been compiled — add material under Ingest and compile it; the graph comes out with the canon.",
    "graph.empty.action": "Go to Ingest",

    "graph.noNodes.title": "The graph is empty",
    "graph.noNodes.description":
      "The graph has no nodes — no links between documents yet.",

    "graph.degree.aria": "Neighbourhood degree",
    "graph.degree.one": "1 degree",
    "graph.degree.two": "2 degrees",

    "graph.canvas.aria": "Knowledge graph canvas",

    "graph.node.detailAria": "Node detail",
    "graph.node.openDocument": "Open the document",
    "graph.node.visibleEdges": "Adjacent edges in view · {count}",
    "graph.node.allEdges": " / {count} in all",
    "graph.node.noEdges": "No links in or out.",
    "graph.node.hint":
      "Click a node in the graph and its type, path and adjacent edges appear here.",

    "graph.legend.title": "Legend · types",
  },
});

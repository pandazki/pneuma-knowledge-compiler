/**
 * 答案正文的行内引用反绑（recall fast / ask briefing 共用）。
 *
 * fast/briefing 答案带 `[cite: sNN]` / `[cite: sNN ¶a-b]` 查询局部 handle，
 * 配 `citation_handles` 映射回真实 source_id；deep 答案直接引用真实 id
 * （`[cite: <uuid> ¶a-b]`，无别名）。这里把每个 `[cite: …]` 片段替换为行内
 * Footnote 上标，点击经 store.focusSource 落到 sources 视图的原文 span。
 *
 * 解析对齐 core 消费侧 `iter_answer_citations`（recall/citation_alias.py）：
 * 一个方括号可合并多个 span —— `[cite: s01 ¶1-3, s02 ¶2-4]`；无自带 id 的 span
 * 继承上一个 id；尾随 `[¶a-b]` 方括号延续前一组的 source。无 ¶ 的 source 级
 * 引用仍是可跳脚注。解析不到真实 source 的组（脏 handle）原样保留为纯文本
 * —— 不可点，也不算错误。
 */
import { Fragment, type ReactNode } from "react";
import { useApp } from "@/lib/store";
import { Footnote } from "@/ui/Footnote";

/** 一个 `[cite: …]` 组及其尾随 `[¶a-b]` 延续括号。 */
const CITE_GROUP_RE = /\[cite:[^\]]*\](?:\s*\[\s*¶[^\]]*\])*/g;
/** 组内单个方括号 —— 领头的 `[cite: …]` 或延续的 `[¶ …]`。 */
const BRACKET_RE = /\[(?:cite:)?\s*([^\]]*?)\s*\]/g;
/** 括号体内的一个 block span；id 可省（继承前一个）。 */
const SPAN_RE = /(?:([^\s,;¶]+)\s*)?¶\s*(\d+)(?:\s*-\s*(\d+))?/g;
/** 不含任何 `¶` span 的括号里的裸 source id。 */
const BARE_SID_RE = /[^\s,;¶\]]+/g;

interface CiteRef {
  /** 答案里写下的 handle/id（`sNN` 别名或真实 source_id）。 */
  handle: string;
  from: number | null;
  to: number | null;
}

/** 把一个 `[cite: …]` 组解析成若干 (handle, span) 引用。 */
function parseGroup(group: string): CiteRef[] {
  const refs: CiteRef[] = [];
  let currentSid: string | null = null;
  let first = true;
  const bracketRe = new RegExp(BRACKET_RE.source, "g");
  let bracket: RegExpExecArray | null;
  while ((bracket = bracketRe.exec(group)) !== null) {
    const body = bracket[1] ?? "";
    const spanRe = new RegExp(SPAN_RE.source, "g");
    let span: RegExpExecArray | null;
    let sawSpan = false;
    while ((span = spanRe.exec(body)) !== null) {
      sawSpan = true;
      const sid: string | null = span[1] || currentSid;
      if (!sid) continue;
      currentSid = sid;
      const from = Number(span[2]);
      const to = span[3] ? Number(span[3]) : from;
      refs.push({ handle: sid, from, to });
    }
    if (!sawSpan && first) {
      // 领头括号无 ¶ span：source 级引用，如 `[cite: s01]`。
      const bareRe = new RegExp(BARE_SID_RE.source, "g");
      let bare: RegExpExecArray | null;
      while ((bare = bareRe.exec(body)) !== null) {
        currentSid = bare[0];
        refs.push({ handle: bare[0], from: null, to: null });
      }
    }
    first = false;
  }
  return refs;
}

/**
 * 把写下的 handle 解析为真实 source_id：
 * - 命中映射表 → 真实 id（fast/briefing 别名）；
 * - 未映射的 `sNN` → null（死别名纪元 —— 留作纯文本）；
 * - 其余 → 自身（deep 直接引用真实 id）。
 */
function resolveHandle(handle: string, handles: Record<string, string>): string | null {
  const real = handles[handle];
  if (real) return real;
  if (/^s\d+$/.test(handle)) return null;
  return handle;
}

/**
 * 渲染答案正文：`[cite: …]` 标记替换为行内 Footnote 上标（全文连续编号），
 * 非引用文本原样通过；整组都解析不到真实 source 时保留原文。
 */
export function CitedAnswer({
  text,
  handles,
}: {
  text: string;
  handles?: Record<string, string> | null;
}) {
  const focusSource = useApp((s) => s.focusSource);
  const map = handles ?? {};
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let footnoteIndex = 0;
  const groupRe = new RegExp(CITE_GROUP_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = groupRe.exec(text)) !== null) {
    const start = m.index;
    const raw = m[0];
    if (start > last) nodes.push(<Fragment key={key++}>{text.slice(last, start)}</Fragment>);
    const resolvable = parseGroup(raw)
      .map((r) => ({ ...r, real: resolveHandle(r.handle, map) }))
      .filter((r): r is CiteRef & { real: string } => r.real != null);
    if (resolvable.length === 0) {
      // 整组无可绑定 —— 保留可读原文，不可点。
      nodes.push(<Fragment key={key++}>{raw}</Fragment>);
    } else {
      nodes.push(
        <Fragment key={key++}>
          {resolvable.map((r, i) => (
            <Footnote
              key={i}
              index={++footnoteIndex}
              citation={{
                sourceId: r.real,
                blockStart: r.from,
                blockEnd: r.to,
              }}
              onJump={(c) =>
                focusSource(
                  c.sourceId,
                  c.blockStart != null
                    ? { start: c.blockStart, end: c.blockEnd ?? c.blockStart }
                    : null,
                )
              }
            />
          ))}
        </Fragment>,
      );
    }
    last = start + raw.length;
  }
  if (last < text.length) nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return <>{nodes}</>;
}

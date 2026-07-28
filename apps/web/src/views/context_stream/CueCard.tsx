import type { Cue, CueDetailFrame } from "@/lib/api";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Mono } from "@/ui/Mono";
import { UsageLine } from "../_shared/UsageLine";

export interface CueCardProps {
  cue: Cue;
  /** getCueKinds 词表里的中文名（缺省显示 kind key）。 */
  kindLabel?: string;
  /** 到达渠道注记，如「ws · seq 3」/「sse」。 */
  via?: string;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
  /** want_more 展开（仅 WS 链路）：未传则卡片无展开区。 */
  canExpand?: boolean;
  pending?: boolean;
  /** 本卡自己的展开失败（按 ref 归属，永不串卡）。 */
  failure?: string;
  detail?: CueDetailFrame;
  onWantMore?: () => void;
}

/**
 * 提词卡：标题 + serif 正文 + trigger 一行（「触发」）+ confidence 数字 mono +
 * 引用 CitationList。被门禁吃掉的内容不在这里出现——只在 GateLedger 计数里。
 */
export function CueCard({
  cue,
  kindLabel,
  via,
  titles,
  onJump,
  canExpand,
  pending,
  failure,
  detail,
  onWantMore,
}: CueCardProps) {
  return (
    <article className="border-b border-line py-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-14 font-medium text-ink">{cue.title}</span>
        <Badge>{kindLabel ?? cue.kind}</Badge>
        <Mono className="text-12 text-ink-3">confidence {cue.confidence}</Mono>
        {via && <Mono className="text-12 text-ink-3">{via}</Mono>}
      </div>
      <p className="prose mt-2 max-w-measure text-14">{cue.body}</p>
      <p className="mt-2 text-12 text-ink-3">触发：「{cue.trigger}」</p>
      {cue.citations.length > 0 && (
        <CitationList
          className="mt-2 max-w-measure"
          citations={cue.citations.map((c) => ({
            sourceId: c.source_id,
            blockStart: c.block_start,
            blockEnd: c.block_end,
            title: titles[c.source_id],
          }))}
          onJump={onJump}
        />
      )}

      {onWantMore && (
        <div className="mt-3">
          <Button
            size="sm"
            loading={pending}
            disabled={!canExpand}
            title={canExpand ? "走 WS 的 want_more，基于本卡引用取原文再展开" : "want_more 只在连接打开时可用"}
            onClick={onWantMore}
          >
            {failure ? "重试展开（want_more）" : "展开（want_more）"}
          </Button>
        </div>
      )}
      {failure && (
        <Callout tone="danger" className="mt-2 max-w-measure">
          展开失败：{failure}
        </Callout>
      )}
      {detail && (
        <div className="mt-3 max-w-measure border-l-2 border-line-2 pl-3">
          <p className="text-12 text-ink-3">cue_detail</p>
          <p className="prose mt-1 text-14 whitespace-pre-wrap">
            {detail.detail || "（空）"}
          </p>
          {detail.citations.length > 0 && (
            <CitationList
              className="mt-2"
              citations={detail.citations.map((c) => ({
                sourceId: c.source_id,
                blockStart: c.block_start,
                blockEnd: c.block_end,
                title: titles[c.source_id],
              }))}
              onJump={onJump}
            />
          )}
          <UsageLine usage={detail.token_usage} className="mt-2" />
        </div>
      )}
    </article>
  );
}

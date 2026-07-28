import { useEffect, useState } from "react";
import {
  Plus,
  Trash2,
  Send,
  CheckCircle2,
  Upload,
  Loader2,
  MessageSquare,
  FileText,
  Eye,
  UserRound,
  ChevronDown,
  Sparkles,
  ShieldCheck,
} from "lucide-react";
import { useApp } from "@/lib/store";
import { Button, Card, Chip, Eyebrow } from "@/components/ui";
import * as api from "@/lib/api";

interface TurnDraft {
  speaker: string;
  text: string;
  at: string; // datetime-local value, "" = unset
}

const EMPTY_TURN: TurnDraft = { speaker: "", text: "", at: "" };

const FIELD =
  "w-full rounded-sm border border-border bg-card px-2.5 py-1.5 text-sm text-foreground " +
  "outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring placeholder:text-muted-foreground";

const TREATMENTS = ["full", "distill", "card", "none"] as const;
const SEMANTICS = ["full", "summary", "none"] as const;

// The "auto / 让系统判断" option — key "" means: send no archetype, let the backend
// propose mechanically. Rendered as the first row of the archetype picker.
const AUTO_ARCHETYPE = {
  key: "",
  label: "让系统判断（auto）",
  summary: "按类型与体量机械判定处理策略",
  examples: "不确定时的默认选择",
};

/**
 * Read-only display of the active ingest target — the user selected in the top bar.
 * Ingest no longer lets you type a raw id; it always locks to `currentUser`. Shows
 * display_name (from currentProfile / profileNames cache) with the raw id as a mono
 * suffix, and an explicit "pick a user first" nudge when none is selected.
 */
function TargetUser() {
  const currentUser = useApp((s) => s.currentUser);
  const currentProfile = useApp((s) => s.currentProfile);
  const profileNames = useApp((s) => s.profileNames);

  if (!currentUser) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-[var(--color-danger)]">
        <UserRound size={13} className="flex-none" />
        未选择用户 — 请先在顶栏选择或新建用户
      </div>
    );
  }
  const name = currentProfile?.display_name ?? profileNames[currentUser] ?? currentUser;
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <UserRound size={13} className="flex-none text-muted-foreground" />
      <span className="text-muted-foreground">目标用户 ·</span>
      <span className="truncate text-foreground">{name}</span>
      {name !== currentUser && (
        <span className="truncate font-mono text-[length:var(--text-2xs)] text-muted-foreground">
          {currentUser}
        </span>
      )}
    </div>
  );
}

export function IngestView() {
  const { currentUser, setUser, loadUsers } = useApp();
  const [title, setTitle] = useState("");
  const [turns, setTurns] = useState<TurnDraft[]>([{ ...EMPTY_TURN }]);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<api.IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const filledTurns = turns.filter((t) => t.text.trim());
  const canSubmit = !!currentUser && !!title.trim() && filledTurns.length > 0 && !submitting;

  function updateTurn(i: number, patch: Partial<TurnDraft>) {
    setTurns((prev) => prev.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  }

  async function onSubmit() {
    if (!currentUser) return;
    setError(null);
    setResult(null);
    setSubmitting(true);
    try {
      const payloadTurns: api.ConversationTurnInput[] = filledTurns.map((t) => ({
        speaker: t.speaker.trim() || "user",
        text: t.text.trim(),
        at: t.at ? new Date(t.at).toISOString() : null,
      }));
      const res = await api.ingestConversation(currentUser, {
        title: title.trim(),
        turns: payloadTurns,
      });
      setResult(res);
      // The first source may make a brand-new user appear in the directory — refresh it.
      setUser(currentUser);
      await loadUsers();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-5 py-6">
        <Eyebrow>增量实验 · Ingest</Eyebrow>
        <h2 className="mt-2 text-[length:var(--text-lg)] font-light">添加一段对话</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          走 <span className="font-mono">POST /v1/users/&#123;uid&#125;/sources/conversation</span>
          。提交后展示系统判定的 IntakePlan 两旋钮。
        </p>

        {/* conversation form */}
        <Card className="mt-5 p-4">
          <TargetUser />

          <label className="mt-3 block">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">标题</span>
            <input
              className={FIELD}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="发布复盘 / roadmap sync …"
            />
          </label>

          <div className="mt-4 mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <MessageSquare size={13} /> 对话轮次 · {filledTurns.length}
          </div>
          <div className="space-y-3">
            {turns.map((t, i) => (
              <div key={i} className="border border-border rounded-sm p-3">
                <div className="flex gap-2">
                  <input
                    className={FIELD + " max-w-[10rem]"}
                    value={t.speaker}
                    onChange={(e) => updateTurn(i, { speaker: e.target.value })}
                    placeholder="speaker"
                  />
                  <input
                    type="datetime-local"
                    className={FIELD}
                    value={t.at}
                    onChange={(e) => updateTurn(i, { at: e.target.value })}
                  />
                  {turns.length > 1 && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="删除轮次"
                      onClick={() => setTurns((prev) => prev.filter((_, idx) => idx !== i))}
                    >
                      <Trash2 size={14} />
                    </Button>
                  )}
                </div>
                <textarea
                  className={FIELD + " mt-2 min-h-[3.5rem] resize-y"}
                  value={t.text}
                  onChange={(e) => updateTurn(i, { text: e.target.value })}
                  placeholder="这一轮说了什么…"
                />
              </div>
            ))}
          </div>

          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setTurns((prev) => [...prev, { ...EMPTY_TURN }])}
            >
              <Plus size={14} /> 加一轮
            </Button>
            <Button
              variant="primary"
              size="sm"
              className="ml-auto"
              disabled={!canSubmit}
              onClick={onSubmit}
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              提交入库
            </Button>
          </div>

          {error && (
            <div className="mt-3 border border-[var(--color-danger)] px-3 py-2 text-xs text-[var(--color-danger)]">
              入库失败：{error}
            </div>
          )}
          {result && (
            <div className="mt-3 flex items-start gap-2 border border-[var(--color-success)] px-3 py-2 text-xs">
              <CheckCircle2 size={14} className="mt-0.5 flex-none text-[var(--color-success)]" />
              <div>
                <div className="font-medium">
                  {result.deduplicated ? "内容去重命中（append-only）" : "已入库"}
                </div>
                <div className="mt-1 break-all font-mono text-muted-foreground">
                  source_id {result.source_id}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="text-muted-foreground">IntakePlan</span>
                  <Chip>treatment · {result.intake_plan.canonical_treatment}</Chip>
                  <Chip>semantic · {result.intake_plan.semantic_indexing}</Chip>
                </div>
                <div className="mt-1.5 leading-4 text-muted-foreground">
                  {result.intake_plan.rationale}
                </div>
              </div>
            </div>
          )}
        </Card>

        {/* document intake — two-step: preview (proposal) → confirm */}
        <DocumentPanel />
      </div>
    </div>
  );
}

function DocumentPanel() {
  const { currentUser, setUser, loadUsers, loadUserDataset } = useApp();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  // The user-facing axis: chosen processing intent. "" = auto (let the backend propose).
  const [archetypes, setArchetypes] = useState<api.IntakeArchetype[]>([]);
  const [archetype, setArchetype] = useState<string>("");
  // After an auto preview, the backend's suggested archetype key (for the 系统建议 hint).
  const [suggested, setSuggested] = useState<string | null>(null);
  const [preview, setPreview] = useState<api.DocumentPreview | null>(null);
  const [treatment, setTreatment] = useState<string>("full");
  const [semantic, setSemantic] = useState<string>("full");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<api.IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch the archetype registry on mount — core is the single source of truth.
  useEffect(() => {
    let alive = true;
    api
      .getIntakeArchetypes()
      .then((rows) => alive && setArchetypes(rows))
      .catch(() => alive && setArchetypes([]));
    return () => {
      alive = false;
    };
  }, []);

  const canPreview = !!currentUser && !!title.trim() && !!text.trim() && !previewing;
  const labelOf = (key: string) =>
    archetypes.find((a) => a.key === key)?.label ?? key;

  // Selecting an intent invalidates the current preview (its proposed plan is now stale).
  function selectArchetype(key: string) {
    setArchetype(key);
    setPreview(null);
    setResult(null);
    setSuggested(null);
  }

  async function onPreview() {
    if (!currentUser) return;
    const wasAuto = !archetype;
    setError(null);
    setResult(null);
    setPreviewing(true);
    try {
      const p = await api.previewDocument(currentUser, {
        title: title.trim(),
        text,
        intake_archetype: archetype || null,
      });
      setPreview(p);
      setTreatment(p.proposed_plan.canonical_treatment);
      setSemantic(p.proposed_plan.semantic_indexing);
      // On the auto path, highlight the backend's suggestion and default the selection to it.
      if (wasAuto) {
        setSuggested(p.proposed_archetype ?? null);
        if (p.proposed_archetype) setArchetype(p.proposed_archetype);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreviewing(false);
    }
  }

  async function onConfirm() {
    if (!currentUser) return;
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.ingestDocument(currentUser, {
        title: title.trim(),
        text,
        intake_archetype: archetype || null,
        // The raw knobs are the ultimate override — only sent when the user opened 高级.
        ...(advancedOpen
          ? {
              plan_override: {
                canonical_treatment: treatment,
                semantic_indexing: semantic,
              },
            }
          : {}),
      });
      setResult(res);
      setPreview(null);
      setUser(currentUser);
      await loadUsers();
      await loadUserDataset();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const pickerRows = [AUTO_ARCHETYPE, ...archetypes];

  return (
    <Card className="mt-4 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Upload size={15} /> 上传文档
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          处理意图 · 两步式（预览 → 确认）
        </span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        选一个处理意图，走 <span className="font-mono">POST …/sources/document/preview</span>{" "}
        预览节树与 IntakePlan 提案，确认后
        <span className="font-mono"> POST …/sources/document</span> 落库并入队，后台处理中。
      </p>

      <div className="mt-3">
        <TargetUser />
      </div>

      <label className="mt-3 block">
        <span className="mb-1 block text-xs font-medium text-muted-foreground">标题</span>
        <input
          className={FIELD}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="发布规范 / 小说节选 …"
        />
      </label>

      {/* archetype picker — the user-facing processing-intent axis */}
      <div className="mt-3">
        <span className="mb-1.5 block text-xs font-medium text-muted-foreground">处理意图</span>
        <div className="grid gap-1.5">
          {pickerRows.map((a) => {
            const selected = archetype === a.key;
            const isSuggested = suggested !== null && suggested === a.key && a.key !== "";
            return (
              <button
                key={a.key || "__auto__"}
                type="button"
                onClick={() => selectArchetype(a.key)}
                aria-pressed={selected}
                className={
                  "flex flex-col items-start rounded-sm border px-3 py-2 text-left transition-colors " +
                  (selected
                    ? "border-ring bg-accent/50 ring-1 ring-ring"
                    : "border-border hover:border-muted-foreground/40")
                }
              >
                <span className="flex w-full items-center gap-1.5 text-sm text-foreground">
                  {a.label}
                  {isSuggested && (
                    <span className="inline-flex items-center gap-0.5 text-[length:var(--text-2xs)] text-[var(--color-success)]">
                      <Sparkles size={10} /> 系统建议
                    </span>
                  )}
                </span>
                <span className="mt-0.5 text-xs text-muted-foreground">{a.summary}</span>
                {a.examples && (
                  <span className="mt-0.5 text-[length:var(--text-2xs)] text-muted-foreground/70">
                    例：{a.examples}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <p className="mt-1.5 flex items-center gap-1 text-[length:var(--text-2xs)] text-muted-foreground">
          <ShieldCheck size={11} className="flex-none" />
          无论选哪种，L0 原文直取 + L1 全文检索始终可用
        </p>
      </div>

      <label className="mt-3 block">
        <span className="mb-1 block text-xs font-medium text-muted-foreground">
          文档正文（markdown / 纯文本，按标题分节，无标题按段落）
        </span>
        <textarea
          className={FIELD + " min-h-[8rem] resize-y font-mono text-xs leading-5"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            "# Atlas 发布规范\n\n公开发布前完成依赖许可证扫描。\n\n## 数据边界\n\n导出包不得包含未脱敏实验材料。"
          }
        />
      </label>

      <div className="mt-3 flex items-center gap-2">
        <Button variant="outline" size="sm" disabled={!canPreview} onClick={onPreview}>
          {previewing ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
          预览
        </Button>
      </div>

      {preview && (
        <div className="mt-3 border border-border rounded-sm p-3">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <FileText size={13} /> 归一化预览 · {preview.normalized.block_count} 块 ·{" "}
            {preview.normalized.char_count} 字
          </div>
          {suggested && (
            <div className="mt-2 flex items-center gap-1 text-[length:var(--text-2xs)] text-[var(--color-success)]">
              <Sparkles size={11} /> 系统建议：{labelOf(suggested)}
            </div>
          )}
          {/* section tree */}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {preview.normalized.section_tree.map((s, i) => (
              <Chip key={i} title={`blocks ${s.start_block}–${s.end_block}`}>
                {s.path.join(" / ") || "(前言)"}{" "}
                <span className="font-mono text-muted-foreground">·{s.block_count}</span>
              </Chip>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="text-[length:var(--text-2xs)] text-muted-foreground">IntakePlan 提案</span>
            <Chip>treatment · {preview.proposed_plan.canonical_treatment}</Chip>
            <Chip>semantic · {preview.proposed_plan.semantic_indexing}</Chip>
          </div>
          <div className="mt-2 text-[length:var(--text-2xs)] leading-4 text-muted-foreground">
            {preview.proposed_plan.rationale}
          </div>

          {/* 高级：the raw two knobs — the ultimate override (plan_override) */}
          <div className="mt-3 border-t border-border pt-2">
            <button
              type="button"
              onClick={() => setAdvancedOpen((v) => !v)}
              className="flex items-center gap-1 text-[length:var(--text-2xs)] font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronDown
                size={12}
                className={"transition-transform " + (advancedOpen ? "" : "-rotate-90")}
              />
              高级 · 手动覆盖两旋钮
            </button>
            {advancedOpen && (
              <div className="mt-2 grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-[length:var(--text-2xs)] font-medium text-muted-foreground">
                    canonical_treatment
                  </span>
                  <select
                    className={FIELD}
                    value={treatment}
                    onChange={(e) => setTreatment(e.target.value)}
                  >
                    {TREATMENTS.map((t) => (
                      <option key={t} value={t}>
                        {t}
                        {t === preview.proposed_plan.canonical_treatment ? " · 提案" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-[length:var(--text-2xs)] font-medium text-muted-foreground">
                    semantic_indexing
                  </span>
                  <select
                    className={FIELD}
                    value={semantic}
                    onChange={(e) => setSemantic(e.target.value)}
                  >
                    {SEMANTICS.map((t) => (
                      <option key={t} value={t}>
                        {t}
                        {t === preview.proposed_plan.semantic_indexing ? " · 提案" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </div>

          <div className="mt-3 flex justify-end">
            <Button variant="primary" size="sm" disabled={submitting} onClick={onConfirm}>
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              确认提交
            </Button>
          </div>
        </div>
      )}

      {error && (
        <div className="mt-3 border border-[var(--color-danger)] px-3 py-2 text-xs text-[var(--color-danger)]">
          文档 intake 失败：{error}
        </div>
      )}
      {result && (
        <div className="mt-3 flex items-start gap-2 border border-[var(--color-success)] px-3 py-2 text-xs">
          <CheckCircle2 size={14} className="mt-0.5 flex-none text-[var(--color-success)]" />
          <div>
            <div className="font-medium">
              {result.deduplicated ? "内容去重命中（append-only）" : "已入库，已入队，后台处理中"}
            </div>
            <div className="mt-1 break-all font-mono text-muted-foreground">
              source_id {result.source_id}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Chip>treatment · {result.intake_plan.canonical_treatment}</Chip>
              <Chip>semantic · {result.intake_plan.semantic_indexing}</Chip>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

import { useEffect, useState } from "react";
import { Braces, UserRound } from "lucide-react";
import {
  getIntakeArchetypes,
  ingestDocument,
  importOfficialSource,
  previewDocument,
  type DocumentPreview,
  type IngestResult,
  type IntakeArchetype,
  type OfficialImportResult,
} from "@/lib/api";
import { useApp } from "@/lib/store";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { EmptyState } from "@/ui/EmptyState";
import { FilePicker } from "@/ui/FilePicker";
import { Mono } from "@/ui/Mono";
import { RadioGroup } from "@/ui/RadioGroup";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { Tabs } from "@/ui/Tabs";
import { TextArea } from "@/ui/TextArea";
import { TextField } from "@/ui/TextField";
import { PageHeader } from "@/components/PageHeader";
import {
  OFFICIAL_SOURCE_OPTIONS,
  detectOfficialSourceKind,
  officialSourceTemplate,
  parseOfficialSourcePayload,
  summarizeOfficialSourcePayload,
  type OfficialSourceKind,
  type OfficialSourceSummary,
} from "./officialSources";

/** Select / RadioGroup 不接受空串项，用哨兵值映射回 null（「自动」）。 */
const AUTO = "__auto__";

const TREATMENTS = ["full", "distill", "card", "none"];
const SEMANTICS = ["full", "summary", "none"];

export default function IngestView() {
  const currentUser = useApp((s) => s.currentUser);
  const readOnly = useApp((s) => s.currentSnapshot != null);
  const [tab, setTab] = useState("official");

  if (!currentUser) {
    return (
      <EmptyState
        icon={UserRound}
        title="未选择用户"
        description="先在顶栏选择或新建一个 user_id，导入的原料归属于该用户。"
      />
    );
  }

  return (
    <div className="flex max-w-measure flex-col gap-6">
      <PageHeader
        title="导入 Ingest"
        description="会议、文档库、即时消息与邮件共用一套可审计入口；canonical contract 预检通过后才进入编译流水线。"
      />
      {readOnly && (
        <Callout tone="info" title="历史快照 · 只读">
          正在查看历史快照，导入已禁用；切回 HEAD 后才能提交新原料。
        </Callout>
      )}
      <Tabs
        aria-label="导入方式"
        value={tab}
        onChange={setTab}
        tabs={[
          {
            value: "official",
            label: "结构化来源",
            panel: <OfficialSourceTab readOnly={readOnly} />,
          },
          {
            value: "document",
            label: "单篇文档",
            panel: <DocumentTab readOnly={readOnly} />,
          },
        ]}
      />
    </div>
  );
}

function OfficialImportResultCallout({ result }: { result: OfficialImportResult }) {
  const focusSource = useApp((s) => s.focusSource);
  const deduplicated = result.sources.filter((source) => source.deduplicated).length;
  return (
    <Callout tone="notice" title={`导入完成 · ${result.sources.length} 条 source`}>
      <div className="flex min-w-0 flex-col gap-2">
        <p>
          contract <Mono>{result.contract_schema}</Mono>
          {deduplicated > 0 && <> · 去重命中 <Mono>{deduplicated}</Mono></>}
        </p>
        <ol className="flex flex-col border-t border-line">
          {result.sources.map((source, index) => (
            <li
              key={source.source_id}
              className="flex min-w-0 items-center gap-3 border-b border-line py-2"
            >
              <Mono className="shrink-0 text-ink-3">{index + 1}</Mono>
              <Mono className="min-w-0 flex-1 truncate">{source.source_id}</Mono>
              {source.deduplicated && <span className="shrink-0 text-12 text-ink-3">已存在</span>}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => focusSource(source.source_id)}
              >
                查看
              </Button>
            </li>
          ))}
        </ol>
      </div>
    </Callout>
  );
}

/* --------------------------------------------------------- 四类官方 Source */

function OfficialSourceTab({ readOnly }: { readOnly: boolean }) {
  const currentUser = useApp((s) => s.currentUser);
  const loadUsers = useApp((s) => s.loadUsers);
  const [kind, setKind] = useState<OfficialSourceKind>("meeting");
  const [raw, setRaw] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [summary, setSummary] = useState<OfficialSourceSummary | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<OfficialImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = OFFICIAL_SOURCE_OPTIONS.find((option) => option.kind === kind)!;
  const canEdit = !readOnly && !submitting;

  function resetPreview() {
    setPayload(null);
    setSummary(null);
    setResult(null);
    setError(null);
  }

  function selectKind(value: string) {
    setKind(value as OfficialSourceKind);
    setRaw("");
    setFile(null);
    resetPreview();
  }

  function setSourceText(value: string) {
    setRaw(value);
    resetPreview();
  }

  async function onFile(next: File | null) {
    setFile(next);
    if (!next) return;
    try {
      const content = await next.text();
      const parsed = JSON.parse(content) as unknown;
      const detected = detectOfficialSourceKind(parsed);
      if (detected) setKind(detected);
      setSourceText(JSON.stringify(parsed, null, 2));
    } catch (caught) {
      setError(`读取 source contract 失败：${(caught as Error).message}`);
    }
  }

  function onPreflight() {
    setError(null);
    setResult(null);
    try {
      const parsed = parseOfficialSourcePayload(raw, kind);
      setPayload(parsed);
      setSummary(summarizeOfficialSourcePayload(parsed, kind));
    } catch (caught) {
      setPayload(null);
      setSummary(null);
      setError((caught as Error).message);
    }
  }

  async function onImport() {
    if (!currentUser || !payload) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const imported = await importOfficialSource(currentUser, payload);
      setResult(imported);
      setPayload(null);
      setSummary(null);
      void loadUsers();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-4">
        <SectionRule no={1} title="选择来源协议" />
        <RadioGroup
          aria-label="官方 source 类型"
          value={kind}
          onChange={selectKind}
          disabled={!canEdit}
          options={OFFICIAL_SOURCE_OPTIONS.map((option) => ({
            value: option.kind,
            label: option.label,
            description: `${option.description} 引用单元：${option.citationUnit}。`,
          }))}
        />
        <p className="text-13 text-ink-2">
          <Mono>{selected.schema}</Mono> · {selected.provider}
        </p>
      </section>

      <section className="flex flex-col gap-4">
        <SectionRule no={2} title="载入 canonical JSON" />
        <FilePicker
          label="选择 JSON 文件（可选）"
          hint="上传后按 schema 自动切换来源类型；文件只在本地读取，确认导入时才发送。"
          accept=".json,application/json"
          file={file}
          onFile={(next) => void onFile(next)}
          disabled={!canEdit}
        />
        <TextArea
          label="source contract"
          hint="可直接粘贴 provider adapter 产出的 canonical JSON。"
          value={raw}
          onChange={(event) => setSourceText(event.target.value)}
          className="font-mono text-13 leading-[1.65]"
          rows={14}
          placeholder={`{\n  "schema": "${selected.schema}",\n  …\n}`}
          disabled={!canEdit}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={!canEdit}
            onClick={() => {
              setFile(null);
              setSourceText(officialSourceTemplate(kind));
            }}
          >
            <Braces size={14} aria-hidden />
            载入合成示例
          </Button>
          <Button
            size="sm"
            variant="default"
            disabled={!canEdit || !raw.trim()}
            onClick={onPreflight}
          >
            预检结构
          </Button>
        </div>
      </section>

      {summary && payload && (
        <section className="flex flex-col gap-4">
          <SectionRule no={3} title="确认导入" />
          <div className="border-y border-line py-3">
            <p className="text-16 font-medium text-ink">{summary.title}</p>
            <p className="mt-1 text-13 text-ink-2">
              provider <Mono>{summary.provider}</Mono> ·{" "}
              <Mono>{summary.itemCount}</Mono> {summary.itemLabel}
            </p>
            <p className="mt-2 text-12 leading-[1.7] text-ink-3">
              服务端会再次执行完整 contract 校验；bundle 将按自然引用单元展开，并分别进入
              L0–L3 流水线。
            </p>
          </div>
          <div>
            <Button
              variant="primary"
              loading={submitting}
              disabled={readOnly}
              onClick={() => void onImport()}
            >
              导入 {selected.label}
            </Button>
          </div>
        </section>
      )}

      {error && (
        <Callout tone="danger" title="结构化来源导入失败">
          <Mono className="break-all">{error}</Mono>
        </Callout>
      )}
      {result && <OfficialImportResultCallout result={result} />}
    </div>
  );
}

/** 入库结果态：mono source_id + 去重标记 + intake_plan + 跳 sources 落点。 */
function IngestResultCallout({ result }: { result: IngestResult }) {
  const focusSource = useApp((s) => s.focusSource);
  return (
    <Callout
      tone="notice"
      title={result.deduplicated ? "内容去重命中（append-only）" : "已入库"}
    >
      <div className="flex flex-col gap-2">
        <p>
          source_id <Mono className="break-all">{result.source_id}</Mono>
        </p>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>
            canonical_treatment <Mono>{result.intake_plan.canonical_treatment}</Mono>
          </span>
          <span>
            semantic_indexing <Mono>{result.intake_plan.semantic_indexing}</Mono>
          </span>
        </p>
        <p className="leading-[1.75]">{result.intake_plan.rationale}</p>
        <p>
          <Button size="sm" variant="ghost" onClick={() => focusSource(result.source_id)}>
            查看原料
          </Button>
        </p>
      </div>
    </Callout>
  );
}

/* ---------------------------------------------------------------- 文档 Tab */

function DocumentTab({ readOnly }: { readOnly: boolean }) {
  const currentUser = useApp((s) => s.currentUser);
  const loadUsers = useApp((s) => s.loadUsers);

  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [archetypes, setArchetypes] = useState<IntakeArchetype[]>([]);
  const [archetype, setArchetype] = useState<string>(AUTO);
  const [sourceClass, setSourceClass] = useState<string>(AUTO);

  const [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [treatment, setTreatment] = useState("full");
  const [semantic, setSemantic] = useState("full");
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // intake archetype 注册表（core 为单一权威，UI 拉取而非内联）。
  useEffect(() => {
    let live = true;
    getIntakeArchetypes()
      .then((rows) => live && setArchetypes(rows))
      .catch(() => live && setArchetypes([]));
    return () => {
      live = false;
    };
  }, []);

  const canEdit = !readOnly && !submitting;
  const canPreview = !!currentUser && !!title.trim() && !!text.trim() && canEdit && !previewing;

  const selectedArchetype = archetypes.find((a) => a.key === archetype) ?? null;

  // 换意图会使现有预览的提案过期。
  function selectArchetype(key: string) {
    setArchetype(key);
    setPreview(null);
    setResult(null);
  }

  async function onFile(f: File | null) {
    setFile(f);
    if (!f) return;
    try {
      const content = await f.text();
      setText(content);
      if (!title.trim()) setTitle(f.name.replace(/\.(md|markdown|txt)$/i, ""));
    } catch (e) {
      setError(`读取文件失败：${(e as Error).message}`);
    }
  }

  const body = () => ({
    title: title.trim(),
    text,
    intake_archetype: archetype === AUTO ? null : archetype,
    source_class:
      sourceClass === AUTO ? null : (sourceClass as "workstream" | "reference"),
  });

  async function onPreview() {
    if (!currentUser) return;
    setError(null);
    setResult(null);
    setPreviewing(true);
    try {
      const p = await previewDocument(currentUser, body());
      setPreview(p);
      setTreatment(p.proposed_plan.canonical_treatment);
      setSemantic(p.proposed_plan.semantic_indexing);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreviewing(false);
    }
  }

  async function onConfirm() {
    if (!currentUser || !preview) return;
    setError(null);
    setSubmitting(true);
    try {
      const overridden =
        treatment !== preview.proposed_plan.canonical_treatment ||
        semantic !== preview.proposed_plan.semantic_indexing;
      const res = await ingestDocument(currentUser, {
        ...body(),
        // 仅在覆盖双旋钮时传 plan_override。
        ...(overridden
          ? { plan_override: { canonical_treatment: treatment, semantic_indexing: semantic } }
          : {}),
      });
      setResult(res);
      setPreview(null);
      // 首条 source 可能让新用户出现在目录里。
      void loadUsers();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const archetypeLabel = (key: string | null | undefined) =>
    archetypes.find((a) => a.key === key)?.label ?? key ?? "";

  return (
    <div className="flex flex-col gap-6">
      {/* 第一步：编辑 */}
      <section className="flex flex-col gap-4">
        <SectionRule no={1} title="编辑" />
        <TextField
          label="标题"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="发布规范 / 会议记录 …"
          disabled={!canEdit}
        />
        <FilePicker
          label="从文件读入（可选）"
          hint="支持 .md / .txt，读入后可在下方继续编辑"
          accept=".md,.markdown,.txt,text/markdown,text/plain"
          file={file}
          onFile={(f) => void onFile(f)}
          disabled={!canEdit}
        />
        <TextArea
          label="正文"
          hint="markdown / 纯文本；按标题分节，无标题按段落"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setPreview(null);
          }}
          autoRows
          maxRows={18}
          placeholder={"# 标题\n\n正文……"}
          disabled={!canEdit}
        />
        <Select
          label="处理意图 intake_archetype"
          value={archetype}
          onChange={selectArchetype}
          disabled={!canEdit}
          options={[
            { value: AUTO, label: "自动（让系统判断）" },
            ...archetypes.map((a) => ({ value: a.key, label: a.label })),
          ]}
        />
        {archetype === AUTO ? (
          <p className="text-12 text-ink-3">按类型与体量机械判定处理策略，预览时给出系统建议。</p>
        ) : (
          selectedArchetype && (
            <div className="flex flex-col gap-1 border-l-2 border-line-2 pl-3">
              <p className="text-13 text-ink-2">{selectedArchetype.summary}</p>
              {selectedArchetype.examples && (
                <p className="text-12 text-ink-3">例：{selectedArchetype.examples}</p>
              )}
            </div>
          )
        )}
        <RadioGroup
          label="source_class"
          value={sourceClass}
          onChange={(v) => {
            setSourceClass(v);
            setPreview(null);
          }}
          disabled={!canEdit}
          options={[
            { value: AUTO, label: "不指定", description: "由系统按内容判断" },
            { value: "workstream", label: "workstream", description: "进行中的工作流材料" },
            { value: "reference", label: "reference", description: "长期参考资料" },
          ]}
        />
        <div>
          <Button variant="primary" loading={previewing} disabled={!canPreview} onClick={() => void onPreview()}>
            机械预览
          </Button>
        </div>
      </section>

      {/* 第二步：预览 → 确认 */}
      {preview && (
        <section className="flex flex-col gap-4">
          <SectionRule no={2} title="机械预览" />
          <p className="text-13 text-ink-2">
            归一化结果：<Mono>{preview.normalized.block_count}</Mono> blocks ·{" "}
            <Mono>{preview.normalized.char_count}</Mono> chars
            {preview.proposed_archetype && (
              <>
                {" "}· 系统建议意图 <Mono>{archetypeLabel(preview.proposed_archetype)}</Mono>
              </>
            )}
          </p>
          {preview.normalized.section_tree.length > 0 && (
            <ul className="flex flex-col border-y border-line">
              {preview.normalized.section_tree.map((sec, i) => {
                const depth = Math.max(0, sec.path.length - 1);
                return (
                  <li
                    key={i}
                    className="flex items-baseline gap-3 border-b border-line py-1.5 last:border-b-0"
                    style={{ paddingLeft: `${depth * 16}px` }}
                  >
                    <span className="min-w-0 flex-1 truncate text-14 text-ink">
                      {sec.path[sec.path.length - 1] ?? "(前言)"}
                    </span>
                    <Mono className="shrink-0 text-12 text-ink-3">
                      b{sec.start_block}–b{sec.end_block} · {sec.block_count}
                    </Mono>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="flex flex-col gap-2">
            <p className="text-13 text-ink-2">
              提案：canonical_treatment <Mono>{preview.proposed_plan.canonical_treatment}</Mono> ·
              semantic_indexing <Mono>{preview.proposed_plan.semantic_indexing}</Mono>
            </p>
            <p className="text-13 leading-[1.75] text-ink-3">{preview.proposed_plan.rationale}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="canonical_treatment（覆盖）"
              value={treatment}
              onChange={setTreatment}
              disabled={readOnly}
              options={TREATMENTS.map((t) => ({
                value: t,
                label: t === preview.proposed_plan.canonical_treatment ? `${t} · 提案` : t,
              }))}
            />
            <Select
              label="semantic_indexing（覆盖）"
              value={semantic}
              onChange={setSemantic}
              disabled={readOnly}
              options={SEMANTICS.map((t) => ({
                value: t,
                label: t === preview.proposed_plan.semantic_indexing ? `${t} · 提案` : t,
              }))}
            />
          </div>
          <div>
            <Button
              variant="primary"
              loading={submitting}
              disabled={readOnly}
              onClick={() => void onConfirm()}
            >
              确认导入
            </Button>
          </div>
        </section>
      )}

      {error && (
        <Callout tone="danger" title="文档导入失败">
          <Mono className="break-all">{error}</Mono>
        </Callout>
      )}
      {result && <IngestResultCallout result={result} />}
    </div>
  );
}

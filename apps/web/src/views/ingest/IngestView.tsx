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
import { useT, useTOr } from "@/lib/useT";
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

/** Select / RadioGroup take no empty-string item; this sentinel maps back to null ("auto"). */
const AUTO = "__auto__";

const TREATMENTS = ["full", "distill", "card", "none"];
const SEMANTICS = ["full", "summary", "none"];

export default function IngestView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const readOnly = useApp((s) => s.currentSnapshot != null);
  const [tab, setTab] = useState("official");

  if (!currentUser) {
    return (
      <EmptyState
        icon={UserRound}
        title={t("ingest.noUser.title")}
        description={t("ingest.noUser.description")}
      />
    );
  }

  return (
    <div className="flex max-w-measure flex-col gap-6">
      <PageHeader title={t("ingest.pageTitle")} description={t("ingest.pageDescription")} />
      {readOnly && (
        <Callout tone="info" title={t("ingest.readOnly.title")}>
          {t("ingest.readOnly.body")}
        </Callout>
      )}
      <Tabs
        aria-label={t("ingest.tabs.aria")}
        value={tab}
        onChange={setTab}
        tabs={[
          {
            value: "official",
            label: t("ingest.tabs.official"),
            panel: <OfficialSourceTab readOnly={readOnly} />,
          },
          {
            value: "document",
            label: t("ingest.tabs.document"),
            panel: <DocumentTab readOnly={readOnly} />,
          },
        ]}
      />
    </div>
  );
}

function OfficialImportResultCallout({ result }: { result: OfficialImportResult }) {
  const t = useT();
  const focusSource = useApp((s) => s.focusSource);
  const deduplicated = result.sources.filter((source) => source.deduplicated).length;
  return (
    <Callout
      tone="notice"
      title={t("ingest.official.result.title", { count: result.sources.length })}
    >
      <div className="flex min-w-0 flex-col gap-2">
        <p>
          contract <Mono>{result.contract_schema}</Mono>
          {deduplicated > 0 && (
            <>
              {" "}
              · {t("ingest.official.result.dedupHit")} <Mono>{deduplicated}</Mono>
            </>
          )}
        </p>
        <ol className="flex flex-col border-t border-line">
          {result.sources.map((source, index) => (
            <li
              key={source.source_id}
              className="flex min-w-0 items-center gap-3 border-b border-line py-2"
            >
              <Mono className="shrink-0 text-ink-3">{index + 1}</Mono>
              <Mono className="min-w-0 flex-1 truncate">{source.source_id}</Mono>
              {source.deduplicated && (
                <span className="shrink-0 text-12 text-ink-3">
                  {t("ingest.official.result.existing")}
                </span>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => focusSource(source.source_id)}
              >
                {t("ingest.official.result.view")}
              </Button>
            </li>
          ))}
        </ol>
      </div>
    </Callout>
  );
}

/* ------------------------------------------ The four official source contracts */

function OfficialSourceTab({ readOnly }: { readOnly: boolean }) {
  const t = useT();
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
      setError(
        t("ingest.official.fileFailed", { detail: (caught as Error).message }),
      );
    }
  }

  function onPreflight() {
    setError(null);
    setResult(null);
    try {
      const parsed = parseOfficialSourcePayload(raw, kind, { t });
      setPayload(parsed);
      setSummary(summarizeOfficialSourcePayload(parsed, kind, { t }));
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
        <SectionRule no={1} title={t("ingest.official.step1")} />
        <RadioGroup
          aria-label={t("ingest.official.kindAria")}
          value={kind}
          onChange={selectKind}
          disabled={!canEdit}
          options={OFFICIAL_SOURCE_OPTIONS.map((option) => ({
            value: option.kind,
            label: t(option.labelKey),
            description: t("ingest.official.optionDescription", {
              description: t(option.descriptionKey),
              citationUnit: t(option.citationUnitKey),
            }),
          }))}
        />
        <p className="text-13 text-ink-2">
          <Mono>{selected.schema}</Mono> · {selected.provider}
        </p>
      </section>

      <section className="flex flex-col gap-4">
        <SectionRule no={2} title={t("ingest.official.step2")} />
        <FilePicker
          label={t("ingest.official.file.label")}
          hint={t("ingest.official.file.hint")}
          accept=".json,application/json"
          file={file}
          onFile={(next) => void onFile(next)}
          disabled={!canEdit}
        />
        <TextArea
          label="source contract"
          hint={t("ingest.official.contract.hint")}
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
              setSourceText(officialSourceTemplate(kind, { t }));
            }}
          >
            <Braces size={14} aria-hidden />
            {t("ingest.official.loadSample")}
          </Button>
          <Button
            size="sm"
            variant="default"
            disabled={!canEdit || !raw.trim()}
            onClick={onPreflight}
          >
            {t("ingest.official.preflight")}
          </Button>
        </div>
      </section>

      {summary && payload && (
        <section className="flex flex-col gap-4">
          <SectionRule no={3} title={t("ingest.official.step3")} />
          <div className="border-y border-line py-3">
            <p className="text-16 font-medium text-ink">{summary.title}</p>
            <p className="mt-1 text-13 text-ink-2">
              provider <Mono>{summary.provider}</Mono> ·{" "}
              <Mono>{summary.itemCount}</Mono> {summary.itemLabel}
            </p>
            <p className="mt-2 text-12 leading-[1.7] text-ink-3">
              {t("ingest.official.confirmNote")}
            </p>
          </div>
          <div>
            <Button
              variant="primary"
              loading={submitting}
              disabled={readOnly}
              onClick={() => void onImport()}
            >
              {t("ingest.official.submit", { kind: t(selected.labelKey) })}
            </Button>
          </div>
        </section>
      )}

      {error && (
        <Callout tone="danger" title={t("ingest.official.failed")}>
          <Mono className="break-all">{error}</Mono>
        </Callout>
      )}
      {result && <OfficialImportResultCallout result={result} />}
    </div>
  );
}

/** The stored result: mono source_id + dedup mark + intake_plan + a jump into Sources. */
function IngestResultCallout({ result }: { result: IngestResult }) {
  const t = useT();
  const focusSource = useApp((s) => s.focusSource);
  return (
    <Callout
      tone="notice"
      title={
        result.deduplicated
          ? t("ingest.document.result.deduplicated")
          : t("ingest.document.result.stored")
      }
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
            {t("ingest.document.result.view")}
          </Button>
        </p>
      </div>
    </Callout>
  );
}

/* ----------------------------------------------------------- The document tab */

function DocumentTab({ readOnly }: { readOnly: boolean }) {
  const t = useT();
  const tOr = useTOr();
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

  // The intake archetype registry (core is the single authority; the UI fetches it rather
  // than inlining a copy).
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

  // Changing the intent makes an existing preview's proposal stale.
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
      setError(t("ingest.document.fileFailed", { detail: (e as Error).message }));
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
        // `plan_override` only travels when one of the two knobs was moved.
        ...(overridden
          ? { plan_override: { canonical_treatment: treatment, semantic_indexing: semantic } }
          : {}),
      });
      setResult(res);
      setPreview(null);
      // A first source can make a new user appear in the directory.
      void loadUsers();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  // The served label is the fallback: an archetype this client has no wording for degrades
  // to the service's English, never to a blank.
  const archetypeLabel = (key: string | null | undefined) => {
    const served = archetypes.find((a) => a.key === key)?.label ?? key ?? "";
    return key ? tOr(`enum.intakeArchetype.${key}.label`, served) : served;
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Step one: edit */}
      <section className="flex flex-col gap-4">
        <SectionRule no={1} title={t("ingest.document.step1")} />
        <TextField
          label={t("ingest.document.title.label")}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("ingest.document.title.placeholder")}
          disabled={!canEdit}
        />
        <FilePicker
          label={t("ingest.document.file.label")}
          hint={t("ingest.document.file.hint")}
          accept=".md,.markdown,.txt,text/markdown,text/plain"
          file={file}
          onFile={(f) => void onFile(f)}
          disabled={!canEdit}
        />
        <TextArea
          label={t("ingest.document.body.label")}
          hint={t("ingest.document.body.hint")}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setPreview(null);
          }}
          autoRows
          maxRows={18}
          placeholder={t("ingest.document.body.placeholder")}
          disabled={!canEdit}
        />
        <Select
          label={t("ingest.document.archetype.label")}
          value={archetype}
          onChange={selectArchetype}
          disabled={!canEdit}
          options={[
            { value: AUTO, label: t("ingest.document.archetype.auto") },
            ...archetypes.map((a) => ({
              value: a.key,
              label: tOr(`enum.intakeArchetype.${a.key}.label`, a.label),
            })),
          ]}
        />
        {archetype === AUTO ? (
          <p className="text-12 text-ink-3">{t("ingest.document.archetype.autoHint")}</p>
        ) : (
          selectedArchetype && (
            <div className="flex flex-col gap-1 border-l-2 border-line-2 pl-3">
              <p className="text-13 text-ink-2">
                {tOr(
                  `enum.intakeArchetype.${selectedArchetype.key}.summary`,
                  selectedArchetype.summary,
                )}
              </p>
              {selectedArchetype.examples && (
                <p className="text-12 text-ink-3">
                  {t("ingest.document.archetype.examples", {
                    examples: tOr(
                      `enum.intakeArchetype.${selectedArchetype.key}.examples`,
                      selectedArchetype.examples,
                    ),
                  })}
                </p>
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
            {
              value: AUTO,
              label: t("ingest.document.sourceClass.auto"),
              description: t("ingest.document.sourceClass.autoHint"),
            },
            {
              value: "workstream",
              label: "workstream",
              description: t("ingest.document.sourceClass.workstream"),
            },
            {
              value: "reference",
              label: "reference",
              description: t("ingest.document.sourceClass.reference"),
            },
          ]}
        />
        <div>
          <Button variant="primary" loading={previewing} disabled={!canPreview} onClick={() => void onPreview()}>
            {t("ingest.document.preview")}
          </Button>
        </div>
      </section>

      {/* Step two: preview → confirm */}
      {preview && (
        <section className="flex flex-col gap-4">
          <SectionRule no={2} title={t("ingest.document.preview")} />
          <p className="text-13 text-ink-2">
            {t("ingest.document.normalizedPrefix")}
            <Mono>{preview.normalized.block_count}</Mono> blocks ·{" "}
            <Mono>{preview.normalized.char_count}</Mono> chars
            {preview.proposed_archetype && (
              <>
                {" "}· {t("ingest.document.proposedArchetype")}{" "}
                <Mono>{archetypeLabel(preview.proposed_archetype)}</Mono>
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
                      {sec.path[sec.path.length - 1] ?? t("ingest.document.preamble")}
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
              {t("ingest.document.proposalPrefix")}canonical_treatment{" "}
              <Mono>{preview.proposed_plan.canonical_treatment}</Mono> · semantic_indexing{" "}
              <Mono>{preview.proposed_plan.semantic_indexing}</Mono>
            </p>
            <p className="text-13 leading-[1.75] text-ink-3">{preview.proposed_plan.rationale}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label={t("ingest.document.treatmentOverride")}
              value={treatment}
              onChange={setTreatment}
              disabled={readOnly}
              options={TREATMENTS.map((option) => ({
                value: option,
                label:
                  option === preview.proposed_plan.canonical_treatment
                    ? t("ingest.document.proposedOption", { value: option })
                    : option,
              }))}
            />
            <Select
              label={t("ingest.document.semanticOverride")}
              value={semantic}
              onChange={setSemantic}
              disabled={readOnly}
              options={SEMANTICS.map((option) => ({
                value: option,
                label:
                  option === preview.proposed_plan.semantic_indexing
                    ? t("ingest.document.proposedOption", { value: option })
                    : option,
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
              {t("ingest.document.confirm")}
            </Button>
          </div>
        </section>
      )}

      {error && (
        <Callout tone="danger" title={t("ingest.document.failed")}>
          <Mono className="break-all">{error}</Mono>
        </Callout>
      )}
      {result && <IngestResultCallout result={result} />}
    </div>
  );
}

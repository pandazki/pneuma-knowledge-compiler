import { useState } from "react";
import { GitBranch } from "lucide-react";
import {
  setHomeCollectionCloud,
  updateHomeCollectionProcessor,
  updateHomeLocalCollection,
} from "@/lib/api";
import {
  collectionScope,
  scopeDraft,
  type CollectionProcessor,
  type CollectionSource,
  type HomeCollection,
} from "@/lib/collection";
import { useT } from "@/lib/useT";
import { fmtDateTime } from "@/lib/format";
import { Button } from "@/ui/Button";
import { Checkbox } from "@/ui/Checkbox";
import { Mono } from "@/ui/Mono";
import { Tabs } from "@/ui/Tabs";
import { TextField } from "@/ui/TextField";
import { CollectionScopeFields, CollectionScopeSummary } from "./CollectionScopeFields";

export type CollectionMutation = (
  key: string,
  operation: () => Promise<unknown>,
  message?: string,
) => Promise<boolean>;

interface Controls {
  disabled: boolean;
  busy: string | null;
  mutate: CollectionMutation;
}

export function CloudConnectionForm({ cloud, disabled, busy, mutate }: Controls & {
  cloud: HomeCollection["cloud"];
}) {
  const t = useT();
  const [url, setUrl] = useState(cloud.url);
  const [token, setToken] = useState("");
  return (
    <form className="flex max-w-2xl flex-col gap-4" onSubmit={(event) => {
      event.preventDefault();
      void mutate("cloud", async () => {
        await setHomeCollectionCloud({ url: url.trim(), host_token: token.trim() });
        setToken("");
      }, t("collection.saved"));
    }}>
      <div>
        <h3 className="font-serif text-20 text-ink">{t(cloud.configured ? "collection.cloudChange" : "collection.cloudTitle")}</h3>
        <p className="mt-2 text-13 text-ink-2">{t("collection.cloudDescription")}</p>
      </div>
      <TextField
        type="url"
        label={t("collection.cloudURL")}
        hint={t("collection.cloudURLHint")}
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        required
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
      />
      <TextField
        type="password"
        label={t("collection.cloudToken")}
        hint={t("collection.cloudTokenHint")}
        value={token}
        onChange={(event) => setToken(event.target.value)}
        required
        disabled={disabled}
        autoComplete="new-password"
        maxLength={4096}
        spellCheck={false}
      />
      <Button type="submit" variant="primary" disabled={disabled || !url.trim() || !token.trim()} loading={busy === "cloud"} className="self-start">
        {t("collection.cloudSave")}
      </Button>
    </form>
  );
}

function LocalCollectionForm({ source, disabled, busy, mutate }: Controls & {
  source: CollectionSource;
}) {
  const t = useT();
  const [draft, setDraft] = useState(() => scopeDraft(source.scope ?? { projects: [], harnesses: [], since: null }));
  const [enabled, setEnabled] = useState(source.enabled);
  const [replaceConfirmed, setReplaceConfirmed] = useState(false);
  const scope = collectionScope(draft);
  const canSave = scope != null && (!source.complex_scope || replaceConfirmed);
  return (
    <form className="flex max-w-2xl flex-col gap-4" onSubmit={(event) => {
      event.preventDefault();
      if (scope && canSave) void mutate("local", () => updateHomeLocalCollection({ enabled, scope }), t("collection.saved"));
    }}>
      <div>
        <h3 className="font-serif text-20">{t("collection.localConfig")}</h3>
        <p className="mt-2 text-13 text-ink-2">{t("collection.localConfigHint")}</p>
      </div>
      {source.complex_scope && <div className="flex flex-col gap-3 border-y border-line py-4">
        <h4 className="text-14 font-medium">{t("collection.existingWatches")}</h4>
        <dl className="flex flex-col gap-3">
          {(source.watches ?? []).map((watch) => <div key={watch.path} className="flex flex-col gap-1">
            <dt>{watch.path === "all" ? <span className="text-13">{t("collection.scopeAll")}</span> : <Mono className="break-all text-13">{watch.path}</Mono>}</dt>
            <dd className="text-12 text-ink-2">
              {watch.harnesses.map((harness) => t(harness === "codex" ? "collection.codex" : "collection.claude")).join(" / ")}
              <span aria-hidden> · </span>{t(watch.recursive ? "collection.recursive" : "collection.exactProject")}
              <span aria-hidden> · </span>{watch.since ? fmtDateTime(watch.since) : t("collection.scopeHistory")}
            </dd>
          </div>)}
        </dl>
        <p className="text-13 text-ink-2">{t("collection.replaceScopeHint")}</p>
      </div>}
      <Checkbox label={t("collection.enabled")} checked={enabled} onCheckedChange={(value) => setEnabled(value === true)} disabled={disabled} />
      <CollectionScopeFields value={draft} onChange={setDraft} disabled={disabled} local />
      {!scope && <CollectionScopeSummary scope={null} />}
      {source.complex_scope && <Checkbox checked={replaceConfirmed} onCheckedChange={(value) => setReplaceConfirmed(value === true)} disabled={disabled}
        label={t("collection.replaceScopeConfirm")} />}
      <Button type="submit" disabled={disabled || !canSave} loading={busy === "local"} className="self-start">
        {t(source.complex_scope ? "collection.replaceScope" : "collection.localSave")}
      </Button>
    </form>
  );
}

function ProcessorForm({ processor, sourceCount, disabled, busy, mutate }: Controls & {
  processor: CollectionProcessor;
  sourceCount: number;
}) {
  const t = useT();
  const [label, setLabel] = useState(processor.label);
  const [values, setValues] = useState({
    min_owner_turns: String(processor.min_owner_turns),
    min_owner_chars: String(processor.min_owner_chars),
    ack_max_words: String(processor.ack_max_words),
    max_part_chars: String(processor.max_part_chars),
  });
  const fields = [
    ["min_owner_turns", "collection.minTurns"],
    ["min_owner_chars", "collection.minChars"],
    ["ack_max_words", "collection.ackWords"],
    ["max_part_chars", "collection.maxPart"],
  ] as const;
  const minimums = { min_owner_turns: 3, min_owner_chars: 0, ack_max_words: 1, max_part_chars: 1000 };
  const valid = label.trim() !== "" && label.trim().length <= 100 && fields.every(([key]) =>
    values[key].trim() !== "" && Number.isInteger(Number(values[key])) && Number(values[key]) >= minimums[key],
  );
  return (
    <form className="flex max-w-2xl flex-col gap-4 border-b border-line py-5 last:border-b-0" onSubmit={(event) => {
      event.preventDefault();
      if (!valid) return;
      void mutate(`processor:${processor.id}`, () => updateHomeCollectionProcessor(processor.id, {
        label: label.trim(),
        min_owner_turns: Number(values.min_owner_turns),
        min_owner_chars: Number(values.min_owner_chars),
        ack_max_words: Number(values.ack_max_words),
        max_part_chars: Number(values.max_part_chars),
      }), t("collection.saved"));
    }}>
      <p className="text-13 text-ink-2">{t("collection.processorUsed", { count: sourceCount })}</p>
      <TextField label={t("collection.processorName")} value={label} onChange={(event) => setLabel(event.target.value)} maxLength={100} required disabled={disabled} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {fields.map(([key, labelKey]) => (
          <TextField
            key={key}
            type="number"
            min={minimums[key]}
            step={1}
            label={t(labelKey)}
            value={values[key]}
            onChange={(event) => setValues({ ...values, [key]: event.target.value })}
            required
            disabled={disabled}
          />
        ))}
      </div>
      <p className="text-13 text-ink-2">{t("collection.thresholdHint")}</p>
      <Button type="submit" disabled={disabled || !valid} loading={busy === `processor:${processor.id}`} className="self-start">
        {t("collection.processorSave")}
      </Button>
    </form>
  );
}

export function CollectionAdvanced({ data, disabled, busy, mutate }: Controls & {
  data: HomeCollection;
}) {
  const t = useT();
  const [tab, setTab] = useState("sources");
  const local = data.sources.find((source) => source.kind === "local");
  const controls = { disabled, busy, mutate };
  return (
    <details className="border-t border-line pt-5">
      <summary className="cursor-pointer text-14 font-medium text-accent">{t("collection.advanced")}</summary>
      <Tabs
        className="mt-4"
        aria-label={t("collection.advanced")}
        value={tab}
        onChange={setTab}
        tabs={[
          {
            value: "sources", label: t("collection.sources"), panel: (
              <div className="flex flex-col gap-8">
                <div className="divide-y divide-line">
                  {data.sources.map((source) => (
                    <div key={source.id} className="flex flex-col gap-2 py-4">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <h3 className="text-14 font-medium">{source.label}</h3>
                        <span className="text-12 text-ink-2">{t(`collection.source.${source.kind}`)}</span>
                        <span className="text-12 text-ink-2">{t(source.enabled ? "collection.sourceEnabled" : "collection.sourceDisabled")}</span>
                      </div>
                      {source.complex_scope
                        ? <p className="text-13 text-ink-2">{t("collection.customScope")}</p>
                        : source.scope?.projects.length && source.scope?.harnesses.length
                          ? <CollectionScopeSummary scope={source.scope} />
                          : <p className="text-13 text-ink-2">{t(source.kind === "r2" ? "collection.deviceScoped" : "collection.noLocalScope")}</p>}
                      <p className="text-12 text-ink-2">
                        {t("collection.processor")}: {data.processors.find((processor) => processor.id === source.processor_id)?.label ?? source.processor_id}
                      </p>
                    </div>
                  ))}
                </div>
                {local && <LocalCollectionForm key={JSON.stringify(local)} source={local} {...controls} />}
                {data.cloud.configured && <CloudConnectionForm key={data.cloud.url} cloud={data.cloud} {...controls} />}
              </div>
            ),
          },
          {
            value: "processors", label: t("collection.processors"), panel: (
              <div>
                <p className="text-13 text-ink-2">{t("collection.processorHint")}</p>
                {data.processors.map((processor) => (
                  <ProcessorForm key={JSON.stringify(processor)} processor={processor}
                    sourceCount={data.sources.filter((source) => source.processor_id === processor.id).length} {...controls} />
                ))}
              </div>
            ),
          },
          {
            value: "projects", label: t("collection.projects"), panel: (
              <div>
                <p className="mb-4 text-13 text-ink-2">{t("collection.projectNote")}</p>
                {data.projects.length === 0 && <p className="py-4 text-14 text-ink-2">{t("collection.noProjects")}</p>}
                <div className="divide-y divide-line">
                  {data.projects.map((project) => (
                    <div key={project.project_id} className="flex flex-col gap-3 py-5">
                      <h3 className="flex items-center gap-2 font-serif text-20"><GitBranch size={16} aria-hidden />{project.name}</h3>
                      <p className="text-12 text-ink-2">{t("collection.projectId")} <Mono className="break-all">{project.project_id}</Mono></p>
                      {project.remotes.length > 0
                        ? project.remotes.map((remote) => <Mono key={remote} className="break-all text-13">{remote}</Mono>)
                        : <p className="text-13 text-ink-2">{t("collection.noRemote")}</p>}
                      <dl aria-label={t("collection.projectLocations")} className="flex flex-col gap-2">
                        {project.locations.map((location) => (
                          <div key={`${location.device_id}:${location.path}`} className="grid grid-cols-1 gap-1 text-13 sm:grid-cols-[160px_minmax(0,1fr)] sm:gap-3">
                            <dt className="break-words text-ink-2">{data.devices.find((device) => device.device_id === location.device_id)?.label ?? location.device_id}</dt>
                            <dd><Mono className="break-all">{location.path}</Mono></dd>
                          </div>
                        ))}
                      </dl>
                      <p className="text-12 text-ink-2">{t("collection.projectSources", { count: project.source_ids.length })}</p>
                    </div>
                  ))}
                </div>
              </div>
            ),
          },
        ]}
      />
    </details>
  );
}

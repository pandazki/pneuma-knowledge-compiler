import type { CollectionScope, CollectionScopeDraft } from "@/lib/collection";
import { useT } from "@/lib/useT";
import { Checkbox } from "@/ui/Checkbox";
import { Select } from "@/ui/Select";
import { TextArea } from "@/ui/TextArea";
import { TextField } from "@/ui/TextField";

export function CollectionScopeFields({
  value,
  onChange,
  disabled,
  local = false,
}: {
  value: CollectionScopeDraft;
  onChange: (next: CollectionScopeDraft) => void;
  disabled: boolean;
  local?: boolean;
}) {
  const t = useT();
  return (
    <div className="flex flex-col gap-4">
      <Select
        label={t("collection.scopeProjects")}
        value={value.allProjects ? "all" : "selected"}
        onChange={(mode) => onChange({ ...value, allProjects: mode === "all" })}
        disabled={disabled}
        options={[
          { value: "all", label: t("collection.scopeAll") },
          { value: "selected", label: t("collection.scopeSelected") },
        ]}
      />
      {!value.allProjects && (
        <TextArea
          label={t(local ? "collection.scopeLocalPaths" : "collection.scopePaths")}
          hint={t("collection.scopePathsHint")}
          value={value.projects}
          onChange={(event) => onChange({ ...value, projects: event.target.value })}
          rows={3}
          required
          disabled={disabled}
          spellCheck={false}
          className="font-mono text-13"
        />
      )}
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2" disabled={disabled}>
        <legend className="mb-2 text-13 font-medium text-ink-2">{t("collection.scopeHarnesses")}</legend>
        {(["codex", "claude-code"] as const).map((harness) => (
          <Checkbox
            key={harness}
            checked={value.harnesses.includes(harness)}
            disabled={disabled}
            onCheckedChange={(checked) => onChange({
              ...value,
              harnesses: checked === true
                ? [...value.harnesses, harness]
                : value.harnesses.filter((item) => item !== harness),
            })}
            label={t(harness === "codex" ? "collection.codex" : "collection.claude")}
          />
        ))}
      </fieldset>
      <TextField
        type="date"
        label={t("collection.scopeSince")}
        hint={t("collection.scopeSinceHint")}
        value={value.since}
        onChange={(event) => onChange({ ...value, since: event.target.value })}
        disabled={disabled}
      />
    </div>
  );
}

export function CollectionScopeSummary({ scope }: { scope: CollectionScope | null }) {
  const t = useT();
  if (!scope) return <p className="text-13 text-warn">{t("collection.scopeInvalid")}</p>;
  const formats = scope.harnesses.map((harness) =>
    t(harness === "codex" ? "collection.codex" : "collection.claude"),
  ).join(" / ");
  return (
    <p className="text-13 leading-relaxed text-ink-2">
      {scope.projects.includes("all")
        ? t("collection.scopeAll")
        : t("collection.scopeProjectsCount", { count: scope.projects.length })}
      <span aria-hidden> · </span>{formats}<span aria-hidden> · </span>
      {scope.since ? t("collection.scopeFrom", { date: scope.since.slice(0, 10) }) : t("collection.scopeHistory")}
    </p>
  );
}

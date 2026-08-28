import { useEffect, useState, type ReactNode } from "react";
import { Pencil, Sparkles, UserRound } from "lucide-react";
import { useApp } from "@/lib/store";
import {
  generateProfile,
  getUserProfile,
  putUserProfile,
  type UserProfilePatch,
} from "@/lib/api";
import { fmtDate, fmtDay } from "@/lib/format";
import type { UserProfile } from "@/lib/types";
import { useT, useTOr, type TOrFunction } from "@/lib/useT";
import { PageHeader } from "@/components/PageHeader";
import { UserPicker } from "@/components/UserPicker";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { NumberField } from "@/ui/NumberField";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { Skeleton, SkeletonText } from "@/ui/Skeleton";
import { Stamp } from "@/ui/Stamp";
import { TextArea } from "@/ui/TextArea";
import { TextField } from "@/ui/TextField";

/* ------------------------------------ Value domains (mirroring user.py's enums) */

const INDUSTRIES = [
  "tech",
  "finance",
  "sports",
  "creative",
  "education",
  "healthcare",
  "marketing",
  "other",
] as const;
const ROLES = [
  "engineering",
  "marketing",
  "product_management",
  "sales",
  "design",
  "support",
  "admin",
  "other",
] as const;
/** Six seniority levels, low → high; drives the AI's answer style. */
const LEVELS = ["entry", "junior", "mid", "senior", "staff", "principal"] as const;
const LANGUAGES = ["zh-CN", "en-US", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES"] as const;
const UNITS = ["metric", "imperial"] as const;
const PRIVACY = ["standard", "strict"] as const;
const WORKSPACE_MODES = ["independent", "team", "organization"] as const;
const AUTOMATION_LEVELS = ["manual", "assisted", "agentic"] as const;

/**
 * The industry / role / seniority vocabulary is spelled out in `i18n/profile.ts`
 * (`profile.core.*`) because the API ships keys without labels. `tOr` is what keeps a value
 * outside the vocabulary — one the service grew and this client has not learned — rendering
 * as its raw wire value rather than as a blank. Same for the per-level answer-style hint
 * (`profile.levelStyle.*`), whose wording mirrors the service's own.
 */
const coreKey = (value: string) => `profile.core.${value}`;

/** industry/role display: the free-text `*_other` stands in when the enum is `other`. */
function coreLabel(tOr: TOrFunction, value: string, other: string | null): string {
  if (value === "other") return other?.trim() || tOr(coreKey("other"), "other");
  return tOr(coreKey(value), value);
}

/** Select options: a current value outside the domain stays selectable (no data lost). */
function enumOptions(tOr: TOrFunction, domain: readonly string[], current: string) {
  const values = domain.includes(current) ? [...domain] : [current, ...domain];
  return values.map((v) => ({ value: v, label: tOr(coreKey(v), v) }));
}

const rawOptions = (domain: readonly string[], current: string) => {
  const values = domain.includes(current) ? [...domain] : [current, ...domain];
  return values.map((v) => ({ value: v, label: v }));
};

/* ------------------------------------------------------------- The edit form */

interface FormState {
  display_name: string;
  gender: string;
  birth_year: number | null;
  industry: string;
  industry_other: string;
  role: string;
  role_other: string;
  level: string;
  occupation: string;
  bio: string;
  /** Comma-separated; split back into a string[] on submit. */
  interestsText: string;
  city: string;
  country: string;
  timezone: string;
  language: string;
  response_language: string;
  units: string;
  privacy_level: string;
  workspace_mode: string;
  workspace_stack: string;
  workspace_automation: string;
  workspace_since: string;
}

/**
 * Seed the form from a profile (or an AI draft). The read-only fields — avatar,
 * level_style, joined_at, source — never enter it.
 */
function toForm(p: UserProfile): FormState {
  return {
    display_name: p.display_name ?? "",
    gender: p.gender ?? "",
    birth_year: p.birth_year,
    industry: p.industry ?? "tech",
    industry_other: p.industry_other ?? "",
    role: p.role ?? "engineering",
    role_other: p.role_other ?? "",
    level: p.level ?? "mid",
    occupation: p.occupation ?? "",
    bio: p.bio ?? "",
    interestsText: (p.interests ?? []).join(", "),
    city: p.locale.city ?? "",
    country: p.locale.country ?? "",
    timezone: p.locale.timezone ?? "",
    language: p.locale.language ?? "zh-CN",
    response_language: p.preferences.response_language ?? "zh-CN",
    units: p.preferences.units ?? "metric",
    privacy_level: p.preferences.privacy_level ?? "standard",
    workspace_mode: p.workspace.operating_mode ?? "independent",
    workspace_stack: p.workspace.primary_stack ?? "",
    workspace_automation: p.workspace.automation_level ?? "agentic",
    workspace_since: p.workspace.active_since ?? "",
  };
}

/** Form → the patch for PUT /profile (the editable subset only). */
function toPatch(f: FormState): UserProfilePatch {
  return {
    display_name: f.display_name.trim(),
    gender: f.gender.trim() || null,
    birth_year: f.birth_year,
    industry: f.industry,
    industry_other: f.industry === "other" ? f.industry_other.trim() || null : null,
    role: f.role,
    role_other: f.role === "other" ? f.role_other.trim() || null : null,
    level: f.level,
    occupation: f.occupation.trim(),
    bio: f.bio.trim(),
    interests: f.interestsText
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean),
    locale: {
      city: f.city.trim(),
      country: f.country.trim(),
      timezone: f.timezone.trim(),
      language: f.language,
    },
    preferences: {
      response_language: f.response_language,
      units: f.units,
      privacy_level: f.privacy_level,
    },
    workspace: {
      operating_mode: f.workspace_mode,
      primary_stack: f.workspace_stack.trim(),
      automation_level: f.workspace_automation,
      active_since: f.workspace_since.trim(),
    },
  };
}

function FormGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-4 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <p className="text-12 text-ink-3">{label}</p>
      {children}
    </div>
  );
}

interface ProfileFormProps {
  uid: string;
  /** What seeds the fields: the current profile, or an AI draft. */
  seed: UserProfile;
  disabled?: boolean;
  onSaved: (saved: UserProfile) => void;
  onCancel: () => void;
  cancelLabel?: string;
}

function ProfileForm({ uid, seed, disabled, onSaved, onCancel, cancelLabel }: ProfileFormProps) {
  const t = useT();
  const tOr = useTOr();
  const [form, setForm] = useState<FormState>(() => toForm(seed));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    setErr(null);
    if (!form.display_name.trim()) {
      setErr(t("profile.form.nameRequired"));
      return;
    }
    setSaving(true);
    try {
      const saved = await putUserProfile(uid, toPatch(form));
      onSaved(saved);
    } catch (e) {
      setErr(t("profile.form.saveFailed", { detail: (e as Error).message }));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <FormGroup label={t("profile.group.basics")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("profile.field.displayName")}
            value={form.display_name}
            onChange={(e) => set("display_name", e.target.value)}
            disabled={disabled}
            required
          />
          <TextField
            label={t("profile.field.occupation")}
            value={form.occupation}
            onChange={(e) => set("occupation", e.target.value)}
            disabled={disabled}
            placeholder={t("profile.placeholder.occupation")}
          />
          <TextField
            label={t("profile.field.gender")}
            value={form.gender}
            onChange={(e) => set("gender", e.target.value)}
            disabled={disabled}
          />
          <NumberField
            label={t("profile.field.birthYear")}
            value={form.birth_year}
            onChange={(v) => set("birth_year", v)}
            min={1900}
            max={2100}
            disabled={disabled}
          />
        </div>
        <TextArea
          label={t("profile.field.bio")}
          value={form.bio}
          onChange={(e) => set("bio", e.target.value)}
          disabled={disabled}
          autoRows
          maxRows={6}
          placeholder={t("profile.placeholder.bio")}
        />
        <TextField
          label={t("profile.field.interests")}
          value={form.interestsText}
          onChange={(e) => set("interestsText", e.target.value)}
          disabled={disabled}
          hint={t("profile.hint.interests")}
          placeholder={t("profile.placeholder.interests")}
        />
      </FormGroup>

      <FormGroup label={t("profile.group.style")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label={t("profile.field.industry")}
            value={form.industry}
            onChange={(v) => set("industry", v)}
            options={enumOptions(tOr, INDUSTRIES, form.industry)}
            disabled={disabled}
          />
          {form.industry === "other" && (
            <TextField
              label={t("profile.field.industryOther")}
              value={form.industry_other}
              onChange={(e) => set("industry_other", e.target.value)}
              disabled={disabled}
              placeholder={t("profile.placeholder.industryOther")}
            />
          )}
          <Select
            label={t("profile.field.role")}
            value={form.role}
            onChange={(v) => set("role", v)}
            options={enumOptions(tOr, ROLES, form.role)}
            disabled={disabled}
          />
          {form.role === "other" && (
            <TextField
              label={t("profile.field.roleOther")}
              value={form.role_other}
              onChange={(e) => set("role_other", e.target.value)}
              disabled={disabled}
              placeholder={t("profile.placeholder.roleOther")}
            />
          )}
        </div>
        <Select
          label={t("profile.field.level")}
          value={form.level}
          onChange={(v) => set("level", v)}
          options={(LEVELS.includes(form.level as (typeof LEVELS)[number])
            ? [...LEVELS]
            : [form.level, ...LEVELS]
          ).map((l) => ({
            value: l,
            label: `${(LEVELS as readonly string[]).indexOf(l) + 1 || "?"} · ${tOr(coreKey(l), l)}`,
          }))}
          // Empty for a level outside the vocabulary, which reads as "no hint".
          hint={tOr(`profile.levelStyle.${form.level}`, "")}
          disabled={disabled}
        />
      </FormGroup>

      <FormGroup label={t("profile.group.locale")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("profile.field.city")}
            value={form.city}
            onChange={(e) => set("city", e.target.value)}
            disabled={disabled}
          />
          <TextField
            label={t("profile.field.country")}
            value={form.country}
            onChange={(e) => set("country", e.target.value)}
            disabled={disabled}
          />
          <TextField
            label={t("profile.field.timezone")}
            value={form.timezone}
            onChange={(e) => set("timezone", e.target.value)}
            disabled={disabled}
            placeholder="Asia/Shanghai"
          />
          <Select
            label={t("profile.field.language")}
            value={form.language}
            onChange={(v) => set("language", v)}
            options={rawOptions(LANGUAGES, form.language)}
            disabled={disabled}
          />
          <Select
            label={t("profile.field.responseLanguage")}
            value={form.response_language}
            onChange={(v) => set("response_language", v)}
            options={rawOptions(LANGUAGES, form.response_language)}
            disabled={disabled}
          />
          <Select
            label={t("profile.field.units")}
            value={form.units}
            onChange={(v) => set("units", v)}
            options={rawOptions(UNITS, form.units)}
            disabled={disabled}
          />
          <Select
            label={t("profile.field.privacy")}
            value={form.privacy_level}
            onChange={(v) => set("privacy_level", v)}
            options={rawOptions(PRIVACY, form.privacy_level)}
            disabled={disabled}
          />
        </div>
      </FormGroup>

      <FormGroup label={t("profile.group.workspace")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label={t("profile.field.workspaceMode")}
            value={form.workspace_mode}
            onChange={(v) => set("workspace_mode", v)}
            options={rawOptions(WORKSPACE_MODES, form.workspace_mode)}
            disabled={disabled}
          />
          <TextField
            label={t("profile.field.workspaceStack")}
            value={form.workspace_stack}
            onChange={(e) => set("workspace_stack", e.target.value)}
            disabled={disabled}
            placeholder="TypeScript + Python"
          />
          <Select
            label={t("profile.field.workspaceAutomation")}
            value={form.workspace_automation}
            onChange={(v) => set("workspace_automation", v)}
            options={rawOptions(AUTOMATION_LEVELS, form.workspace_automation)}
            disabled={disabled}
          />
          <TextField
            label={t("profile.field.workspaceSince")}
            value={form.workspace_since}
            onChange={(e) => set("workspace_since", e.target.value)}
            disabled={disabled}
            placeholder="2024-05-01"
          />
        </div>
      </FormGroup>

      {err && (
        <Callout tone="danger" title={t("profile.form.saveFailedTitle")}>
          {err}
        </Callout>
      )}

      <div className="flex items-center gap-2 border-t border-line pt-4">
        <Button variant="primary" loading={saving} disabled={disabled} onClick={() => void save()}>
          {t("profile.form.save")}
        </Button>
        <Button variant="ghost" disabled={saving} onClick={onCancel}>
          {cancelLabel ?? t("profile.form.cancel")}
        </Button>
      </div>
    </div>
  );
}

/* --------------------------------------------------- The read-only definition list */

function joinParts(parts: (string | null | undefined)[]): string | null {
  const s = parts.filter((p) => p && p.trim()).join(" · ");
  return s || null;
}

function ProfileFields({ p }: { p: UserProfile }) {
  const t = useT();
  const tOr = useTOr();
  const levelIdx = (LEVELS as readonly string[]).indexOf(p.level);
  const dash = <span className="text-ink-3">—</span>;
  return (
    <DefinitionList
      termClassName="sm:w-32"
      items={[
        { term: "user_id", definition: <Mono>{p.user_id}</Mono> },
        { term: t("profile.term.industry"), definition: coreLabel(tOr, p.industry, p.industry_other) },
        { term: t("profile.term.role"), definition: coreLabel(tOr, p.role, p.role_other) },
        {
          term: t("profile.term.level"),
          definition: (
            <>
              {coreLabel(tOr, p.level, null)}
              {levelIdx >= 0 && (
                <Mono className="ml-2 text-12 text-ink-3">
                  {levelIdx + 1}/{LEVELS.length}
                </Mono>
              )}
            </>
          ),
        },
        { term: t("profile.term.levelStyle"), definition: p.level_style || dash },
        { term: t("profile.term.occupation"), definition: p.occupation || dash },
        { term: t("profile.term.bio"), definition: p.bio || dash },
        {
          term: t("profile.term.interests"),
          definition:
            p.interests.length > 0 ? (
              <span className="flex flex-wrap gap-1.5">
                {p.interests.map((it) => (
                  <Badge key={it}>{it}</Badge>
                ))}
              </span>
            ) : (
              dash
            ),
        },
        {
          term: t("profile.term.region"),
          definition:
            joinParts([
              joinParts([p.locale.city, p.locale.country]),
              p.locale.timezone,
              p.locale.language,
            ]) ?? dash,
        },
        {
          term: t("profile.term.workspace"),
          // The values are wire codes (independent / agentic / a stack string): labelled, not
          // translated.
          definition:
            joinParts([
              p.workspace.operating_mode
                ? t("profile.summary.mode", { value: p.workspace.operating_mode })
                : null,
              p.workspace.primary_stack
                ? t("profile.summary.stack", { value: p.workspace.primary_stack })
                : null,
              p.workspace.automation_level
                ? t("profile.summary.automation", { value: p.workspace.automation_level })
                : null,
              p.workspace.active_since
                ? t("profile.summary.since", { value: fmtDay(p.workspace.active_since) })
                : null,
            ]) ?? dash,
        },
        {
          term: t("profile.term.preferences"),
          definition:
            joinParts([
              p.preferences.response_language
                ? t("profile.summary.responseLanguage", {
                    value: p.preferences.response_language,
                  })
                : null,
              p.preferences.units
                ? t("profile.summary.units", { value: p.preferences.units })
                : null,
              p.preferences.privacy_level
                ? t("profile.summary.privacy", { value: p.preferences.privacy_level })
                : null,
            ]) ?? dash,
        },
        { term: t("profile.term.joinedAt"), definition: p.joined_at ? fmtDate(p.joined_at) : dash },
      ]}
    />
  );
}

/* ------------------------------------------------------------------- The view */

export default function ProfileView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const profile = useApp((s) => s.currentProfile);
  const setProfile = useApp((s) => s.setProfile);
  const onboarding = useApp(
    (s) => s.currentUser != null && s.profileOnboardingUser === s.currentUser,
  );
  const finishProfileCreation = useApp((s) => s.finishProfileCreation);
  /** Historical snapshots are read-only: every mutating control is disabled (DESIGN.md §4.3). */
  const readOnly = useApp((s) => s.currentSnapshot != null);

  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState(false);
  /**
   * The AI's draft: it only pre-fills the form, it is never stored. A changing nonce is what
   * re-seeds the form.
   */
  const [draft, setDraft] = useState<{ profile: UserProfile; nonce: number } | null>(null);

  const [sentence, setSentence] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  // This view loads the profile itself so it can show a real error state: store.loadProfile
  // swallows failures and degrades, which cannot drive an ErrorState. On success the result
  // goes back into the store, which stays the single source for what is displayed.
  useEffect(() => {
    setEditing(onboarding);
    setDraft(null);
    setGenError(null);
    if (!currentUser) {
      setPhase("ready");
      setLoadError(null);
      return;
    }
    let live = true;
    setPhase("loading");
    setLoadError(null);
    getUserProfile(currentUser)
      .then((p) => {
        if (!live) return;
        setProfile(currentUser, p);
        setPhase("ready");
      })
      .catch((e: Error) => {
        if (!live) return;
        setLoadError(e.message);
        setPhase("error");
      });
    return () => {
      live = false;
    };
  }, [currentUser, onboarding, attempt, setProfile]);

  async function generate() {
    const s = sentence.trim();
    if (!s || !currentUser) return;
    setGenError(null);
    setGenerating(true);
    try {
      const p = await generateProfile(s, currentUser);
      setDraft((d) => ({ profile: p, nonce: (d?.nonce ?? 0) + 1 }));
      setEditing(true);
    } catch (e) {
      setGenError(t("profile.ai.failed", { detail: (e as Error).message }));
    } finally {
      setGenerating(false);
    }
  }

  const aiSection = (
    <section>
      <SectionRule no={2} title={t("profile.ai.title")} className="mb-3" />
      <p className="mb-3 max-w-measure text-13 text-ink-2">{t("profile.ai.lead")}</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <TextField
          wrapperClassName="flex-1"
          aria-label={t("profile.ai.inputAria")}
          value={sentence}
          onChange={(e) => setSentence(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void generate();
            }
          }}
          disabled={readOnly || generating}
          placeholder={t("profile.ai.placeholder")}
        />
        <Button
          variant="primary"
          loading={generating}
          disabled={readOnly || !sentence.trim()}
          onClick={() => void generate()}
        >
          <Sparkles size={14} aria-hidden />
          {t("profile.ai.generate")}
        </Button>
      </div>
      {genError && <p className="mt-2 text-12 text-danger">{genError}</p>}
    </section>
  );

  if (!currentUser) {
    return (
      <>
        <PageHeader
          title={t("nav.view.profile")}
          description={t("profile.header.description")}
        />
        <EmptyState
          icon={UserRound}
          title={t("profile.empty.title")}
          description={t("profile.empty.description")}
          action={<UserPicker />}
        />
      </>
    );
  }

  if (phase === "error") {
    return (
      <>
        <PageHeader
          title={t("nav.view.profile")}
          description={t("profile.header.descriptionShort")}
        />
        <ErrorState
          title={t("profile.error.title")}
          error={loadError ?? t("common.unknownError")}
          onRetry={() => setAttempt((a) => a + 1)}
        />
      </>
    );
  }

  if (phase === "loading" || !profile) {
    return (
      <>
        <PageHeader
          title={t("nav.view.profile")}
          description={t("profile.header.descriptionShort")}
        />
        <div aria-busy className="flex flex-col gap-8">
          <div className="flex items-center gap-4">
            <Skeleton className="size-14" />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-6 w-40" />
              <Skeleton className="h-3.5 w-56" />
            </div>
          </div>
          <SkeletonText lines={6} />
        </div>
      </>
    );
  }

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        title={onboarding ? t("profile.onboarding.title") : t("nav.view.profile")}
        description={
          onboarding
            ? t("profile.onboarding.description")
            : t("profile.header.demoDescription")
        }
        actions={
          !onboarding && !editing ? (
            <Button size="sm" disabled={readOnly} onClick={() => setEditing(true)}>
              <Pencil size={13} aria-hidden />
              {t("profile.action.edit")}
            </Button>
          ) : undefined
        }
      />

      {/* Identity: the avatar letter tile, display_name, the mono id, the synthetic stamp. */}
      <section className="flex flex-wrap items-center gap-4">
        <span
          aria-hidden
          className="inline-flex size-14 shrink-0 items-center justify-center rounded-2 bg-active font-serif text-24 text-ink"
        >
          {profile.avatar.initial}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-serif text-24 text-balance text-ink">{profile.display_name}</h2>
            {/* The stamp states provenance, so it follows `source`: a profile the owner edited
                and saved is theirs, not a synthesised persona. */}
            {profile.source !== "user" && <Stamp tone="neutral">SYNTHETIC</Stamp>}
          </div>
          <Mono className="text-13 text-ink-3">{profile.user_id}</Mono>
          <p className="text-12 text-ink-3">
            {t("profile.source.prefix")} <Mono>source = {profile.source}</Mono>
            {t("profile.source.legend")}
          </p>
        </div>
      </section>

      {onboarding ? (
        <>
          {aiSection}
          {draft && (
            <Callout tone="notice" title={t("profile.draft.title")}>
              {t("profile.draft.body")}
            </Callout>
          )}
          <section>
            <SectionRule no={2} title={t("profile.section.confirm")} className="mb-4" />
            <ProfileForm
              key={draft ? `draft-${draft.nonce}` : "base"}
              uid={currentUser}
              seed={draft?.profile ?? profile}
              disabled={readOnly}
              onSaved={(saved) => {
                setProfile(currentUser, saved);
                setDraft(null);
                finishProfileCreation(true);
              }}
              onCancel={() => {
                setDraft(null);
                finishProfileCreation(false);
              }}
              cancelLabel={t("profile.form.skip")}
            />
          </section>
        </>
      ) : editing ? (
        <section>
          <SectionRule no={1} title={t("profile.section.edit")} className="mb-4" />
          <ProfileForm
            uid={currentUser}
            seed={profile}
            disabled={readOnly}
            onSaved={(saved) => {
              setProfile(currentUser, saved);
              setEditing(false);
            }}
            onCancel={() => setEditing(false)}
          />
        </section>
      ) : (
        <section>
          <SectionRule no={1} title={t("profile.section.core")} className="mb-2" />
          <ProfileFields p={profile} />
        </section>
      )}
    </div>
  );
}

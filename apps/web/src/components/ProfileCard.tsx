/**
 * ProfileCard — the single source of truth for rendering a user picture, in three
 * modes:
 *   - "view":   read-only display (Profile tab, switcher-modal preview).
 *   - "edit":   editable form for an existing user_id (PUT /profile).
 *   - "create": editable form for a brand-new id (id field + 🎲 random-fill, then
 *               PUT /profile materializes it).
 *
 * The edit/create forms are the same field set — "新建/编辑就是 ProfileView 的可编辑版本".
 * Visuals reuse the existing tokens/primitives only (no new style).
 */
import { type ReactNode, useMemo, useState } from "react";
import {
  UserRound,
  Sparkles,
  Briefcase,
  Layers,
  MapPin,
  Code2,
  SlidersHorizontal,
  CalendarDays,
  Info,
  Plus,
  X,
  Loader2,
  Dice5,
} from "lucide-react";
import { Card, Chip, Eyebrow, Button } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import type { UserProfile } from "@/lib/types";
import * as api from "@/lib/api";

/* --------------------------------------------------------------------- action bar */

/**
 * The card's fixed action strip: a sticky toolbar pinned to the top of the scroll
 * container, mode label on the left and right-aligned action buttons. Used in all
 * three modes (view / edit / create) so the primary actions never scatter to the
 * form's end and stay visible while the body scrolls. `-mx-5 -mt-5` cancels the
 * card root's px-5/pt-5 so the bar spans flush edge-to-edge and sticks at top:0.
 */
function ActionBar({ label, children }: { label?: ReactNode; children?: ReactNode }) {
  return (
    <div
      className={cn(
        "sticky top-0 z-10 -mx-5 -mt-5 mb-5 flex items-center justify-between gap-3",
        "border-b border-border bg-card px-5 py-2.5",
      )}
    >
      <div className="min-w-0 flex-1 truncate">{label}</div>
      <div className="flex flex-none items-center gap-2">{children}</div>
    </div>
  );
}

/* ---------------------------------------------------------------- enum value sets */
// Mirror packages/pneuma-knowledge-core/.../domain/user.py — the select value domains.
export const INDUSTRIES = [
  "tech",
  "finance",
  "sports",
  "creative",
  "education",
  "healthcare",
  "marketing",
  "other",
] as const;
export const ROLES = [
  "engineering",
  "marketing",
  "product_management",
  "sales",
  "design",
  "support",
  "admin",
  "other",
] as const;
/** 6 seniority tiers, low → high; drives the AI answer style. */
export const LEVELS = ["entry", "junior", "mid", "senior", "staff", "principal"] as const;
/** Answer-style directive per level (mirrors user.py LEVEL_STYLES). */
export const LEVEL_STYLES: Record<string, string> = {
  entry: "用定义和逐步拆解解释问题，不预设背景知识。",
  junior: "给出清晰说明、具体例子和必要的下一步指引。",
  mid: "平衡结论、理由与可执行细节。",
  senior: "保持简洁，优先呈现取舍、影响和决策边界。",
  staff: "突出系统影响、跨域约束和边界情况。",
  principal: "默认深厚专业背景，只保留决策所需的高信号信息。",
};
const UNITS = ["metric", "imperial"] as const;
const PRIVACY = ["standard", "strict"] as const;
const LANGUAGES = ["zh-CN", "en-US", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES"] as const;

/** Valid user_id shape — external key, keep it filesystem/URL-safe. */
const USER_ID_RE = /^[A-Za-z0-9._:-]+$/;

/* ------------------------------------------------------------------ label helpers */

/** enum → human label ("product_management" → "Product Management"). */
function titleCase(s: string): string {
  return s
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

const CORE_LABELS: Record<string, string> = {
  tech: "技术与软件",
  finance: "金融",
  sports: "体育",
  creative: "创意",
  education: "教育",
  healthcare: "医疗健康",
  marketing: "市场",
  engineering: "独立工程",
  product_management: "产品管理",
  sales: "销售",
  design: "设计",
  support: "客户支持",
  admin: "运营管理",
  other: "其他",
  entry: "入门",
  junior: "初级",
  mid: "中级",
  senior: "资深",
  staff: "专家",
  principal: "首席",
  male: "男",
  female: "女",
};

/** industry/role display: honor the free-text `*_other` when the enum is "other". */
function coreLabel(value: string, other: string | null): string {
  if (value === "other") return other?.trim() || CORE_LABELS.other;
  return CORE_LABELS[value] ?? titleCase(value);
}

const LEVEL_ORDER = LEVELS as readonly string[];

/* =============================================================== READ-ONLY (view) */

/** Label/value row inside a group card; renders nothing when the value is empty. */
function Field({ label, value }: { label: string; value: ReactNode }) {
  const empty =
    value == null || value === "" || (Array.isArray(value) && value.length === 0);
  if (empty) return null;
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="flex-none text-[length:var(--text-2xs)] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="min-w-0 break-words text-right text-[length:var(--text-sm)] text-foreground">
        {value}
      </span>
    </div>
  );
}

/** A titled group card; renders nothing when it holds no non-empty fields. */
function GroupCard({
  icon,
  title,
  children,
  hasContent,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  hasContent: boolean;
}) {
  if (!hasContent) return null;
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-1.5 text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
        {icon}
        {title}
      </div>
      <div className="divide-y divide-border-subtle">{children}</div>
    </Card>
  );
}

/** The core onboarding trio (industry / role / level) — the answer-style DNA. */
function AnswerStyle({ p }: { p: UserProfile }) {
  const industry = coreLabel(p.industry, p.industry_other);
  const role = coreLabel(p.role, p.role_other);
  const levelIdx = LEVEL_ORDER.indexOf(p.level);
  return (
    <section>
      <div className="mb-2 flex items-center gap-1.5">
        <Sparkles size={13} className="text-[var(--color-accent)]" />
        <Eyebrow>回答风格 · Answer Style</Eyebrow>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Card className="p-4">
          <div className="flex items-center gap-1.5 text-[length:var(--text-2xs)] uppercase tracking-wide text-muted-foreground">
            <Briefcase size={12} /> Industry
          </div>
          <div className="mt-1.5 text-[length:var(--text-lg)] font-light text-foreground">{industry}</div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-1.5 text-[length:var(--text-2xs)] uppercase tracking-wide text-muted-foreground">
            <UserRound size={12} /> Role
          </div>
          <div className="mt-1.5 text-[length:var(--text-lg)] font-light text-foreground">{role}</div>
        </Card>
        <Card
          className="p-4"
          style={{
            borderColor: "var(--color-accent)",
            background: "var(--color-surface-muted)",
          }}
        >
          <div className="flex items-center gap-1.5 text-[length:var(--text-2xs)] uppercase tracking-wide text-muted-foreground">
            <Layers size={12} /> Level
            {levelIdx >= 0 && (
              <span className="ml-auto font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                {levelIdx + 1}/{LEVEL_ORDER.length}
              </span>
            )}
          </div>
          <div className="mt-1.5 text-[length:var(--text-lg)] font-light text-foreground">
            {coreLabel(p.level, null)}
          </div>
        </Card>
      </div>
      {p.level_style && (
        <div className="mt-3 flex items-start gap-2 rounded-sm border border-border bg-card p-3">
          <Sparkles size={14} className="mt-0.5 flex-none text-[var(--color-accent)]" />
          <div>
            <div className="text-[length:var(--text-sm)] leading-5 text-foreground">
              {LEVEL_STYLES[p.level] ?? p.level_style}
            </div>
            <div className="mt-1 text-[length:var(--text-2xs)] text-muted-foreground">
              Level 决定 AI 回答风格——不同资历档位对应不同的回答语气与深度。
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function ProfileHeader({ p, uid }: { p: UserProfile; uid: string }) {
  return (
    <div className="flex items-start gap-4">
      <div
        className="flex h-16 w-16 flex-none items-center justify-center rounded-full text-[length:var(--text-2xl)] font-light text-white"
        style={{ background: p.avatar.color }}
        aria-hidden
      >
        {p.avatar.initial}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[length:var(--text-2xl)] font-light leading-tight tracking-[-0.02em] text-foreground">
          {p.display_name}
        </div>
        {p.occupation && (
          <div className="mt-0.5 text-sm text-muted-foreground">{p.occupation}</div>
        )}
        <div className="mt-1 break-all font-mono text-[length:var(--text-2xs)] text-muted-foreground">{uid}</div>
      </div>
    </div>
  );
}

/** Read-only body of a profile (the old ProfileView content). */
function ProfileReadOnly({
  p,
  uid,
  actions,
}: {
  p: UserProfile;
  uid: string;
  actions?: ReactNode;
}) {
  const localeParts = [p.locale.city, p.locale.country].filter(Boolean).join(", ");
  const hasLocale = !!(localeParts || p.locale.timezone || p.locale.language);
  const hasWorkspace = !!(
    p.workspace.operating_mode ||
    p.workspace.primary_stack ||
    p.workspace.automation_level ||
    p.workspace.active_since
  );
  const hasPrefs = !!(
    p.preferences.response_language ||
    p.preferences.units ||
    p.preferences.privacy_level
  );

  return (
    <div className="px-5 py-5">
      <ActionBar label={<Eyebrow>用户画像 · Profile</Eyebrow>}>{actions}</ActionBar>

      <div className="space-y-6">
        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-end gap-3">
            <span
              className="inline-flex items-center gap-1 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-[length:var(--text-2xs)] text-muted-foreground"
              style={{ background: "var(--color-surface-muted)" }}
              title="画像来源：mock=合成，user=用户已保存"
            >
              <Info size={10} /> source = {p.source}
            </span>
          </div>
          <ProfileHeader p={p} uid={uid} />
        </div>

        <AnswerStyle p={p} />

      {p.bio && (
        <section>
          <Eyebrow className="mb-2">Bio</Eyebrow>
          <Card className="p-4 text-[length:var(--text-sm)] leading-6 text-foreground">{p.bio}</Card>
        </section>
      )}

      {p.interests.length > 0 && (
        <section>
          <Eyebrow className="mb-2">Interests · {p.interests.length}</Eyebrow>
          <div className="flex flex-wrap gap-1.5">
            {p.interests.map((it, i) => (
              <Chip key={i}>{it}</Chip>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <GroupCard icon={<MapPin size={12} />} title="Locale" hasContent={hasLocale}>
          <Field label="City" value={localeParts} />
          <Field label="Timezone" value={p.locale.timezone} />
          <Field label="Language" value={p.locale.language} />
        </GroupCard>

        <GroupCard icon={<Code2 size={12} />} title="Workspace" hasContent={hasWorkspace}>
          <Field label="Mode" value={p.workspace.operating_mode} />
          <Field label="Stack" value={p.workspace.primary_stack} />
          <Field label="Automation" value={p.workspace.automation_level} />
          <Field
            label="Active since"
            value={p.workspace.active_since ? fmtDate(p.workspace.active_since) : null}
          />
        </GroupCard>

        <GroupCard
          icon={<SlidersHorizontal size={12} />}
          title="Preferences"
          hasContent={hasPrefs}
        >
          <Field label="Answer language" value={p.preferences.response_language} />
          <Field label="Units" value={p.preferences.units} />
          <Field label="Privacy" value={p.preferences.privacy_level} />
        </GroupCard>

        <GroupCard
          icon={<CalendarDays size={12} />}
          title="Account"
          hasContent={!!(p.joined_at || p.birth_year || p.gender)}
        >
          <Field label="Joined" value={p.joined_at ? fmtDate(p.joined_at) : null} />
          <Field label="Birth year" value={p.birth_year} />
          <Field label="Gender" value={p.gender ? coreLabel(p.gender, null) : null} />
        </GroupCard>
      </div>

      </div>
    </div>
  );
}

/* =================================================================== FORM (edit/create) */

const FIELD =
  "w-full rounded-sm border border-border bg-background px-2.5 py-1.5 text-sm text-foreground " +
  "outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring placeholder:text-muted-foreground";

interface FormState {
  user_id: string; // create only
  display_name: string;
  occupation: string;
  bio: string;
  gender: string;
  birth_year: string;
  industry: string;
  industry_other: string;
  role: string;
  role_other: string;
  level: string;
  city: string;
  country: string;
  timezone: string;
  language: string;
  response_language: string;
  units: string;
  privacy_level: string;
  interests: string[];
  workspace_mode: string;
  workspace_stack: string;
  workspace_automation: string;
  workspace_since: string;
}

/** Seed a form from a profile (or blanks for create). Read-only fields are dropped. */
function toForm(p: UserProfile | null): FormState {
  return {
    user_id: "",
    display_name: p?.display_name ?? "",
    occupation: p?.occupation ?? "",
    bio: p?.bio ?? "",
    gender: p?.gender ?? "",
    birth_year: p?.birth_year != null ? String(p.birth_year) : "",
    industry: p?.industry ?? "tech",
    industry_other: p?.industry_other ?? "",
    role: p?.role ?? "engineering",
    role_other: p?.role_other ?? "",
    level: p?.level ?? "mid",
    city: p?.locale.city ?? "",
    country: p?.locale.country ?? "",
    timezone: p?.locale.timezone ?? "",
    language: p?.locale.language ?? "zh-CN",
    response_language: p?.preferences.response_language ?? "zh-CN",
    units: p?.preferences.units ?? "metric",
    privacy_level: p?.preferences.privacy_level ?? "standard",
    interests: p?.interests ?? [],
    workspace_mode: p?.workspace.operating_mode ?? "opc",
    workspace_stack: p?.workspace.primary_stack ?? "",
    workspace_automation: p?.workspace.automation_level ?? "agentic",
    workspace_since: p?.workspace.active_since ?? "",
  };
}

/** Build the PUT patch from the form (only the editable subset). */
function toPatch(f: FormState): api.UserProfilePatch {
  return {
    display_name: f.display_name.trim(),
    gender: f.gender.trim() || null,
    birth_year: f.birth_year.trim() ? Number(f.birth_year) : null,
    industry: f.industry,
    industry_other: f.industry === "other" ? f.industry_other.trim() || null : null,
    role: f.role,
    role_other: f.role === "other" ? f.role_other.trim() || null : null,
    level: f.level,
    occupation: f.occupation.trim(),
    bio: f.bio.trim(),
    interests: f.interests,
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

/* -------------------------------------------------------------- field primitives */

function Labeled({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-[length:var(--text-2xs)] uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[length:var(--text-2xs)] leading-4 text-muted-foreground">{hint}</span>}
    </label>
  );
}

function SelectField({
  value,
  onChange,
  options,
  labelFor = titleCase,
}: {
  value: string;
  onChange: (v: string) => void;
  options: readonly string[];
  labelFor?: (v: string) => string;
}) {
  // Keep the current value selectable even if it is outside the known domain.
  const opts = options.includes(value) ? options : [value, ...options];
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={FIELD + " appearance-none"}>
      {opts.map((o) => (
        <option key={o} value={o}>
          {labelFor(o)}
        </option>
      ))}
    </select>
  );
}

function InterestsEditor({
  value,
  onChange,
}: {
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  function add() {
    const t = draft.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setDraft("");
  }
  return (
    <div>
      {value.length > 0 && (
        <div className="mb-1.5 flex flex-wrap gap-1.5">
          {value.map((it) => (
            <span
              key={it}
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-2 py-[2px] text-[length:var(--text-2xs)] text-foreground"
            >
              {it}
              <button
                type="button"
                aria-label={`删除 ${it}`}
                onClick={() => onChange(value.filter((x) => x !== it))}
                className="text-muted-foreground outline-none hover:text-foreground focus-visible:text-foreground"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="添加兴趣，回车确认…"
          className={FIELD}
        />
        <Button type="button" variant="outline" size="sm" onClick={add} aria-label="添加兴趣">
          <Plus size={13} />
        </Button>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------------- the form */

function ProfileForm({
  mode,
  seed,
  uid,
  onSaved,
  onCancel,
}: {
  mode: "edit" | "create";
  seed: UserProfile | null;
  uid?: string;
  onSaved: (profile: UserProfile, uid: string) => void | Promise<void>;
  onCancel?: () => void;
}) {
  const [form, setForm] = useState<FormState>(() => toForm(seed));
  const [saving, setSaving] = useState(false);
  const [filling, setFilling] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiSentence, setAiSentence] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const targetId = mode === "create" ? form.user_id.trim() : (uid ?? "");

  /** 🎲 random-fill: GET a synthesized profile for the id (or a random one) and prefill. */
  async function randomFill() {
    setErr(null);
    setFilling(true);
    try {
      const id =
        form.user_id.trim() && USER_ID_RE.test(form.user_id.trim())
          ? form.user_id.trim()
          : `u-${Math.random().toString(36).slice(2, 8)}`;
      const p = await api.getUserProfile(id);
      setForm((f) => ({ ...toForm(p), user_id: f.user_id.trim() || id }));
    } catch (e) {
      setErr(`随机填充失败：${(e as Error).message}`);
    } finally {
      setFilling(false);
    }
  }

  /** ✨ AI 生成人设: expand one sentence into a full profile draft, then prefill. */
  async function generateFill() {
    const sentence = aiSentence.trim();
    if (!sentence) return;
    setErr(null);
    setGenerating(true);
    try {
      const p = await api.generateProfile(sentence, form.user_id.trim() || undefined);
      // Reuse toForm exactly like randomFill; keep any id the user already typed,
      // else adopt the persona-derived id the service put on the draft.
      setForm((f) => ({ ...toForm(p), user_id: f.user_id.trim() || p.user_id }));
      // Form is filled — collapse the optional AI entry back to its compact state.
      setAiOpen(false);
      setAiSentence("");
    } catch (e) {
      setErr(`AI 生成失败：${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  }

  async function save() {
    setErr(null);
    if (!form.display_name.trim()) {
      setErr("显示名称不能为空");
      return;
    }
    if (mode === "create") {
      if (!targetId) {
        setErr("请输入 user_id");
        return;
      }
      if (!USER_ID_RE.test(targetId)) {
        setErr("user_id 仅允许字母、数字与 . _ : -");
        return;
      }
    }
    if (form.birth_year.trim() && !Number.isFinite(Number(form.birth_year))) {
      setErr("出生年份需为数字");
      return;
    }
    setSaving(true);
    try {
      const saved = await api.putUserProfile(targetId, toPatch(form));
      await onSaved(saved, targetId);
    } catch (e) {
      setErr(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="px-5 py-5">
      <ActionBar
        label={
          <Eyebrow>{mode === "create" ? "新建用户 · New profile" : "编辑画像 · Edit profile"}</Eyebrow>
        }
      >
        <Button variant="primary" size="sm" onClick={save} disabled={saving}>
          {saving && <Loader2 size={13} className="animate-spin" />}
          {mode === "create" ? "创建并切换" : "保存"}
        </Button>
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
            取消
          </Button>
        )}
      </ActionBar>

      <div className="space-y-5">
        {/* Create mode leads with a QUICK-DRAFT zone — the two prefill helpers
            (mock 随机填充 + AI 生成) grouped as peers and kept OUT of the form fields.
            Everything below (starting with user_id) is the actual form. */}
        {mode === "create" && (
          <div className="rounded-md border border-border bg-secondary/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <Eyebrow>快速起草 · Quick draft</Eyebrow>
              <span className="text-[length:var(--text-2xs)] uppercase tracking-wide text-muted-foreground/70">
                可选
              </span>
            </div>
            <p className="mt-1 text-[length:var(--text-2xs)] leading-4 text-muted-foreground">
              选一种方式一键预填整份画像，或直接在下方手动填写。
            </p>
            {!aiOpen ? (
              <div className="mt-2.5 flex flex-wrap gap-2">
                <Button type="button" variant="outline" size="sm" onClick={randomFill} disabled={filling}>
                  {filling ? <Loader2 size={13} className="animate-spin" /> : <Dice5 size={13} />} 随机填充
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={() => setAiOpen(true)}>
                  <Sparkles size={13} className="text-[var(--color-accent)]" /> 用一句话让 AI 生成
                </Button>
              </div>
            ) : (
              <div className="mt-2.5 flex items-center gap-2">
                <input
                  autoFocus
                  value={aiSentence}
                  onChange={(e) => setAiSentence(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void generateFill();
                    } else if (e.key === "Escape") {
                      e.preventDefault();
                      setAiOpen(false);
                      setAiSentence("");
                    }
                  }}
                  placeholder="一句话描述，如「深圳做 AI Agent 的大数据后端」"
                  aria-label="AI 生成人设描述"
                  className={FIELD}
                />
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={generateFill}
                  disabled={generating || !aiSentence.trim()}
                  className="flex-none"
                >
                  {generating ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Sparkles size={13} className="text-[var(--color-accent)]" />
                  )}{" "}
                  生成
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="收起 AI 生成"
                  onClick={() => {
                    setAiOpen(false);
                    setAiSentence("");
                  }}
                  disabled={generating}
                  className="flex-none"
                >
                  <X size={14} />
                </Button>
              </div>
            )}
          </div>
        )}

        {/* user_id — a plain form field (create only), no button glued to it. */}
        {mode === "create" && (
          <Labeled label="user_id" hint="外部唯一键，允许字母、数字与 . _ : -">
            <input
              value={form.user_id}
              onChange={(e) => set("user_id", e.target.value)}
              placeholder="u-opc-…"
              aria-label="user_id"
              className={FIELD + " font-mono"}
            />
          </Labeled>
        )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="显示名称 · Display name">
          <input
            value={form.display_name}
            onChange={(e) => set("display_name", e.target.value)}
            placeholder="林知远"
            className={FIELD}
          />
        </Labeled>
        <Labeled label="职业 · Occupation">
          <input
            value={form.occupation}
            onChange={(e) => set("occupation", e.target.value)}
            placeholder="AI-Native 独立开发者"
            className={FIELD}
          />
        </Labeled>
      </div>

      <Labeled label="简介 · Bio">
        <textarea
          value={form.bio}
          onChange={(e) => set("bio", e.target.value)}
          rows={3}
          placeholder="一句话介绍…"
          className={FIELD + " resize-y"}
        />
      </Labeled>

      {/* answer-style core */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="行业 · Industry">
          <SelectField value={form.industry} onChange={(v) => set("industry", v)} options={INDUSTRIES} />
        </Labeled>
        {form.industry === "other" ? (
          <Labeled label="行业（其它） · Industry other">
            <input
              value={form.industry_other}
              onChange={(e) => set("industry_other", e.target.value)}
              placeholder="自定义行业"
              className={FIELD}
            />
          </Labeled>
        ) : (
          <div className="hidden sm:block" />
        )}
        <Labeled label="角色 · Role">
          <SelectField value={form.role} onChange={(v) => set("role", v)} options={ROLES} />
        </Labeled>
        {form.role === "other" ? (
          <Labeled label="角色（其它） · Role other">
            <input
              value={form.role_other}
              onChange={(e) => set("role_other", e.target.value)}
              placeholder="自定义角色"
              className={FIELD}
            />
          </Labeled>
        ) : (
          <div className="hidden sm:block" />
        )}
      </div>

      <Labeled label="资历 · Level（决定 AI 回答风格）" hint={LEVEL_STYLES[form.level]}>
        <SelectField
          value={form.level}
          onChange={(v) => set("level", v)}
          options={LEVELS}
          labelFor={(v) =>
            `${LEVELS.indexOf(v as (typeof LEVELS)[number]) + 1}. ${coreLabel(v, null)}`
          }
        />
      </Labeled>

      {/* demographics */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="性别 · Gender">
          <input
            value={form.gender}
            onChange={(e) => set("gender", e.target.value)}
            placeholder="（可选）"
            className={FIELD}
          />
        </Labeled>
        <Labeled label="出生年份 · Birth year">
          <input
            value={form.birth_year}
            onChange={(e) => set("birth_year", e.target.value)}
            inputMode="numeric"
            placeholder="1990"
            className={FIELD}
          />
        </Labeled>
      </div>

      {/* locale */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="城市 · City">
          <input value={form.city} onChange={(e) => set("city", e.target.value)} className={FIELD} />
        </Labeled>
        <Labeled label="国家 · Country">
          <input
            value={form.country}
            onChange={(e) => set("country", e.target.value)}
            className={FIELD}
          />
        </Labeled>
        <Labeled label="时区 · Timezone">
          <input
            value={form.timezone}
            onChange={(e) => set("timezone", e.target.value)}
            placeholder="Asia/Shanghai"
            className={FIELD}
          />
        </Labeled>
        <Labeled label="界面语言 · Language">
          <SelectField
            value={form.language}
            onChange={(v) => set("language", v)}
            options={LANGUAGES}
            labelFor={(v) => v}
          />
        </Labeled>
      </div>

      {/* preferences */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Labeled label="回答语言 · Answer">
          <SelectField
            value={form.response_language}
            onChange={(v) => set("response_language", v)}
            options={LANGUAGES}
            labelFor={(v) => v}
          />
        </Labeled>
        <Labeled label="单位 · Units">
          <SelectField value={form.units} onChange={(v) => set("units", v)} options={UNITS} />
        </Labeled>
        <Labeled label="隐私 · Privacy">
          <SelectField
            value={form.privacy_level}
            onChange={(v) => set("privacy_level", v)}
            options={PRIVACY}
          />
        </Labeled>
      </div>

      {/* interests */}
      <Labeled label="兴趣 · Interests">
        <InterestsEditor value={form.interests} onChange={(v) => set("interests", v)} />
      </Labeled>

      {/* workspace */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Labeled label="工作模式 · Mode">
          <SelectField
            value={form.workspace_mode}
            onChange={(v) => set("workspace_mode", v)}
            options={["opc", "independent", "team"]}
          />
        </Labeled>
        <Labeled label="主要技术栈 · Stack">
          <input
            value={form.workspace_stack}
            onChange={(e) => set("workspace_stack", e.target.value)}
            placeholder="TypeScript + Python"
            className={FIELD}
          />
        </Labeled>
        <Labeled label="自动化 · Automation">
          <SelectField
            value={form.workspace_automation}
            onChange={(v) => set("workspace_automation", v)}
            options={["manual", "assisted", "agentic"]}
          />
        </Labeled>
        <Labeled label="启用日期 · Active since">
          <input
            value={form.workspace_since}
            onChange={(e) => set("workspace_since", e.target.value)}
            placeholder="2024-05-01"
            className={FIELD}
          />
        </Labeled>
      </div>

      {err && (
        <div className="rounded-sm border border-border bg-card px-2.5 py-1.5 text-[length:var(--text-xs)] text-[var(--color-danger)]">
          {err}
        </div>
      )}

      </div>
    </div>
  );
}

/* ================================================================= ProfileCard API */

export interface ProfileCardProps {
  mode: "view" | "edit" | "create";
  /** Seed profile for view/edit; may be null for a blank create. */
  profile: UserProfile | null;
  /** Known user_id for view/edit (shown in the header / used as PUT target). */
  uid?: string;
  /** view mode: buttons for the sticky action bar (e.g. 切换到此用户 / 编辑). */
  actions?: ReactNode;
  /** edit/create: called with the saved profile + resolved uid after a successful PUT. */
  onSaved?: (profile: UserProfile, uid: string) => void | Promise<void>;
  /** edit/create: cancel — discard and return (parent flips back to view / closes). */
  onCancel?: () => void;
}

/**
 * Render a user picture read-only, editable, or as a blank create form. The same
 * component backs the Profile tab and the switcher modal's right pane.
 */
export function ProfileCard({ mode, profile, uid, actions, onSaved, onCancel }: ProfileCardProps) {
  // Reset form state whenever we (re)enter a form for a different seed/user.
  const formKey = useMemo(
    () => `${mode}:${uid ?? ""}:${profile?.user_id ?? ""}`,
    [mode, uid, profile?.user_id],
  );

  if (mode === "view") {
    if (!profile) return null;
    return <ProfileReadOnly p={profile} uid={uid ?? profile.user_id} actions={actions} />;
  }
  return (
    <ProfileForm
      key={formKey}
      mode={mode}
      seed={profile}
      uid={uid}
      onSaved={onSaved ?? (() => {})}
      onCancel={onCancel}
    />
  );
}

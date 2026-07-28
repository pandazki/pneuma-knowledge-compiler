import { useEffect, useState, type ReactNode } from "react";
import { Pencil, Sparkles, UserRound } from "lucide-react";
import { useApp } from "@/lib/store";
import {
  generateProfile,
  getUserProfile,
  putUserProfile,
  type UserProfilePatch,
} from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { UserProfile } from "@/lib/types";
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

/* ------------------------------------------- 取值域（镜像后端 user.py 的枚举） */

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
/** 6 档资历，低 → 高；驱动 AI 回答风格。 */
const LEVELS = ["entry", "junior", "mid", "senior", "staff", "principal"] as const;
/** 每档资历对应的回答风格指令（镜像后端 LEVEL_STYLES）。 */
const LEVEL_STYLES: Record<string, string> = {
  entry: "用定义和逐步拆解解释问题，不预设背景知识。",
  junior: "给出清晰说明、具体例子和必要的下一步指引。",
  mid: "平衡结论、理由与可执行细节。",
  senior: "保持简洁，优先呈现取舍、影响和决策边界。",
  staff: "突出系统影响、跨域约束和边界情况。",
  principal: "默认深厚专业背景，只保留决策所需的高信号信息。",
};
const LANGUAGES = ["zh-CN", "en-US", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES"] as const;
const UNITS = ["metric", "imperial"] as const;
const PRIVACY = ["standard", "strict"] as const;
const WORKSPACE_MODES = ["opc", "independent", "team"] as const;
const AUTOMATION_LEVELS = ["manual", "assisted", "agentic"] as const;

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
};

/** industry/role 展示：枚举为 other 时用自由文本 *_other。 */
function coreLabel(value: string, other: string | null): string {
  if (value === "other") return other?.trim() || CORE_LABELS.other;
  return CORE_LABELS[value] ?? value;
}

/** Select 选项：当前值在取值域外时也保留为可选项（不丢数据）。 */
function enumOptions(domain: readonly string[], current: string) {
  const values = domain.includes(current) ? [...domain] : [current, ...domain];
  return values.map((v) => ({ value: v, label: CORE_LABELS[v] ?? v }));
}

const rawOptions = (domain: readonly string[], current: string) => {
  const values = domain.includes(current) ? [...domain] : [current, ...domain];
  return values.map((v) => ({ value: v, label: v }));
};

/* ------------------------------------------------------------- 编辑表单 */

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
  /** 逗号分隔，提交时拆回 string[]。 */
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

/** 以画像（或 AI 草稿）播种表单；只读字段（avatar/level_style/joined_at/source）不进表单。 */
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
    workspace_mode: p.workspace.operating_mode ?? "opc",
    workspace_stack: p.workspace.primary_stack ?? "",
    workspace_automation: p.workspace.automation_level ?? "agentic",
    workspace_since: p.workspace.active_since ?? "",
  };
}

/** 表单 → PUT /profile 的 patch（仅可编辑子集）。 */
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
  /** 播种来源：当前画像或 AI 草稿。 */
  seed: UserProfile;
  disabled?: boolean;
  onSaved: (saved: UserProfile) => void;
  onCancel: () => void;
}

function ProfileForm({ uid, seed, disabled, onSaved, onCancel }: ProfileFormProps) {
  const [form, setForm] = useState<FormState>(() => toForm(seed));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    setErr(null);
    if (!form.display_name.trim()) {
      setErr("显示名称不能为空。");
      return;
    }
    setSaving(true);
    try {
      const saved = await putUserProfile(uid, toPatch(form));
      onSaved(saved);
    } catch (e) {
      setErr(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <FormGroup label="基本">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="显示名称"
            value={form.display_name}
            onChange={(e) => set("display_name", e.target.value)}
            disabled={disabled}
            required
          />
          <TextField
            label="职业"
            value={form.occupation}
            onChange={(e) => set("occupation", e.target.value)}
            disabled={disabled}
            placeholder="AI-Native 独立开发者"
          />
          <TextField
            label="性别（可选）"
            value={form.gender}
            onChange={(e) => set("gender", e.target.value)}
            disabled={disabled}
          />
          <NumberField
            label="出生年份（可选）"
            value={form.birth_year}
            onChange={(v) => set("birth_year", v)}
            min={1900}
            max={2100}
            disabled={disabled}
          />
        </div>
        <TextArea
          label="简介"
          value={form.bio}
          onChange={(e) => set("bio", e.target.value)}
          disabled={disabled}
          autoRows
          maxRows={6}
          placeholder="一句话介绍…"
        />
        <TextField
          label="兴趣"
          value={form.interestsText}
          onChange={(e) => set("interestsText", e.target.value)}
          disabled={disabled}
          hint="多个兴趣用逗号分隔"
          placeholder="开源, 编译器, 徒步"
        />
      </FormGroup>

      <FormGroup label="回答风格（industry / role / level）">
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="行业"
            value={form.industry}
            onChange={(v) => set("industry", v)}
            options={enumOptions(INDUSTRIES, form.industry)}
            disabled={disabled}
          />
          {form.industry === "other" && (
            <TextField
              label="行业（其它）"
              value={form.industry_other}
              onChange={(e) => set("industry_other", e.target.value)}
              disabled={disabled}
              placeholder="自定义行业"
            />
          )}
          <Select
            label="角色"
            value={form.role}
            onChange={(v) => set("role", v)}
            options={enumOptions(ROLES, form.role)}
            disabled={disabled}
          />
          {form.role === "other" && (
            <TextField
              label="角色（其它）"
              value={form.role_other}
              onChange={(e) => set("role_other", e.target.value)}
              disabled={disabled}
              placeholder="自定义角色"
            />
          )}
        </div>
        <Select
          label="资历（决定 AI 回答风格）"
          value={form.level}
          onChange={(v) => set("level", v)}
          options={(LEVELS.includes(form.level as (typeof LEVELS)[number])
            ? [...LEVELS]
            : [form.level, ...LEVELS]
          ).map((l) => ({
            value: l,
            label: `${(LEVELS as readonly string[]).indexOf(l) + 1 || "?"} · ${CORE_LABELS[l] ?? l}`,
          }))}
          hint={LEVEL_STYLES[form.level]}
          disabled={disabled}
        />
      </FormGroup>

      <FormGroup label="地区与偏好">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="城市"
            value={form.city}
            onChange={(e) => set("city", e.target.value)}
            disabled={disabled}
          />
          <TextField
            label="国家"
            value={form.country}
            onChange={(e) => set("country", e.target.value)}
            disabled={disabled}
          />
          <TextField
            label="时区"
            value={form.timezone}
            onChange={(e) => set("timezone", e.target.value)}
            disabled={disabled}
            placeholder="Asia/Shanghai"
          />
          <Select
            label="界面语言"
            value={form.language}
            onChange={(v) => set("language", v)}
            options={rawOptions(LANGUAGES, form.language)}
            disabled={disabled}
          />
          <Select
            label="回答语言"
            value={form.response_language}
            onChange={(v) => set("response_language", v)}
            options={rawOptions(LANGUAGES, form.response_language)}
            disabled={disabled}
          />
          <Select
            label="单位"
            value={form.units}
            onChange={(v) => set("units", v)}
            options={rawOptions(UNITS, form.units)}
            disabled={disabled}
          />
          <Select
            label="隐私"
            value={form.privacy_level}
            onChange={(v) => set("privacy_level", v)}
            options={rawOptions(PRIVACY, form.privacy_level)}
            disabled={disabled}
          />
        </div>
      </FormGroup>

      <FormGroup label="工作台">
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="工作模式"
            value={form.workspace_mode}
            onChange={(v) => set("workspace_mode", v)}
            options={rawOptions(WORKSPACE_MODES, form.workspace_mode)}
            disabled={disabled}
          />
          <TextField
            label="主要技术栈"
            value={form.workspace_stack}
            onChange={(e) => set("workspace_stack", e.target.value)}
            disabled={disabled}
            placeholder="TypeScript + Python"
          />
          <Select
            label="自动化程度"
            value={form.workspace_automation}
            onChange={(v) => set("workspace_automation", v)}
            options={rawOptions(AUTOMATION_LEVELS, form.workspace_automation)}
            disabled={disabled}
          />
          <TextField
            label="启用日期"
            value={form.workspace_since}
            onChange={(e) => set("workspace_since", e.target.value)}
            disabled={disabled}
            placeholder="2024-05-01"
          />
        </div>
      </FormGroup>

      {err && (
        <Callout tone="danger" title="无法保存">
          {err}
        </Callout>
      )}

      <div className="flex items-center gap-2 border-t border-line pt-4">
        <Button variant="primary" loading={saving} disabled={disabled} onClick={() => void save()}>
          保存画像
        </Button>
        <Button variant="ghost" disabled={saving} onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- 只读定义表 */

function joinParts(parts: (string | null | undefined)[]): string | null {
  const s = parts.filter((p) => p && p.trim()).join(" · ");
  return s || null;
}

function ProfileFields({ p }: { p: UserProfile }) {
  const levelIdx = (LEVELS as readonly string[]).indexOf(p.level);
  const dash = <span className="text-ink-3">—</span>;
  return (
    <DefinitionList
      termClassName="sm:w-32"
      items={[
        { term: "user_id", definition: <Mono>{p.user_id}</Mono> },
        { term: "行业", definition: coreLabel(p.industry, p.industry_other) },
        { term: "角色", definition: coreLabel(p.role, p.role_other) },
        {
          term: "资历",
          definition: (
            <>
              {coreLabel(p.level, null)}
              {levelIdx >= 0 && (
                <Mono className="ml-2 text-12 text-ink-3">
                  {levelIdx + 1}/{LEVELS.length}
                </Mono>
              )}
            </>
          ),
        },
        { term: "回答风格", definition: p.level_style || dash },
        { term: "职业", definition: p.occupation || dash },
        { term: "简介", definition: p.bio || dash },
        {
          term: "兴趣",
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
          term: "地区",
          definition:
            joinParts([
              joinParts([p.locale.city, p.locale.country]),
              p.locale.timezone,
              p.locale.language,
            ]) ?? dash,
        },
        {
          term: "工作台",
          definition:
            joinParts([
              p.workspace.operating_mode ? `模式 ${p.workspace.operating_mode}` : null,
              p.workspace.primary_stack ? `技术栈 ${p.workspace.primary_stack}` : null,
              p.workspace.automation_level ? `自动化 ${p.workspace.automation_level}` : null,
              p.workspace.active_since ? `自 ${p.workspace.active_since}` : null,
            ]) ?? dash,
        },
        {
          term: "偏好",
          definition:
            joinParts([
              p.preferences.response_language
                ? `回答语言 ${p.preferences.response_language}`
                : null,
              p.preferences.units ? `单位 ${p.preferences.units}` : null,
              p.preferences.privacy_level ? `隐私 ${p.preferences.privacy_level}` : null,
            ]) ?? dash,
        },
        { term: "加入时间", definition: p.joined_at ? fmtDate(p.joined_at) : dash },
      ]}
    />
  );
}

/* ------------------------------------------------------------------- 视图 */

export default function ProfileView() {
  const currentUser = useApp((s) => s.currentUser);
  const profile = useApp((s) => s.currentProfile);
  const setProfile = useApp((s) => s.setProfile);
  /** 历史快照只读态：所有 mutation 控件 disabled（DESIGN.md §4.3）。 */
  const readOnly = useApp((s) => s.currentSnapshot != null);

  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState(false);
  /** AI 生成的草稿：只预填表单，不落库；nonce 变化触发表单重播种。 */
  const [draft, setDraft] = useState<{ profile: UserProfile; nonce: number } | null>(null);

  const [sentence, setSentence] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  // 自己发起加载以获得真实的 error 态（store.loadProfile 吞错降级，无法驱动 ErrorState）；
  // 成功后写回 store，store.currentProfile 仍是唯一展示来源。
  useEffect(() => {
    setEditing(false);
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
  }, [currentUser, attempt, setProfile]);

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
      setGenError(`生成失败：${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  }

  const aiSection = (
    <section>
      <SectionRule no={2} title="AI 生成画像" className="mb-3" />
      <p className="mb-3 max-w-measure text-13 text-ink-2">
        一句话描述一个人设，AI 展开为完整画像草稿并预填编辑表单——不落库，确认保存后才写入。
      </p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <TextField
          wrapperClassName="flex-1"
          aria-label="一句话描述人设"
          value={sentence}
          onChange={(e) => setSentence(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void generate();
            }
          }}
          disabled={readOnly || generating}
          placeholder="如「杭州做开源数据库的独立开发者」"
        />
        <Button
          variant="primary"
          loading={generating}
          disabled={readOnly || !sentence.trim()}
          onClick={() => void generate()}
        >
          <Sparkles size={14} aria-hidden />
          生成草稿
        </Button>
      </div>
      {genError && <p className="mt-2 text-12 text-danger">{genError}</p>}
    </section>
  );

  if (!currentUser) {
    return (
      <>
        <PageHeader
          title="画像 Profile"
          description="synthetic 用户档案：核心字段、编辑与 AI 生成。"
        />
        <EmptyState
          icon={UserRound}
          title="尚未选择用户"
          description="选择一个 user_id 查看其画像；任何 id 都会解析出一份合成画像。"
          action={<UserPicker />}
        />
      </>
    );
  }

  if (phase === "error") {
    return (
      <>
        <PageHeader title="画像 Profile" description="synthetic 用户档案。" />
        <ErrorState
          title="画像加载失败"
          error={loadError ?? "未知错误"}
          onRetry={() => setAttempt((a) => a + 1)}
        />
      </>
    );
  }

  if (phase === "loading" || !profile) {
    return (
      <>
        <PageHeader title="画像 Profile" description="synthetic 用户档案。" />
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
        title="画像 Profile"
        description="演示用 synthetic 人设：由服务确定性合成，不代表真实用户。"
        actions={
          !editing ? (
            <Button size="sm" disabled={readOnly} onClick={() => setEditing(true)}>
              <Pencil size={13} aria-hidden />
              编辑画像
            </Button>
          ) : undefined
        }
      />

      {/* 身份区：avatar 字标 + display_name + mono id + synthetic 档案戳 */}
      <section className="flex flex-wrap items-center gap-4">
        <span
          aria-hidden
          className="inline-flex size-14 shrink-0 items-center justify-center rounded-2 bg-active font-serif text-24 text-ink"
        >
          {profile.avatar.initial}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-serif text-24 text-ink">{profile.display_name}</h2>
            <Stamp tone="neutral">SYNTHETIC</Stamp>
          </div>
          <Mono className="text-13 text-ink-3">{profile.user_id}</Mono>
          <p className="text-12 text-ink-3">
            画像来源 <Mono>source = {profile.source}</Mono>
            （mock = 合成，user = 已编辑保存）
          </p>
        </div>
      </section>

      {editing ? (
        <>
          {draft && (
            <Callout tone="notice" title="草稿已预填">
              这是 AI 按一句话生成的草稿，尚未写入——确认「保存画像」后才落库。
            </Callout>
          )}
          <section>
            <SectionRule no={1} title="编辑画像" className="mb-4" />
            <ProfileForm
              key={draft ? `draft-${draft.nonce}` : "base"}
              uid={currentUser}
              seed={draft?.profile ?? profile}
              disabled={readOnly}
              onSaved={(saved) => {
                setProfile(currentUser, saved);
                setEditing(false);
                setDraft(null);
              }}
              onCancel={() => {
                setEditing(false);
                setDraft(null);
              }}
            />
          </section>
          {aiSection}
        </>
      ) : (
        <>
          <section>
            <SectionRule no={1} title="核心字段" className="mb-2" />
            <ProfileFields p={profile} />
          </section>
          {aiSection}
        </>
      )}
    </div>
  );
}

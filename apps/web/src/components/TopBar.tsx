import { useEffect, useMemo, useRef, useState } from "react";
import {
  Moon,
  Sun,
  ChevronDown,
  AlertTriangle,
  X,
  Check,
  Search,
  Users,
  MapPin,
  UserPlus,
  ArrowRightLeft,
  Pencil,
  Loader2,
  GitCommitHorizontal,
  CircleDot,
} from "lucide-react";
import { useApp } from "@/lib/store";
import type { UserProfile } from "@/lib/types";
import { ProfileCard } from "./ProfileCard";
import { Button, Chip } from "./ui";

/* ------------------------------------------------------------------ profile labels */

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
};

/** industry/role display: honor the free-text `*_other` when the enum is "other". */
function coreLabel(value: string, other: string | null): string {
  if (value === "other") return other?.trim() || CORE_LABELS.other;
  return CORE_LABELS[value] ?? titleCase(value);
}

/** The core onboarding trio industry / role / level as a compact " · "-joined line. */
function coreTrio(p: UserProfile): string {
  return [
    coreLabel(p.industry, p.industry_other),
    coreLabel(p.role, p.role_other),
    coreLabel(p.level, null),
  ]
    .filter(Boolean)
    .join(" · ");
}

/** locale one-liner (city · language) — only the parts that exist. */
function localeLine(p: UserProfile): string {
  return [p.locale.city, p.locale.language].filter(Boolean).join(" · ");
}

/* -------------------------------------------------------------------------- Avatar */

/** Circular identity chip — profile avatar (color + initial) with a raw-id fallback. */
function Avatar({
  profile,
  uid,
  size = 26,
}: {
  profile: UserProfile | null | undefined;
  uid: string;
  size?: number;
}) {
  const color = profile?.avatar.color ?? "var(--color-surface-muted)";
  const initial = profile?.avatar.initial ?? uid.slice(0, 1).toUpperCase() ?? "?";
  return (
    <span
      aria-hidden
      className="flex flex-none items-center justify-center rounded-full font-light text-white"
      style={{
        width: size,
        height: size,
        background: color,
        fontSize: Math.round(size * 0.42),
        color: profile ? "#fff" : "var(--color-text-secondary)",
      }}
    >
      {initial}
    </span>
  );
}

/* ------------------------------------------------------------------------ user row */

/**
 * A selectable user line — avatar + display_name + raw id (mono) + core chips.
 * `active` highlights the selected row (modal preview target); `current` marks the
 * app's active user with a check (distinct from mere selection).
 */
function UserRow({
  uid,
  profile,
  active,
  current,
  onSelect,
  compact = false,
}: {
  uid: string;
  profile: UserProfile | null | undefined;
  active?: boolean;
  current?: boolean;
  onSelect: () => void;
  compact?: boolean;
}) {
  const name = profile?.display_name ?? uid;
  return (
    <button
      type="button"
      onClick={onSelect}
      title={uid}
      aria-current={active || undefined}
      className={
        "flex w-full items-center gap-2.5 rounded-sm px-2 py-1.5 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring " +
        (active ? "bg-accent" : "")
      }
    >
      <Avatar profile={profile} uid={uid} size={compact ? 24 : 28} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-[length:var(--text-sm)] text-foreground">{name}</span>
          {current && <Check size={13} className="flex-none text-[var(--color-accent)]" />}
        </span>
        {!compact && (
          <span className="mt-0.5 block truncate font-mono text-[length:var(--text-2xs)] text-muted-foreground">
            {uid}
          </span>
        )}
        {!compact && profile && (
          <span className="mt-1 flex flex-wrap gap-1">
            <Chip>{coreLabel(profile.industry, profile.industry_other)}</Chip>
            <Chip>{coreLabel(profile.role, profile.role_other)}</Chip>
            <Chip>{coreLabel(profile.level, null)}</Chip>
          </span>
        )}
      </span>
    </button>
  );
}

/* -------------------------------------------------------------------- manage modal */

/** Right-pane state: preview/edit an existing user, or create a brand-new one. */
type RightPane = { kind: "user"; uid: string; editing: boolean } | { kind: "create" };

/**
 * The "heavy" full switcher — a two-pane manager. LEFT: search + every user
 * (GET /v1/users) with avatar/name/raw-id/core chips + a "新建用户" action; clicking a
 * row only SELECTS it (no switch). RIGHT: the selected user's ProfileCard preview
 * with explicit「切换到此用户」/「编辑」actions, or a blank create form. Only an
 * explicit switch / create changes the active user + closes; cancel / Esc / backdrop
 * close WITHOUT changing it.
 */
function ManageModal({ onClose }: { onClose: () => void }) {
  const { users, currentUser, profileCards, ensureCards, setUser, setProfile, setView } = useApp();
  const [query, setQuery] = useState("");
  const [pane, setPane] = useState<RightPane>(() =>
    currentUser ? { kind: "user", uid: currentUser, editing: false } : { kind: "create" },
  );
  const searchRef = useRef<HTMLInputElement>(null);

  // Always keep the active user in the list, even if the backend directory hasn't
  // seen it yet (a just-created new user only appears after its first source lands).
  const options = useMemo(
    () => (currentUser && !users.includes(currentUser) ? [currentUser, ...users] : users),
    [users, currentUser],
  );
  const optionsKey = options.join(" ");

  // Parallel, best-effort backfill of full profiles for every row (avatar + chips).
  useEffect(() => {
    if (optionsKey) ensureCards(optionsKey.split(" "));
  }, [optionsKey, ensureCards]);

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  // Esc closes the modal without changing the current user (cancel semantics).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = query.trim().toLowerCase();
  const filtered = options.filter((uid) => {
    if (!q) return true;
    const name = profileCards[uid]?.display_name ?? "";
    return uid.toLowerCase().includes(q) || name.toLowerCase().includes(q);
  });

  const selectedUid = pane.kind === "user" ? pane.uid : null;

  /** Commit a switch to `uid`: records MRU + reloads profile/snapshots/dataset, then closes. */
  function switchTo(uid: string) {
    setUser(uid);
    onClose();
  }

  /** A create just persisted `uid` — seed caches, switch, land on Profile, close. */
  function afterCreate(profile: UserProfile, uid: string) {
    setProfile(uid, profile); // seed so the Profile view/top-bar don't flash empty
    setUser(uid); // records MRU + reloads snapshots/dataset for the new id
    setView("profile"); // land on the picture we just filled (NOT Ingest)
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[6vh]"
      role="dialog"
      aria-modal="true"
      aria-label="切换 / 管理用户"
    >
      {/* backdrop — click = cancel */}
      <div
        className="absolute inset-0 bg-[var(--color-scrim,rgba(0,0,0,0.45))]"
        onClick={onClose}
        aria-hidden
      />
      <div
        className="relative flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-sm border border-border bg-popover text-popover-foreground"
        style={{ boxShadow: "var(--shadow-overlay)" }}
      >
        {/* header */}
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-1.5 text-[length:var(--text-sm)] font-medium text-foreground">
            <Users size={14} /> 切换 / 管理用户
          </div>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="inline-flex items-center rounded-sm p-1 text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X size={15} />
          </button>
        </div>

        {/* body: left list | right preview/edit/create */}
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          {/* LEFT — search + list + 新建用户 */}
          <div className="flex min-h-0 shrink-0 flex-col border-b border-border md:w-72 md:border-b-0 md:border-r">
            <div className="border-b border-border px-3 py-2.5">
              <div className="relative">
                <Search
                  size={13}
                  className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
                />
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="按名称或 user_id 搜索…"
                  aria-label="搜索用户"
                  className="h-8 w-full rounded-sm border border-border bg-background pl-7 pr-2 text-xs text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring placeholder:text-muted-foreground"
                />
              </div>
            </div>

            <div className="min-h-0 max-h-[28vh] flex-1 overflow-y-auto px-2 py-2 md:max-h-none">
              {filtered.length === 0 ? (
                <div className="px-2 py-6 text-center text-xs text-muted-foreground">
                  {options.length === 0 ? "暂无用户" : "无匹配用户"}
                </div>
              ) : (
                <div className="flex flex-col gap-0.5">
                  {filtered.map((uid) => (
                    <UserRow
                      key={uid}
                      uid={uid}
                      profile={profileCards[uid]}
                      active={uid === selectedUid}
                      current={uid === currentUser}
                      onSelect={() => setPane({ kind: "user", uid, editing: false })}
                    />
                  ))}
                </div>
              )}
            </div>

            <div className="border-t border-border px-3 py-2.5">
              <Button
                variant={pane.kind === "create" ? "primary" : "outline"}
                size="sm"
                className="w-full"
                onClick={() => setPane({ kind: "create" })}
              >
                <UserPlus size={13} /> 新建用户
              </Button>
            </div>
          </div>

          {/* RIGHT — preview / edit / create */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            {pane.kind === "create" ? (
              <ProfileCard
                mode="create"
                profile={null}
                onSaved={afterCreate}
                onCancel={() =>
                  setPane(
                    currentUser
                      ? { kind: "user", uid: currentUser, editing: false }
                      : { kind: "create" },
                  )
                }
              />
            ) : profileCards[pane.uid] ? (
              pane.editing ? (
                <ProfileCard
                  mode="edit"
                  profile={profileCards[pane.uid]}
                  uid={pane.uid}
                  onSaved={(profile, uid) => {
                    setProfile(uid, profile);
                    setPane({ kind: "user", uid, editing: false });
                  }}
                  onCancel={() => setPane({ kind: "user", uid: pane.uid, editing: false })}
                />
              ) : (
                <ProfileCard
                  mode="view"
                  profile={profileCards[pane.uid]}
                  uid={pane.uid}
                  actions={
                    <>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => switchTo(pane.uid)}
                        disabled={pane.uid === currentUser}
                      >
                        <ArrowRightLeft size={13} />
                        {pane.uid === currentUser ? "当前用户" : "切换到此用户"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPane({ kind: "user", uid: pane.uid, editing: true })}
                      >
                        <Pencil size={13} /> 编辑
                      </Button>
                    </>
                  }
                />
              )
            ) : (
              <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> 加载画像…
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- user switcher */

/**
 * Top-bar user switcher: a custom trigger (avatar + name + core micro-badge) that
 * opens a lightweight panel (current-user summary + up to 3 recent quick-switches +
 * a "manage" button), which in turn opens the heavy ManageModal.
 */
function UserSwitcher() {
  const { currentUser, currentProfile, profileCards, recentUsers, ensureCards, setUser } = useApp();
  const [panelOpen, setPanelOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Up to 3 most-recent OTHER users for the quick-switch list.
  const recent = useMemo(
    () => recentUsers.filter((uid) => uid !== currentUser).slice(0, 3),
    [recentUsers, currentUser],
  );
  const recentKey = recent.join(" ");

  // Backfill recent rows' avatars/names when the panel is open (parallel, best-effort).
  useEffect(() => {
    if (panelOpen && recentKey) ensureCards(recentKey.split(" "));
  }, [panelOpen, recentKey, ensureCards]);

  // Panel: click-outside + Esc close.
  useEffect(() => {
    if (!panelOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setPanelOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPanelOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [panelOpen]);

  function quickSwitch(uid: string) {
    setUser(uid);
    setPanelOpen(false);
  }

  const trigger = currentProfile;
  const trioLine = trigger ? coreTrio(trigger) : null;

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        aria-label="切换用户"
        aria-haspopup="menu"
        aria-expanded={panelOpen}
        title={currentUser ?? "无用户"}
        disabled={!currentUser}
        onClick={() => setPanelOpen((o) => !o)}
        className="flex h-9 max-w-[15rem] items-center gap-2 rounded-sm border border-border bg-card px-1.5 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      >
        <Avatar profile={trigger} uid={currentUser ?? "?"} size={24} />
        <span className="hidden min-w-0 flex-col leading-tight md:flex">
          <span className="truncate text-xs text-foreground">
            {trigger?.display_name ?? currentUser ?? "无用户"}
          </span>
          {trioLine && (
            <span className="truncate text-[length:var(--text-2xs)] text-muted-foreground">{trioLine}</span>
          )}
        </span>
        <ChevronDown size={13} className="flex-none text-muted-foreground" />
      </button>

      {panelOpen && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-72 rounded-sm border border-border bg-popover p-2 text-popover-foreground"
          style={{ boxShadow: "var(--shadow-overlay)" }}
        >
          {/* current-user summary */}
          {currentUser && (
            <div className="rounded-sm border border-border bg-card p-3">
              <div className="flex items-center gap-2.5">
                <Avatar profile={trigger} uid={currentUser} size={34} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[length:var(--text-sm)] text-foreground">
                    {trigger?.display_name ?? currentUser}
                  </div>
                  <div className="truncate font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                    {currentUser}
                  </div>
                </div>
              </div>
              {trigger && (
                <>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <Chip>{coreLabel(trigger.industry, trigger.industry_other)}</Chip>
                    <Chip>{coreLabel(trigger.role, trigger.role_other)}</Chip>
                    <Chip>{coreLabel(trigger.level, null)}</Chip>
                  </div>
                  {localeLine(trigger) && (
                    <div className="mt-2 flex items-center gap-1 text-[length:var(--text-2xs)] text-muted-foreground">
                      <MapPin size={10} /> {localeLine(trigger)}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* recent quick-switch */}
          {recent.length > 0 && (
            <div className="mt-2">
              <div className="px-2 pb-1 text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
                最近
              </div>
              <div className="flex flex-col gap-0.5">
                {recent.map((uid) => (
                  <UserRow
                    key={uid}
                    uid={uid}
                    profile={profileCards[uid]}
                    onSelect={() => quickSwitch(uid)}
                    compact
                  />
                ))}
              </div>
            </div>
          )}

          {/* manage */}
          <div className="mt-2 border-t border-border pt-2">
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => {
                setModalOpen(true);
                setPanelOpen(false);
              }}
            >
              <Users size={13} /> 切换 / 管理用户
            </Button>
          </div>
        </div>
      )}

      {modalOpen && <ManageModal onClose={() => setModalOpen(false)} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- TopBar */

export function TopBar({ title }: { title: string }) {
  const {
    currentUser,
    theme,
    toggleTheme,
    usersError,
    notice,
    dismissNotice,
    snapshots,
    currentSnapshot,
    setSnapshot,
  } = useApp();

  return (
    <header className="pneuma-topbar">
      {usersError && (
        <div className="pneuma-service-alert" role="alert">
          <AlertTriangle size={12} />
          <span>知识编译服务不可达：{usersError}。请启动 API 后重试。</span>
        </div>
      )}
      {notice && (
        <div className="pneuma-service-alert" role="status">
          <span>{notice}</span>
          <button
            type="button"
            aria-label="关闭提示"
            onClick={dismissNotice}
            className="inline-flex items-center rounded-sm p-0.5 hover:bg-accent"
          >
            <X size={12} />
          </button>
        </div>
      )}
      <div className="pneuma-topbar-main">
        <div className="pneuma-view-heading">
          <span className="pneuma-view-kicker">
            <CircleDot size={11} />
            OPC KNOWLEDGE / {currentUser ?? "NO USER"}
          </span>
          <h1>{title}</h1>
        </div>

        <div className="pneuma-topbar-state">
          <div className="pneuma-compile-state" title="当前 API 已连接">
            <span className="pneuma-live-dot" />
            服务已连接
          </div>
        </div>

        <div className="pneuma-topbar-actions">
          <UserSwitcher />

          <div className="relative flex items-center gap-1.5">
            <div className="relative">
              <GitCommitHorizontal
                size={13}
                className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <ChevronDown
                size={13}
                className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <select
                aria-label="选择快照"
                title="选择快照（历史快照只读）"
                value={currentSnapshot ?? ""}
                disabled={snapshots.length === 0}
                onChange={(e) => setSnapshot(e.target.value || null)}
                className="h-8 w-[5.5rem] max-w-[10rem] appearance-none rounded-sm border border-border bg-card pl-7 pr-6 font-mono text-[length:var(--text-xs)] font-medium tracking-[-0.02em] text-foreground outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 md:w-auto"
              >
                <option value="">HEAD · 当前版本</option>
                {snapshots.map((s, i) => (
                  <option key={s.ref} value={s.ref}>
                    {i === 0 ? "HEAD · " : ""}
                    {s.ref.slice(0, 8)}
                    {s.label ? ` · ${s.label}` : ""}
                  </option>
                ))}
              </select>
            </div>
            {currentSnapshot && (
              <span className="pneuma-readonly-stamp" title="正在查看历史快照，画面只读">
                READ ONLY
              </span>
            )}
          </div>

          <Button
            variant="ghost"
            size="icon"
            aria-label="切换主题"
            title={theme === "dark" ? "切换到瓷白线路图" : "切换到午夜控制室"}
            onClick={toggleTheme}
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </Button>
        </div>
      </div>
    </header>
  );
}

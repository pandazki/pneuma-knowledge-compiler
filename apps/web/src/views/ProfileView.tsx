import { useEffect, useState } from "react";
import { UserRound, Loader2, Pencil, Sparkles, Boxes, ArrowRight } from "lucide-react";
import { useApp } from "@/lib/store";
import { Button, Chip, EmptyState, Eyebrow } from "@/components/ui";
import { ProfileCard } from "@/components/ProfileCard";
import type { UserProfile } from "@/lib/types";
import * as api from "@/lib/api";

/**
 * A compact "量身定制" strip beside the picture: how many packs the owner's effective
 * skill composes and where they came from (matrix / derived / evolved), with a jump to the
 * Evolve view for the full skill card + schema-evolve review. Best-effort — a failed load
 * just hides the strip (the profile itself never depends on it).
 */
function SkillComboCard({ userId }: { userId: string }) {
  const setView = useApp((s) => s.setView);
  const [skill, setSkill] = useState<api.SkillInfo | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    setState("loading");
    api
      .getSkillInfo(userId)
      .then((s) => {
        if (!live) return;
        setSkill(s);
        setState("ready");
      })
      .catch(() => {
        if (live) setState("error");
      });
    return () => {
      live = false;
    };
  }, [userId]);

  if (state === "error") return null;

  // origin → count, in a stable order so the matrix reads consistently.
  const ORDER = ["matrix", "derived", "evolved"] as const;
  const counts: Record<string, number> = {};
  for (const p of skill?.packs ?? []) {
    const o = p.origin ?? "other";
    counts[o] = (counts[o] ?? 0) + 1;
  }
  const others = Object.keys(counts).filter((o) => !ORDER.includes(o as (typeof ORDER)[number]));

  return (
    <div className="mb-4 rounded-sm border border-border bg-card p-4">
      <div className="flex items-center gap-1.5">
        <Sparkles size={13} className="text-[var(--color-accent)]" />
        <Eyebrow>量身定制 · 当前 skill 组合</Eyebrow>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={() => setView("evolve")}
          title="查看完整 skill 与 schema-evolve"
        >
          Evolve <ArrowRight size={13} />
        </Button>
      </div>

      {state === "loading" ? (
        <div className="mt-2 flex items-center gap-2 text-[length:var(--text-sm)] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> 加载 skill…
        </div>
      ) : skill ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="inline-flex items-center gap-1.5 text-[length:var(--text-sm)] text-foreground">
            <Boxes size={13} className="text-muted-foreground" />
            {skill.packs.length} 个 pack
          </span>
          <span className="inline-flex flex-wrap items-center gap-1.5">
            {ORDER.filter((o) => counts[o]).map((o) => (
              <Chip key={o} title={`来源 ${o}`}>
                {o} · {counts[o]}
              </Chip>
            ))}
            {others.map((o) => (
              <Chip key={o} title={`来源 ${o}`}>
                {o} · {counts[o]}
              </Chip>
            ))}
            {skill.packs.length === 0 && (
              <span className="text-[length:var(--text-xs)] text-muted-foreground">仅基座 skill，无扩展 pack</span>
            )}
          </span>
          <span className="ml-auto font-mono text-[length:var(--text-2xs)] text-muted-foreground">
            base {skill.base_version} · v{skill.version}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The Profile tab. Loads the active user's picture and renders it via the shared
 * ProfileCard — read-only by default, with an "编辑" button that flips the same card
 * into its editable form (PUT /profile). Saving refreshes the store's currentProfile
 * so the top-bar name/avatar update in lockstep.
 */
export function ProfileView() {
  const currentUser = useApp((s) => s.currentUser);
  const setProfile = useApp((s) => s.setProfile);
  const [profile, setProfileState] = useState<UserProfile | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!currentUser) {
      setProfileState(null);
      setState("ready");
      return;
    }
    let live = true;
    setState("loading");
    setEditing(false);
    api
      .getUserProfile(currentUser)
      .then((p) => {
        if (!live) return;
        setProfileState(p);
        setState("ready");
      })
      .catch((e: Error) => {
        if (!live) return;
        setError(e.message);
        setState("error");
      });
    return () => {
      live = false;
    };
  }, [currentUser]);

  if (!currentUser) {
    return (
      <EmptyState
        icon={<UserRound size={28} />}
        title="未选择用户"
        hint="在右上角选择一个 user_id 以查看其画像。任何 id 都会返回合成画像。"
      />
    );
  }
  if (state === "loading") {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
        <Loader2 size={18} className="animate-spin" /> 加载画像…
      </div>
    );
  }
  if (state === "error" || !profile) {
    return <EmptyState icon={<UserRound size={28} />} title="加载画像失败" hint={error} />;
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl">
        {!editing && <SkillComboCard userId={currentUser} />}
        {editing ? (
          <ProfileCard
            mode="edit"
            profile={profile}
            uid={currentUser}
            onSaved={(saved, uid) => {
              setProfileState(saved);
              setProfile(uid, saved); // reflect in top-bar name/avatar + switcher caches
              setEditing(false);
            }}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <ProfileCard
            mode="view"
            profile={profile}
            uid={currentUser}
            actions={
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil size={13} /> 编辑
              </Button>
            }
          />
        )}
      </div>
    </div>
  );
}

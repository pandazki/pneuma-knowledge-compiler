import { useEffect } from "react";
import { UserRoundPlus } from "lucide-react";
import { useApp } from "@/lib/store";
import { Combobox, type ComboboxItem } from "@/ui/Combobox";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

function AvatarMark({ initial, className }: { initial: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex size-5 shrink-0 items-center justify-center rounded-1 bg-active text-12 font-medium text-ink",
        className,
      )}
    >
      {initial}
    </span>
  );
}

/**
 * synthetic 用户切换：avatar 字标 + display_name + mono id；
 * 「最近」分组（store.recentUsers）+「新建画像」（过滤词即新 id，走 createUser）。
 */
export function UserPicker() {
  const users = useApp((s) => s.users);
  const currentUser = useApp((s) => s.currentUser);
  const currentProfile = useApp((s) => s.currentProfile);
  const profileNames = useApp((s) => s.profileNames);
  const recentUsers = useApp((s) => s.recentUsers);
  const setUser = useApp((s) => s.setUser);
  const createUser = useApp((s) => s.createUser);
  const ensureNames = useApp((s) => s.ensureNames);

  useEffect(() => {
    ensureNames(users);
  }, [users, ensureNames]);

  const nameOf = (uid: string) =>
    profileNames[uid] ?? (uid === currentUser ? currentProfile?.display_name : undefined) ?? uid;
  const initialOf = (uid: string) =>
    (uid === currentUser ? currentProfile?.avatar.initial : undefined) ??
    nameOf(uid).charAt(0).toUpperCase();

  const recent = recentUsers.filter((u) => users.includes(u)).slice(0, 3);
  const rest = users.filter((u) => !recent.includes(u));

  const toItem = (uid: string, group: string): ComboboxItem => ({
    value: uid,
    label: nameOf(uid),
    keywords: uid,
    group,
    render: () => (
      <span className="flex items-center gap-2">
        <AvatarMark initial={initialOf(uid)} />
        <span className="min-w-0 flex-1 truncate">{nameOf(uid)}</span>
        <Mono className="shrink-0 text-12 text-ink-3">{uid}</Mono>
      </span>
    ),
  });

  const items: ComboboxItem[] = [
    ...recent.map((u) => toItem(u, "最近")),
    ...rest.map((u) => toItem(u, recent.length > 0 ? "全部" : "")),
  ];

  return (
    <Combobox
      value={currentUser}
      onChange={setUser}
      items={items}
      trigger={
        <span className="flex items-center gap-1.5">
          {currentUser && <AvatarMark initial={initialOf(currentUser)} />}
          <span className="max-w-28 truncate">
            {currentUser ? nameOf(currentUser) : "选择画像"}
          </span>
        </span>
      }
      triggerAriaLabel="切换用户画像"
      filterPlaceholder="输入名字或 user_id…"
      emptyText="没有匹配的画像"
      footer={(query, close) => {
        const id = query.trim();
        if (!id || users.includes(id)) return null;
        return (
          <button
            type="button"
            onClick={() => {
              createUser(id);
              close();
            }}
            className="flex w-full cursor-pointer items-center gap-2 rounded-1 px-2.5 py-1.5 text-left text-13 text-accent hover:bg-accent-soft"
          >
            <UserRoundPlus size={14} aria-hidden />
            <span className="min-w-0 truncate">
              新建画像 <Mono className="text-12">{id}</Mono>
            </span>
          </button>
        );
      }}
    />
  );
}

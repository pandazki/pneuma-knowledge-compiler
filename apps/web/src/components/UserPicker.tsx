import { useEffect } from "react";
import { UserRoundPlus } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
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
 * Synthetic user switcher: avatar mark + display_name + mono id, a "recent" group
 * (store.recentUsers) and a "new profile" footer where the filter text IS the new id
 * (routed through createUser).
 */
export function UserPicker() {
  const t = useT();
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
    ...recent.map((u) => toItem(u, t("nav.user.recent"))),
    ...rest.map((u) => toItem(u, recent.length > 0 ? t("nav.user.all") : "")),
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
            {currentUser ? nameOf(currentUser) : t("nav.user.choose")}
          </span>
        </span>
      }
      triggerAriaLabel={t("nav.user.switchAria")}
      filterPlaceholder={t("nav.user.filterPlaceholder")}
      emptyText={t("nav.user.empty")}
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
              {t("nav.user.create")} <Mono className="text-12">{id}</Mono>
            </span>
          </button>
        );
      }}
    />
  );
}

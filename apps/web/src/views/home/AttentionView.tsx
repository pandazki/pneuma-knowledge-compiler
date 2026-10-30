import { useApp } from "@/lib/store";
import { useHome } from "@/lib/useHome";

export default function AttentionView() {
  const home = useHome();
  const locale = useApp((s) => s.locale);
  const theme = useApp((s) => s.theme);
  const userId = useApp((s) => s.currentUser);
  const current = home?.libraries.find((library) => library.current);
  if (!current || current.tenant !== userId)
    return (
      <p className="p-8 text-ink-2">
        {locale === "zh"
          ? "注意力看板属于本机个人知识库，请先选择该引擎对应的画像。"
          : "Attention belongs to this personal library. Select the engine’s own profile to open it."}
      </p>
    );
  return (
    <iframe
      className="block w-full border-0"
      style={{ height: "calc(100dvh - 110px)", minHeight: 560 }}
      title={
        locale === "zh"
          ? "注意力看板与时光机"
          : "Attention board and time machine"
      }
      src={`/home/attention/view?locale=${locale}&theme=${theme}`}
      sandbox="allow-scripts allow-same-origin allow-forms"
    />
  );
}

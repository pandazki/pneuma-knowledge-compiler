import { useMemo } from "react";
import { BookOpen } from "lucide-react";
import { useApp } from "@/lib/store";
import { DirTree } from "@/components/DirTree";
import { DocumentReader } from "@/components/DocumentReader";
import { EmptyState, Eyebrow } from "@/components/ui";

export function LibraryView() {
  const { model, selection, select } = useApp();
  if (!model) return null;
  const docs = model.dataset.documents.documents;

  // resolve the active document from the current selection, else first document.
  const { activeDoc, highlightAnchor } = useMemo(() => {
    let id: string | null = null;
    let anchor: string | null = null;
    if (selection?.kind === "document" || selection?.kind === "node") id = selection.id;
    else if (selection?.kind === "claim") {
      id = selection.documentId;
      anchor = selection.anchor;
    }
    const byId = id ? model.docById.get(id) : undefined;
    return {
      activeDoc: byId ?? docs.find((d) => d.document_id) ?? docs[0] ?? null,
      highlightAnchor: anchor,
    };
  }, [selection, model, docs]);

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      {/* left rail: directory tree */}
      <aside className="max-h-56 w-full flex-none overflow-y-auto border-b border-border bg-card md:max-h-none md:w-64 md:border-b-0 md:border-r">
        <div className="px-3 py-3 border-b border-border-subtle sticky top-0 bg-card z-10">
          <Eyebrow>Library · {docs.length} 篇文档</Eyebrow>
        </div>
        <DirTree
          root={model.tree}
          selectedPath={activeDoc?.path ?? null}
          onSelect={(path) => {
            const d = model.docByPath.get(path);
            if (d?.document_id) select({ kind: "document", id: d.document_id });
            else if (d) select({ kind: "document", id: d.path });
          }}
        />
      </aside>

      {/* reader */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {activeDoc ? (
          <DocumentReader doc={activeDoc} model={model} highlightAnchor={highlightAnchor} />
        ) : (
          <EmptyState
            icon={<BookOpen size={28} className="text-muted-foreground" />}
            title="没有文档"
            hint="该 workspace 导出的 documents.json 为空。"
          />
        )}
      </div>
    </div>
  );
}

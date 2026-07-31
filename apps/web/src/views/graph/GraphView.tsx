import { useEffect, useMemo, useState } from "react";
import { Inbox } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { getSkillInfo } from "@/lib/api";
import { lensDocuments, legacyNodeTarget, structureHealth } from "@/lib/structureLens";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { Tabs } from "@/ui/Tabs";
import { StructureHealthPanel } from "./StructureHealthPanel";
import { SnapshotComparePanel } from "./SnapshotComparePanel";

/**
 * `#/graph` — the structure lens.
 *
 * This route used to be a free-exploration canvas: a force layout of the whole base with a
 * detail rail beside it. Measured against the questions people actually bring to it, it lost
 * every one — the landing point was arbitrary, a focused neighbourhood of 24 nodes and 140
 * edges was a grey scribble, and the rail answered "what do these two have in common?" with a
 * truncated list of ids and the word "link". The document view answered the same question in
 * five seconds, with dates and names, because it had the sentences.
 *
 * So the route keeps its address and changes its job. It is no longer a place you go to look
 * for one document — Canonical is that place, and its neighbourhood card is where a thread is
 * followed. It is the lens you point at the WHOLE structure, in the two moments a maintainer
 * needs one: "is this base healthy?" and "what did that groom actually change?".
 *
 * Old `#/graph/node/<id>` links still work; they resolve to the document (or the source) the
 * node stood for. See `structureLens.legacyNodeTarget`.
 */
export default function GraphView() {
  const t = useT();
  const dataset = useApp((s) => s.dataset);
  const model = useApp((s) => s.model);
  const currentUser = useApp((s) => s.currentUser);
  const selection = useApp((s) => s.selection);
  const jump = useApp((s) => s.jump);
  const setView = useApp((s) => s.setView);

  const [tab, setTab] = useState("health");
  // null = not read yet or unreadable; the family section says so rather than inventing families.
  const [templates, setTemplates] = useState<string[] | null>(null);

  // A node deep link is an address for a subject, and subjects are read in Canonical now.
  useEffect(() => {
    if (selection?.kind !== "node") return;
    const target = legacyNodeTarget(selection.id);
    // `jump` rather than `focusSource`: it rewrites the address into the destination's own
    // deep-link shape, so a shared old link does not stay spelled as a graph node forever.
    jump(target, target.kind === "source" ? "sources" : "library");
  }, [selection, jump]);

  // Families are the skill's declared path templates — a projection carries the documents, not
  // the slots they were meant to fill, so the roster comes from the skill face.
  useEffect(() => {
    if (!currentUser) return;
    let alive = true;
    void getSkillInfo(currentUser)
      .then((skill) => {
        if (alive) setTemplates(skill.path_templates ?? []);
      })
      .catch(() => {
        if (alive) setTemplates(null);
      });
    return () => {
      alive = false;
    };
  }, [currentUser]);

  const docs = useMemo(
    () => (model ? lensDocuments(model.dataset.documents.documents) : []),
    [model],
  );
  const health = useMemo(
    () => (docs.length ? structureHealth(docs, templates ?? []) : null),
    [docs, templates],
  );

  if (!dataset || !model || !health) {
    return (
      <>
        <PageHeader title={t("nav.view.graph")} description={t("graph.description")} />
        <EmptyState
          icon={Inbox}
          title={t("graph.empty.title")}
          description={t("graph.empty.description")}
          action={
            <Button size="sm" onClick={() => setView("ingest")}>
              {t("graph.empty.action")}
            </Button>
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("nav.view.graph")} description={t("graph.description")} />
      <Tabs
        aria-label={t("graph.tab.aria")}
        value={tab}
        onChange={setTab}
        tabs={[
          {
            value: "health",
            label: t("graph.tab.health"),
            panel: (
              <StructureHealthPanel
                health={health}
                files={docs.length}
                templatesAvailable={templates != null && templates.length > 0}
              />
            ),
          },
          {
            value: "compare",
            label: t("graph.tab.compare"),
            panel: <SnapshotComparePanel templates={templates ?? []} />,
          },
        ]}
      />
    </>
  );
}

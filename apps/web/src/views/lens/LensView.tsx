import { useEffect, useState } from "react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { legacyNodeTarget } from "@/lib/structureLens";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/ui/Tabs";
import { ReadingPanel } from "./ReadingPanel";
import { ComparePanel } from "./ComparePanel";

/**
 * `#/lens` — the structure lens (docs/design/structure-lens.md §5.1).
 *
 * The Steward works inside the library, one source at a time, and every compile can be right
 * while the sum drifts: a page filling with session narration, a chronology in ingest order,
 * a subject existing twice under two spellings, a family nothing links to. None of that is
 * visible from where the Steward stands. It is visible only from outside — which is what this
 * route is: a reader that takes the whole library at once and does not care how any page came
 * to be the way it is.
 *
 * The route's predecessor, `#/graph`, stopped at the instrument: it counted dead ends and
 * printed the three largest numbers, saying nothing about what a number COST the Owner and
 * nothing about what to do. The report replaces both halves of that: each finding names its
 * pages, its evidence, what it costs and one recommended action with an actor.
 *
 * Two things this view deliberately does NOT do. It computes nothing — the score, the levels
 * and the order all come from the service, so the number here is the number `pkc lens` prints.
 * And it pushes nothing at anybody: this version is a pure reading face, and a finding reaches
 * the Steward only because somebody asked for it (§9).
 *
 * Old `#/graph/node/<id>` links still work: `lib/hash.ts` maps the retired route name onto
 * this one, and the effect below resolves the node selection to the document (or the source)
 * that node stood for.
 */
export default function LensView() {
  const t = useT();
  const selection = useApp((s) => s.selection);
  const jump = useApp((s) => s.jump);
  const [tab, setTab] = useState("reading");

  // A node deep link is an address for a subject, and subjects are read in Canonical.
  useEffect(() => {
    if (selection?.kind !== "node") return;
    const target = legacyNodeTarget(selection.id);
    // `jump` rather than `focusSource`: it rewrites the address into the destination's own
    // deep-link shape, so a shared old link does not stay spelled as a graph node forever.
    jump(target, target.kind === "source" ? "sources" : "library");
  }, [selection, jump]);

  return (
    <>
      <PageHeader title={t("nav.view.lens")} description={t("lens.description")} />
      <Tabs
        aria-label={t("lens.tab.aria")}
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "reading", label: t("lens.tab.reading"), panel: <ReadingPanel /> },
          { value: "compare", label: t("lens.tab.compare"), panel: <ComparePanel /> },
        ]}
      />
    </>
  );
}

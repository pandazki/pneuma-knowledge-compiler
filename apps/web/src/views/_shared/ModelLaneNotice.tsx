import { KeyRound } from "lucide-react";
import { isViewVisible } from "@/lib/lenses";
import { MODEL_LANE_KEY_COMMAND, type ModelLaneView } from "@/lib/modelLanes";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import type { MessageKey } from "@/lib/i18n";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";

/**
 * What Recall / Ask / Live Context render when the machine says this library has no API key.
 *
 * The page keeps its own title, because the map of the console must not change with the
 * state of a credential: the reader arrived at Recall and is still at Recall. Under the
 * title, three sentences and nothing else — what this page is (a quality-testing tool over
 * the API's model lanes), why it cannot run (no key in this home, and the command that sets
 * one), and where retrieval actually lives (the Steward, reading the library for you).
 *
 * The way out is offered only to a lens that may take it: the Steward is the owner's, and a
 * button into a view the guard would bounce is a worse dead end than no button.
 */
export function ModelLaneNotice({ view }: { view: ModelLaneView }) {
  const t = useT();
  const lens = useApp((s) => s.lens);
  const setView = useApp((s) => s.setView);
  const stewardReachable = isViewVisible("steward", lens);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        className="shrink-0"
        title={t(`nav.view.${view}` as MessageKey)}
        description={t("modelLane.notice.what")}
      />
      <EmptyState
        icon={KeyRound}
        title={t("modelLane.notice.title")}
        description={
          <span className="flex flex-col items-center gap-2">
            <span>{t("modelLane.notice.why")}</span>
            <Mono className="text-12 text-ink-3">{MODEL_LANE_KEY_COMMAND}</Mono>
            {stewardReachable && <span>{t("modelLane.notice.retrieval")}</span>}
          </span>
        }
        action={
          stewardReachable ? (
            <Button size="sm" variant="default" onClick={() => setView("steward")}>
              {t("modelLane.notice.goSteward")}
            </Button>
          ) : undefined
        }
      />
    </div>
  );
}

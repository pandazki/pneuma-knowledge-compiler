import { useEffect, useState } from "react";
import { getHomeSourceCollection } from "@/lib/api";
import { collectionReadOnly } from "@/lib/collection";
import { fmtDateTime } from "@/lib/format";
import type { SourceCollection } from "@/lib/sourceCollection";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";

/** Optional observations stay outside the original's metadata and numbered evidence blocks. */
export function SourceCollectionProvenance({ userId, sourceId }: { userId: string; sourceId: string }) {
  const personal = useApp((state) => state.home != null);
  const snapshot = useApp(collectionReadOnly);
  const revision = useApp((state) => state.libraryRevision);
  if (!personal || snapshot) return null;
  // A new identity or revision unmounts the old request before it can repaint old context.
  return <CollectionObservations key={`${userId}\0${sourceId}\0${revision}`} userId={userId} sourceId={sourceId} />;
}

function CollectionObservations({ userId, sourceId }: { userId: string; sourceId: string }) {
  const t = useT();
  const [data, setData] = useState<SourceCollection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getHomeSourceCollection(userId, sourceId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [userId, sourceId, attempt]);

  if (!loading && !error && !data?.observations.length) return null;
  return (
    <section aria-label={t("sources.collection.title")} className="flex min-w-0 flex-col gap-2 border-y border-line py-3">
      <h3 className="text-13 font-medium text-ink">{t("sources.collection.title")}</h3>
      {loading ? <SkeletonText lines={2} /> : error ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-13 text-ink-2" title={error}>{t("sources.collection.unavailable")}</p>
          <Button type="button" size="sm" variant="ghost" onClick={() => setAttempt((value) => value + 1)}>
            {t("common.retry")}
          </Button>
        </div>
      ) : (
        <>
          <p className="text-12 text-ink-3">{t("sources.collection.description")}</p>
          <ul className="min-w-0 divide-y divide-line">
            {data?.observations.map((observation, index) => (
              <li key={`${observation.device_id}\0${observation.project_id}\0${observation.project_path}\0${index}`}
                className="flex min-w-0 flex-col gap-1.5 py-2 first:pt-0 last:pb-0">
                <p className="min-w-0 break-words text-13 text-ink">
                  {t(`sources.collection.${observation.transport}`)}
                  <span aria-hidden> · </span>
                  {observation.device_label?.trim() || <Mono className="break-all">{observation.device_id}</Mono>}
                </p>
                {observation.project_path && (
                  <p className="min-w-0 text-12 text-ink-2">
                    <span className="mr-2 text-ink-3">{t("sources.collection.path")}</span>
                    <Mono className="break-all">{observation.project_path}</Mono>
                  </p>
                )}
                <details className="min-w-0 text-12">
                  <summary className="cursor-pointer text-ink-2 hover:text-ink">{t("sources.collection.details")}</summary>
                  <dl className="mt-2 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1.5">
                    <dt className="text-ink-3">{t("sources.collection.deviceId")}</dt>
                    <dd className="min-w-0 text-ink-2"><Mono className="break-all">{observation.device_id}</Mono></dd>
                    {observation.project_name && <>
                      <dt className="text-ink-3">{t("sources.collection.project")}</dt>
                      <dd className="min-w-0 break-words text-ink-2">{observation.project_name}</dd>
                    </>}
                    {observation.project_id && <>
                      <dt className="text-ink-3">{t("sources.collection.projectId")}</dt>
                      <dd className="min-w-0 text-ink-2"><Mono className="break-all">{observation.project_id}</Mono></dd>
                    </>}
                    {observation.remotes.length > 0 && <>
                      <dt className="text-ink-3">{t("sources.collection.remotes")}</dt>
                      <dd className="min-w-0 text-ink-2">
                        <ul className="flex flex-col gap-1">
                          {observation.remotes.map((remote, remoteIndex) => <li key={remoteIndex}><Mono className="break-all">{remote}</Mono></li>)}
                        </ul>
                      </dd>
                    </>}
                    {observation.first_observed_at && <>
                      <dt className="text-ink-3">{t("sources.collection.firstObserved")}</dt>
                      <dd className="min-w-0 break-words text-ink-2">{fmtDateTime(observation.first_observed_at)}</dd>
                    </>}
                    {observation.last_observed_at && <>
                      <dt className="text-ink-3">{t("sources.collection.lastObserved")}</dt>
                      <dd className="min-w-0 break-words text-ink-2">{fmtDateTime(observation.last_observed_at)}</dd>
                    </>}
                  </dl>
                </details>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

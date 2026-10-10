import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Clock, Copy, Laptop, Pause, Play, Plus, RefreshCw } from "lucide-react";
import {
  createHomeCollectionInvitation,
  getHomeCollection,
  revokeHomeCollectionInvitation,
  updateHomeCollectionDevice,
  updateHomeLocalCollection,
} from "@/lib/api";
import {
  collectionReadOnly,
  collectionScope,
  invitationStatus,
  scopeDraft,
  type CollectionDevice,
  type CollectionInvitation,
  type CollectionInvitationRequest,
  type CollectionInvitationSecret,
  type HomeCollection,
} from "@/lib/collection";
import { fmtDateTime } from "@/lib/format";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";
import { Tabs } from "@/ui/Tabs";
import { TextField } from "@/ui/TextField";
import { cn } from "@/ui/cn";
import { CloudConnectionForm, CollectionAdvanced, type CollectionMutation } from "./CollectionAdvanced";
import { CollectionScopeFields, CollectionScopeSummary } from "./CollectionScopeFields";

interface IssuedInvitation {
  secret: CollectionInvitationSecret;
  request: CollectionInvitationRequest;
  revoked?: boolean;
}

/** One personal engine owns the configuration; invitation secrets are never persisted here. */
export function CollectionPanel() {
  const t = useT();
  const readOnly = useApp(collectionReadOnly);
  const [data, setData] = useState<HomeCollection | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [joining, setJoining] = useState(false);
  const [issued, setIssued] = useState<IssuedInvitation | null>(null);
  const [name, setName] = useState("");
  const [draft, setDraft] = useState(() => scopeDraft());
  const [processorId, setProcessorId] = useState("agent-sessions");
  const [mode, setMode] = useState("ai");
  const [now, setNow] = useState(Date.now);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  const reload = useCallback(async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setRefreshing(true);
    try {
      const next = await getHomeCollection(request.signal);
      if (!request.signal.aborted && mounted.current) {
        setData(next);
        setError(null);
      }
    } catch (failure) {
      if (!request.signal.aborted && mounted.current) setError(failure as Error);
    } finally {
      if (!request.signal.aborted && mounted.current) {
        controller.current = null;
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void reload();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        setNow(Date.now());
        if (!controller.current) void reload();
      }
    }, issued ? 5_000 : 30_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        setNow(Date.now());
        if (!controller.current) void reload();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mounted.current = false;
      controller.current?.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [reload, issued?.secret.invitation_id]);

  useEffect(() => {
    if (!issued) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [issued]);

  const mutate: CollectionMutation = async (key, operation, message) => {
    if (readOnly || busy) return false;
    setBusy(key);
    setError(null);
    setFeedback("");
    let success = false;
    try {
      await operation();
      if (mounted.current) setFeedback(message ?? "");
      success = true;
    } catch (failure) {
      if (mounted.current) setError(failure as Error);
    } finally {
      if (mounted.current) {
        setBusy(null);
        if (success) await reload();
      }
    }
    return success;
  };

  const disabled = readOnly || busy != null;
  const scope = collectionScope(draft);
  const processor = data?.processors.find((item) => item.id === processorId) ?? data?.processors[0];
  const invitations = data?.invitations ?? [];
  const current = issued && invitations.find((item) => item.invitation_id === issued.secret.invitation_id);
  const status = issued ? invitationStatus(issued.revoked
    ? { status: "revoked", expires_at: issued.secret.expires_at }
    : current || { status: "pending", expires_at: issued.secret.expires_at }, now) : null;
  const joinedDevice = current?.device_id ? data?.devices.find((device) => device.device_id === current.device_id) : null;

  function prepare() {
    if (!scope || !processor || !name.trim()) return;
    const request: CollectionInvitationRequest = { label: name.trim(), scope, processor_id: processor.id };
    void mutate("invite", async () => {
      const secret = await createHomeCollectionInvitation(request);
      if (mounted.current) { setIssued({ secret, request }); setNow(Date.now()); }
    });
  }

  function regenerate() {
    if (!issued) return;
    const prior = issued;
    void mutate("reissue", async () => {
      if (status !== "revoked") await revokeHomeCollectionInvitation(prior.secret.invitation_id);
      // Clear the old secret as soon as revocation succeeds, even if creating its replacement fails.
      if (mounted.current) { setIssued(null); setJoining(true); }
      const secret = await createHomeCollectionInvitation(prior.request);
      if (mounted.current) { setIssued({ secret, request: prior.request }); setNow(Date.now()); }
    });
  }

  async function copy() {
    if (!issued || status !== "pending") return;
    try {
      await navigator.clipboard.writeText(mode === "ai" ? issued.secret.ai_prompt : issued.secret.command);
      setFeedback(t("collection.copied"));
    } catch {
      setFeedback(t("collection.copyFailed"));
    }
  }

  const instruction = issued ? (
    <div className="flex flex-col gap-4">
      <pre tabIndex={0} aria-label={t("collection.instructionLabel")} className="max-w-full whitespace-pre-wrap break-all rounded-2 border border-line bg-surface p-4 font-mono text-13 leading-relaxed text-ink">
        {mode === "ai" ? issued.secret.ai_prompt : issued.secret.command}
      </pre>
      <Button type="button" variant="primary" onClick={() => void copy()} className="h-auto min-h-9 self-start py-2 text-left">
        <Copy size={15} aria-hidden />{t(mode === "ai" ? "collection.copyAI" : "collection.copyCommand")}
      </Button>
    </div>
  ) : null;

  return (
    <section aria-labelledby="collection-heading" className="flex min-w-0 flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 id="collection-heading" className="font-serif text-24 text-ink">{t("collection.title")}</h2>
          <p className="mt-2 max-w-measure text-14 text-ink-2">{t("collection.description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="ghost" size="sm" loading={refreshing} onClick={() => void reload()}>
            {!refreshing && <RefreshCw size={14} aria-hidden />}{t("collection.refresh")}
          </Button>
          {!joining && !issued && data && (
            <Button type="button" variant="primary" size="sm" disabled={disabled} onClick={() => { setJoining(true); setFeedback(""); }}>
              <Plus size={14} aria-hidden />{t("collection.add")}
            </Button>
          )}
        </div>
      </div>

      {readOnly && <Callout tone="info">{t("collection.snapshot")}</Callout>}
      {error && (data
        ? <Callout tone="danger" title={t("collection.actionError")}><span>{error.message}</span></Callout>
        : <ErrorState title={t("collection.loadError")} error={error} onRetry={() => void reload()} />)}
      {feedback && <p role="status" className="text-13 text-ink-2">{feedback}</p>}
      {!data && !error && <SkeletonText lines={4} />}

      {data && <>
        {data.cloud.error && <Callout tone="warn">{t("collection.cloudError", { detail: data.cloud.error })}</Callout>}
        {(joining || issued) && (
          <div className="flex flex-col gap-5 border-y border-line py-5">
            <Button type="button" variant="ghost" size="sm" className="self-start" disabled={busy != null} onClick={() => {
              setIssued(null); setJoining(false); setFeedback("");
            }}><ArrowLeft size={14} aria-hidden />{t("collection.back")}</Button>

            {!issued && (data.cloud.configured ? (
              <form className="flex max-w-2xl flex-col gap-5" onSubmit={(event) => { event.preventDefault(); prepare(); }}>
                <div>
                  <h3 className="font-serif text-20">{t("collection.add")}</h3>
                  <p className="mt-2 text-14 text-ink-2">{t("collection.addDescription")}</p>
                  <p className="mt-2 text-12 text-ink-2">{t("collection.cloudReady")}</p>
                </div>
                <TextField label={t("collection.deviceName")} placeholder={t("collection.deviceNamePlaceholder")}
                  value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required disabled={disabled} />
                <div className="flex flex-col gap-2">
                  <span className="text-13 font-medium text-ink">{t("collection.scope")}</span>
                  <CollectionScopeSummary scope={scope} />
                  <details className="mt-1">
                    <summary className="cursor-pointer text-13 text-accent">{t("collection.scopeAdjust")}</summary>
                    <div className="mt-4"><CollectionScopeFields value={draft} onChange={setDraft} disabled={disabled} /></div>
                  </details>
                </div>
                {data.processors.length > 1 && <Select label={t("collection.processor")} value={processor?.id ?? ""} onChange={setProcessorId}
                  options={data.processors.map((item) => ({ value: item.id, label: item.label }))} disabled={disabled} />}
                {processor && <p className="text-13 text-ink-2">{t("collection.summaryProcessor", { label: processor.label })}</p>}
                <Button type="submit" variant="primary" disabled={disabled || !scope || !processor || !name.trim()} loading={busy === "invite"} className="self-start">
                  {t("collection.prepare")}
                </Button>
              </form>
            ) : <CloudConnectionForm key={data.cloud.url} cloud={data.cloud} disabled={disabled} busy={busy} mutate={mutate} />)}

            {issued && status && <>
              <div className="flex flex-col gap-3">
                <h3 className="font-serif text-20">{t("collection.summaryTitle")}</h3>
                <p className="text-14 font-medium">{issued.request.label}</p>
                <CollectionScopeSummary scope={issued.request.scope} />
                <p className="text-13 text-ink-2">{t("collection.summaryDiscover")}</p>
                <p className="text-13 text-ink-2">{t("collection.summaryProject")}</p>
                <p className="text-13 text-ink-2">{t("collection.summaryProcessor", {
                  label: data.processors.find((item) => item.id === issued.request.processor_id)?.label ?? issued.request.processor_id,
                })}</p>
              </div>
              {status === "pending" && (
                <div className="flex min-w-0 flex-col gap-3 border-t border-line pt-5">
                  <h3 className="font-serif text-20">{t("collection.instructionTitle")}</h3>
                  <Tabs aria-label={t("collection.instructionMode")} value={mode} onChange={setMode} tabs={[
                    { value: "ai", label: t("collection.aiMode"), panel: instruction },
                    { value: "direct", label: t("collection.directMode"), panel: instruction },
                  ]} />
                  <p className="text-12 text-ink-2">{t("collection.invitationExpires", { time: fmtDateTime(issued.secret.expires_at) })}</p>
                  <p className="text-12 text-ink-2">{t("collection.invitationNotStored")}</p>
                </div>
              )}
              <div className="flex flex-wrap items-start justify-between gap-4 border-t border-line pt-5">
                <div className="flex min-w-0 flex-col gap-2" role="status">
                  <h3 className={cn("flex items-center gap-2 text-14 font-medium", status === "redeemed" ? "text-ok" : "text-ink")}>
                    {status === "redeemed" ? <Check size={16} aria-hidden /> : <Clock size={16} aria-hidden />}
                    {t(`collection.invitation.${status}`)}
                  </h3>
                  <p className="text-13 text-ink-2">{t(status === "pending" ? "collection.waitingHint" : status === "redeemed" ? "collection.redeemedHint" : "collection.inactiveHint")}</p>
                  {joinedDevice && <p className="text-13 text-ink-2">{t("collection.redeemedDevice", { label: joinedDevice.label })}</p>}
                </div>
                {status !== "redeemed" && <div className="flex flex-wrap gap-2">
                  <Button type="button" size="sm" disabled={disabled} loading={busy === "reissue"} onClick={regenerate}>{t("collection.regenerate")}</Button>
                  {status === "pending" && <Button type="button" size="sm" variant="ghost" disabled={disabled} loading={busy === `invite:${issued.secret.invitation_id}`}
                    onClick={() => void mutate(`invite:${issued.secret.invitation_id}`, async () => {
                      await revokeHomeCollectionInvitation(issued.secret.invitation_id);
                      if (mounted.current) setIssued({ ...issued, revoked: true });
                    })}>{t("collection.revokeInvite")}</Button>}
                </div>}
              </div>
            </>}
          </div>
        )}

        <div>
          <h3 className="mb-3 font-serif text-20">{t("collection.devices")}</h3>
          <div className="divide-y divide-line border-y border-line">
            {data.sources.filter((source) => source.kind === "local").map((source) => (
              <div key={source.id} className="flex flex-wrap items-start justify-between gap-4 py-4">
                <div className="flex min-w-0 gap-3">
                  <Laptop size={19} aria-hidden className="mt-1 shrink-0 text-ink-2" />
                  <div className="flex min-w-0 flex-col gap-2">
                    <p className="text-14 font-medium">{t("collection.local")}</p>
                    <p className={cn("text-13", source.enabled ? "text-ok" : "text-ink-2")}>{t(source.enabled ? "collection.localEnabled" : "collection.localPaused")}</p>
                    {source.complex_scope
                      ? <p className="text-13 text-ink-2">{t("collection.customScope")}</p>
                      : source.scope?.projects.length && source.scope?.harnesses.length
                        ? <CollectionScopeSummary scope={source.scope} />
                        : <p className="text-13 text-ink-2">{t("collection.noLocalScope")}</p>}
                  </div>
                </div>
                <Button type="button" size="sm" variant="ghost" disabled={disabled || !source.scope || !collectionScope(scopeDraft(source.scope))} loading={busy === "local"} onClick={() => {
                  void mutate("local", () => updateHomeLocalCollection({ enabled: !source.enabled }));
                }}>
                  {source.enabled ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}{t(source.enabled ? "collection.pause" : "collection.resume")}
                </Button>
              </div>
            ))}
            {data.devices.map((device) => <RemoteDevice key={device.device_id} device={device} disabled={disabled} busy={busy} mutate={mutate} />)}
          </div>
          {data.devices.length === 0 && <p className="mt-3 text-13 text-ink-2">{t("collection.noRemoteDevices")}</p>}
          <p className="mt-4 text-13 text-ink-2">{t("collection.projectNote")}</p>
        </div>

        {invitations.some((invitation) => invitation.invitation_id !== issued?.secret.invitation_id && invitationStatus(invitation, now) === "pending") && (
          <div>
            <h3 className="mb-2 font-serif text-20">{t("collection.pendingInvitations")}</h3>
            <div className="divide-y divide-line">
              {invitations.filter((invitation) => invitation.invitation_id !== issued?.secret.invitation_id && invitationStatus(invitation, now) === "pending").map((invitation) => (
                <PendingInvitation key={invitation.invitation_id} invitation={invitation} disabled={disabled} busy={busy} mutate={mutate} />
              ))}
            </div>
          </div>
        )}

        <CollectionAdvanced data={data} disabled={disabled} busy={busy} mutate={mutate} />
      </>}
    </section>
  );
}

function RemoteDevice({ device, disabled, busy, mutate }: {
  device: CollectionDevice;
  disabled: boolean;
  busy: string | null;
  mutate: CollectionMutation;
}) {
  const t = useT();
  const [confirm, setConfirm] = useState(false);
  const key = `device:${device.device_id}`;
  return (
    <div className="flex flex-col gap-3 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 gap-3">
          <Laptop size={19} aria-hidden className="mt-1 shrink-0 text-ink-2" />
          <div className="flex min-w-0 flex-col gap-2">
            <p className="break-words text-14 font-medium">{device.label}</p>
            <p className="text-13 text-ink-2">{t(`collection.device.${device.status}`)}</p>
            <p className="text-12 text-ink-2">{device.last_seen_at ? t("collection.lastSeen", { time: fmtDateTime(device.last_seen_at) }) : t("collection.neverSeen")}</p>
            <p className="text-12 text-ink-2">{device.last_snapshot_at ? t("collection.lastSnapshot", { time: fmtDateTime(device.last_snapshot_at) }) : t("collection.noSnapshot")}</p>
          </div>
        </div>
        {device.status !== "revoked" && <Button type="button" size="sm" variant="ghost" disabled={disabled} loading={busy === key}
          onClick={() => void mutate(key, () => updateHomeCollectionDevice(device.device_id, device.status === "active" ? "paused" : "active"))}>
          {device.status === "active" ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}{t(device.status === "active" ? "collection.pause" : "collection.resume")}
        </Button>}
      </div>
      <details className="pl-8">
        <summary className="cursor-pointer text-12 text-ink-2">{t("collection.advanced")}</summary>
        <div className="mt-3 flex flex-col gap-3">
          <Mono className="break-all text-12 text-ink-2">{device.device_id}</Mono>
          {device.policy?.scope && <div className="flex flex-col gap-2">
            <span className="text-13 font-medium">{t("collection.scope")}</span>
            <CollectionScopeSummary scope={device.policy.scope} />
            {!device.policy.scope.projects.includes("all") && device.policy.scope.projects.map((path) =>
              <Mono key={path} className="break-all text-12 text-ink-2">{path}</Mono>)}
          </div>}
          <p className="text-12 text-ink-2">{t("collection.deviceScopeNote")}</p>
          {device.status !== "revoked" && (confirm ? (
            <div className="flex flex-col gap-2">
              <p className="text-13 text-ink-2">{t("collection.revokeDeviceHint")}</p>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="danger" disabled={disabled} loading={busy === key} onClick={() => void mutate(key, () => updateHomeCollectionDevice(device.device_id, "revoked"))}>{t("collection.confirmRevoke")}</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setConfirm(false)}>{t("collection.cancel")}</Button>
              </div>
            </div>
          ) : <Button type="button" size="sm" variant="ghost" disabled={disabled} className="self-start text-danger" onClick={() => setConfirm(true)}>{t("collection.revokeDevice")}</Button>)}
        </div>
      </details>
    </div>
  );
}

function PendingInvitation({ invitation, disabled, busy, mutate }: {
  invitation: CollectionInvitation;
  disabled: boolean;
  busy: string | null;
  mutate: CollectionMutation;
}) {
  const t = useT();
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-14 text-ink">{invitation.label}</p>
        <p className="text-12 text-ink-2">{t("collection.invitationExpires", { time: fmtDateTime(invitation.expires_at) })}</p>
      </div>
      <Button type="button" size="sm" variant="ghost" disabled={disabled} loading={busy === `invite:${invitation.invitation_id}`}
        onClick={() => void mutate(`invite:${invitation.invitation_id}`, () => revokeHomeCollectionInvitation(invitation.invitation_id))}>{t("collection.revokeInvite")}</Button>
    </div>
  );
}

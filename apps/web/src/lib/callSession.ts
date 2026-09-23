/**
 * The plumbing of one voice call: a peer connection to the voice provider, and a socket to
 * our engine.
 *
 * A small class with callbacks, like `StewardSocket` — it owns no policy and keeps no view
 * state. Everything it learns it hands to `onEvent` as one of `lib/call.ts`'s events, and the
 * reducer there decides what any of it means. Two sides, and the split is the whole design:
 *
 *   THE PEER CONNECTION carries the audio both ways and, on the `oai-events` data channel,
 *   the session's own account of itself — transcript fragments of both speakers, the mute
 *   state, the close. It knows nothing about the library.
 *
 *   THE ENGINE SOCKET carries what only the library knows: a question was delegated, this is
 *   what it answered, these are the citations. It is opened with the `call_id` the engine
 *   answered the offer with.
 *
 * Nothing here starts on its own. A session is billed by the minute, so `start()` is called
 * from a user gesture and from nowhere else, and ending is a handshake rather than a hang-up:
 * the close is asked for on both channels, the media stays alive until the session says it is
 * over, and a 15-second fallback stops the call anyway if nobody answers.
 */

import { CallSocket, startCall } from "./api";
import type { CallEvent, Delegation } from "./call";

/** How long to wait for ICE gathering before sending the offer as it stands. */
const ICE_TIMEOUT_MS = 10_000;
/** How long to wait for the session's own goodbye before stopping the media anyway. */
const CLOSE_TIMEOUT_MS = 15_000;

export interface CallSessionHandlers {
  /** Every event, from either side, in arrival order. */
  onEvent: (event: CallEvent) => void;
  /** The voice's audio track, wrapped for an `<audio>` element to play. */
  onRemoteStream: (stream: MediaStream) => void;
}

/** The provider's data-channel events this client consumes; everything else is ignored. */
interface ChannelEvent {
  type?: string;
  delta?: string;
  start_ms?: number;
  end_ms?: number;
  reason?: string;
  usage?: { seconds?: number } | null;
  error?: { code?: string; message?: string } | null;
}

export class CallSession {
  private pc: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private socket: CallSocket | null = null;
  private mic: MediaStream | null = null;
  private fallback: ReturnType<typeof setTimeout> | null = null;
  /** The teardown runs once: a close that arrives on both channels is still one ending. */
  private finished = false;
  private eventSeq = 0;

  constructor(
    private readonly userId: string,
    private readonly locale: "zh" | "en",
    private readonly handlers: CallSessionHandlers,
  ) {}

  /**
   * The documented negotiation, in order: the connection and its listeners first, the
   * microphone next, the data channel BEFORE the offer (a channel added afterwards would not
   * be in the SDP), then the offer to our engine and its answer back, and only then the
   * engine socket — which is what makes delegation work.
   */
  async start(): Promise<void> {
    if (this.pc || this.finished) return;
    this.handlers.onEvent({ type: "start" });

    const pc = new RTCPeerConnection();
    this.pc = pc;
    pc.ontrack = (event) => {
      if (event.track.kind !== "audio") return;
      this.handlers.onRemoteStream(new MediaStream([event.track]));
    };

    let mic: MediaStream;
    try {
      mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      if (this.finished) return;
      // The two refusals a person can act on are told apart; anything else keeps its own name.
      const name = (e as Error)?.name ?? "";
      const code =
        name === "NotAllowedError" || name === "SecurityError"
          ? "mic_denied"
          : name === "NotFoundError" || name === "OverconstrainedError"
            ? "no_microphone"
            : "mic_failed";
      this.fail(code, (e as Error)?.message ?? name);
      return;
    }
    // Permission may resolve after Cancel or navigation. Never revive the old call.
    if (this.finished) {
      for (const track of mic.getTracks()) track.stop();
      return;
    }
    this.mic = mic;
    for (const track of mic.getTracks()) pc.addTrack(track, mic);

    this.handlers.onEvent({ type: "connecting" });

    const channel = pc.createDataChannel("oai-events");
    this.channel = channel;
    // Attached before the offer exists: a session that starts talking the moment the answer
    // lands must not find nobody listening.
    channel.onmessage = (e) => this.onChannelMessage(e.data);

    let openedCallId: string | null = null;
    try {
      const offer = await pc.createOffer();
      if (this.finished) return;
      await pc.setLocalDescription(offer);
      await iceComplete(pc);
      if (this.finished) return;
      const started = await startCall(this.userId, pc.localDescription?.sdp ?? "", this.locale);
      openedCallId = started.call_id;
      if (this.finished) {
        closeCancelledCall(this.userId, openedCallId);
        return;
      }
      await pc.setRemoteDescription({ type: "answer", sdp: started.sdp });
      if (this.finished) {
        closeCancelledCall(this.userId, openedCallId);
        return;
      }
      this.socket = new CallSocket(
        this.userId,
        started.call_id,
        (frame) => this.onEngineFrame(frame),
        () => {
          /* the engine's own `closed` frame is the ending; a socket state is not one */
        },
      );
      this.handlers.onEvent({
        type: "connected",
        call_id: started.call_id,
        session_id: started.session_id,
      });
    } catch (e) {
      if (openedCallId) closeCancelledCall(this.userId, openedCallId);
      if (this.finished) return;
      this.fail("connect_failed", (e as Error)?.message ?? "");
    }
  }

  /**
   * Ask the session for the microphone state the Owner clicked for.
   *
   * It is an ASK: the state the console shows comes back from the session's own
   * `session.input_audio.muted` / `.unmuted` event, so the mic indicator can never show
   * something the session did not confirm.
   */
  setMuted(muted: boolean): void {
    this.eventSeq += 1;
    this.toChannel({
      type: muted ? "session.input_audio.mute" : "session.input_audio.unmute",
      event_id: `evt-${this.eventSeq}`,
    });
  }

  /**
   * The Owner hung up. Both sides are told, and the media stays up until the session says it
   * is over — a peer connection closed first would take the goodbye (and the final usage)
   * with it.
   */
  end(): void {
    if (this.finished) return;
    if (!this.pc) {
      this.teardown();
      return;
    }
    this.handlers.onEvent({ type: "ending" });
    this.toChannel({ type: "session.close" });
    this.socket?.end();
    if (this.fallback == null) {
      this.fallback = setTimeout(() => this.teardown(), CLOSE_TIMEOUT_MS);
    }
  }

  /**
   * The tab is going away. Both goodbyes are sent best-effort and nothing is waited for —
   * there is no later in which to wait.
   */
  hangUpNow(): void {
    if (this.finished) return;
    this.toChannel({ type: "session.close" });
    this.socket?.end();
    this.teardown();
  }

  /* ------------------------------------------------------------------ the two sides */

  private onChannelMessage(data: unknown): void {
    let event: ChannelEvent;
    try {
      event = JSON.parse(String(data)) as ChannelEvent;
    } catch {
      return;
    }
    switch (event.type) {
      case "session.started":
        this.handlers.onEvent({ type: "session.started" });
        return;
      case "session.input_transcript.delta":
      case "session.output_transcript.delta":
        this.handlers.onEvent({
          type: event.type,
          delta: event.delta ?? "",
          start_ms: event.start_ms ?? 0,
          end_ms: event.end_ms ?? event.start_ms ?? 0,
        });
        return;
      case "session.input_audio.muted":
      case "session.input_audio.unmuted":
        this.handlers.onEvent({ type: event.type });
        return;
      case "session.closed":
        this.handlers.onEvent({
          type: "session.closed",
          reason: event.reason ?? "",
          usage: event.usage ?? null,
        });
        this.teardown();
        return;
      case "error":
        this.handlers.onEvent({ type: "error", error: event.error ?? null });
        return;
      default:
        // Everything else the provider sends is the session's own business.
        return;
    }
  }

  private onEngineFrame(frame: Record<string, unknown>): void {
    const type = String(frame.type ?? "");
    switch (type) {
      case "attached":
        this.handlers.onEvent({ type: "attached" });
        return;
      case "delegation":
        this.handlers.onEvent({
          type: "delegation",
          delegation: frame.delegation as Delegation,
        });
        return;
      case "usage":
        this.handlers.onEvent({
          type: "usage",
          seconds: Number(frame.seconds ?? 0),
          context_ratio: frame.context_ratio == null ? null : Number(frame.context_ratio),
        });
        return;
      case "closed":
        this.handlers.onEvent({
          type: "closed",
          reason: String(frame.reason ?? ""),
          seconds: frame.seconds == null ? null : Number(frame.seconds),
        });
        this.teardown();
        return;
      case "error":
        this.handlers.onEvent({
          type: "error",
          code: String(frame.code ?? "error"),
          detail: String(frame.detail ?? ""),
        });
        return;
      default:
        return;
    }
  }

  private toChannel(message: Record<string, unknown>): void {
    if (this.channel?.readyState !== "open") return;
    try {
      this.channel.send(JSON.stringify(message));
    } catch {
      /* the channel went away between the check and the send */
    }
  }

  private fail(code: string, detail: string): void {
    this.handlers.onEvent({ type: "failed", code, detail });
    this.teardown(true);
  }

  /** Stop the media and close both sides. Runs once, whichever goodbye arrives first. */
  private teardown(silent = false): void {
    if (this.finished) return;
    this.finished = true;
    if (this.fallback != null) {
      clearTimeout(this.fallback);
      this.fallback = null;
    }
    for (const track of this.mic?.getTracks() ?? []) track.stop();
    this.mic = null;
    if (this.channel) {
      this.channel.onmessage = null;
      this.channel = null;
    }
    try {
      this.pc?.close();
    } catch {
      /* already closed */
    }
    this.pc = null;
    this.socket?.close();
    this.socket = null;
    // A failure already said what happened; saying "ended" after it would overwrite the
    // one sentence the Owner needs.
    if (!silent) this.handlers.onEvent({ type: "ended" });
  }
}

/**
 * Wait for ICE gathering to finish, or for ten seconds — whichever comes first.
 *
 * The timeout is not a failure: an offer with the candidates gathered so far is a valid
 * offer, and a network that never reaches `complete` would otherwise hang the call at the
 * one moment the Owner is waiting with a microphone open.
 */
function iceComplete(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise<void>((resolve) => {
    const settle = () => {
      clearTimeout(timer);
      pc.removeEventListener("icegatheringstatechange", check);
      resolve();
    };
    const check = () => {
      if (pc.iceGatheringState === "complete") settle();
    };
    const timer = setTimeout(settle, ICE_TIMEOUT_MS);
    pc.addEventListener("icegatheringstatechange", check);
  });
}

/** A cancelled negotiation can still return a billed session. Close it once its socket opens. */
function closeCancelledCall(userId: string, callId: string): void {
  let socket: CallSocket | null = null;
  const timer = setTimeout(() => socket?.close(), CLOSE_TIMEOUT_MS);
  const close = () => { clearTimeout(timer); socket?.close(); };
  socket = new CallSocket(userId, callId, (frame) => {
    if (frame.type === "closed") close();
  }, (status) => {
    if (status === "open") socket?.end();
    if (status === "closed") clearTimeout(timer);
  });
}

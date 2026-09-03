/**
 * "Is this answer still the answer to the question on screen?"
 *
 * A view that fetches per user has one failure that no amount of care in the component
 * prevents: the reader switches library while a request for the previous one is on the wire,
 * the old response lands second, and the new user's screen fills with the old user's rows.
 * That is `I1` — no cross-user read path — broken at the last inch, in the browser, after
 * every server-side tenant check has already passed.
 *
 * The guard is the mechanical answer rather than a careful one: every request takes a token
 * before it goes out, and only the newest token is allowed to write state. A response for any
 * earlier token is dropped on arrival — it does not matter whether it came back because the
 * user switched, because the drawer closed, or because the network was slow.
 *
 * Deliberately free of React and of `fetch`: it is one token and two questions, so a test
 * can play the race out in-process (`tests/requestGuard.test.mjs`). Views hold one in a ref
 * and abort on cleanup as well — `invalidate()` is what makes the abort's own rejection stop
 * being a state write.
 */

/**
 * Opaque handle for one in-flight request. A symbol rather than a counter on purpose: only
 * identity with the token the guard itself handed out can pass, so no value a caller happens
 * to have lying around — 0, 1, a stale id — can be mistaken for the current request.
 */
export type RequestToken = symbol;

export interface RequestGuard {
  /** Start a request. Every token handed out before this one stops being current. */
  next(): RequestToken;
  /** True only for the newest token — a late answer for a previous one is ignored. */
  isCurrent(token: RequestToken): boolean;
  /** Retire every outstanding token without starting a request (unmount, close, switch). */
  invalidate(): void;
}

export function makeGuard(): RequestGuard {
  // The initial value is a token nobody holds, so nothing is current until a request starts.
  let current: RequestToken = Symbol("idle");
  return {
    next: () => (current = Symbol("request")),
    isCurrent: (token) => token === current,
    invalidate: () => {
      current = Symbol("idle");
    },
  };
}

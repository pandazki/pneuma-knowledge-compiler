/**
 * The Live Context conversation: roles and turns, as pure reducers.
 *
 * The page has ONE chat surface for both transports. That is the whole point of the redesign:
 * a conversation is a conversation, and which socket carries it is a delivery detail. But the
 * two deliveries differ in one way that cannot be papered over — **the one-shot transport
 * re-sends the whole window on every evaluation, while the long-lived one is append-only**.
 * So a turn already pushed on the socket is frozen: editing it would change a window the
 * server has already read, and the client would be describing a conversation that never
 * happened. `canEditTurn` is that rule, and it is the reason the reducers take a mode.
 *
 * Everything here is a pure function over plain data, with the clock as an argument — the
 * `liveStages` discipline. That is what makes "a sent turn cannot be edited" an assertion
 * about a return value rather than about a rendered button's `disabled` attribute.
 *
 * No runtime imports: the node test harness transpiles this file standalone.
 */

/** `owner` is the knowledge subject (知识主体) — the gate treats their turns differently, so
 * the pill is visually distinct and there is exactly one of it. */
export type LiveRoleKind = "owner" | "other";

/** The wire's own role vocabulary. `unknown` exists on the protocol but the chat surface
 * never produces it: every turn is typed by the pill that was active when it was written. */
export type WireRole = "owner" | "other" | "unknown";

export interface LiveRole {
  id: string;
  name: string;
  /** A palette KEY, not a CSS colour — the view maps it to tokens so themes still work. */
  colour: RoleColour;
  kind: LiveRoleKind;
}

export interface LiveTurn {
  id: string;
  roleId: string;
  text: string;
  /** epoch ms, supplied by the caller; nothing here reads a clock. */
  at: number;
  /** Pushed on the long-lived socket already. Append-only means: frozen. */
  sent: boolean;
}

export type ChatMode = "oneshot" | "stream";

/**
 * The role palette. Keys rather than colour values so the view owns the tokens and both
 * themes stay honest; the order is the assignment order for a newly added role, so two roles
 * added in a row never collide.
 */
export const ROLE_COLOURS = ["slate", "amber", "violet", "teal", "rose", "lime"] as const;
export type RoleColour = (typeof ROLE_COLOURS)[number];

/** The colour for the nth role — wraps, so an eighth role is legible rather than undefined. */
export function nextColour(count: number): RoleColour {
  return ROLE_COLOURS[count % ROLE_COLOURS.length];
}

export interface RoleState {
  roles: LiveRole[];
  /** The pill currently armed. Always names a role that exists. */
  activeId: string;
}

export type RoleAction =
  | { type: "add"; id: string; name: string }
  | { type: "rename"; id: string; name: string }
  | { type: "recolour"; id: string; colour: RoleColour }
  | { type: "remove"; id: string }
  | { type: "activate"; id: string };

/**
 * Roles: add, rename, recolour, remove, activate.
 *
 * Three rules are mechanical rather than advisory, because each one has a state the UI could
 * otherwise reach and not recover from:
 *   - the owner pill can never be removed (the gate distinguishes the knowledge subject; a
 *     conversation with no owner cannot say whose knowledge base it is about);
 *   - the last remaining role can never be removed (there would be nothing to attribute a
 *     turn to, and the composer would have no active pill);
 *   - removing the active role moves activation to the first survivor, rather than leaving
 *     `activeId` pointing at something that is gone.
 *
 * A blank or whitespace-only name is refused rather than accepted-and-rendered-empty: an
 * unnamed pill is unclickable in practice.
 */
export function roleReducer(state: RoleState, action: RoleAction): RoleState {
  switch (action.type) {
    case "add": {
      const name = action.name.trim();
      if (!name) return state;
      if (state.roles.some((r) => r.id === action.id)) return state;
      const role: LiveRole = {
        id: action.id,
        name,
        colour: nextColour(state.roles.length),
        kind: "other",
      };
      return { roles: [...state.roles, role], activeId: role.id };
    }
    case "rename": {
      const name = action.name.trim();
      if (!name) return state;
      if (!state.roles.some((r) => r.id === action.id)) return state;
      return {
        ...state,
        roles: state.roles.map((r) => (r.id === action.id ? { ...r, name } : r)),
      };
    }
    case "recolour": {
      if (!state.roles.some((r) => r.id === action.id)) return state;
      return {
        ...state,
        roles: state.roles.map((r) =>
          r.id === action.id ? { ...r, colour: action.colour } : r,
        ),
      };
    }
    case "remove": {
      const target = state.roles.find((r) => r.id === action.id);
      if (!target) return state;
      if (target.kind === "owner") return state;
      if (state.roles.length <= 1) return state;
      const roles = state.roles.filter((r) => r.id !== action.id);
      return {
        roles,
        activeId: state.activeId === action.id ? roles[0].id : state.activeId,
      };
    }
    case "activate": {
      if (!state.roles.some((r) => r.id === action.id)) return state;
      return { ...state, activeId: action.id };
    }
    default:
      return state;
  }
}

/**
 * Whether this turn may still be changed.
 *
 * One-shot: always. The window is re-sent whole on the next evaluation, so an edit is simply
 * a different window — nothing downstream has read the old one in a way that matters.
 *
 * Long-lived: only while unsent. The stream is append-only; the server has the turn, it is
 * inside the sliding window it evaluates against, and there is no wire verb for retracting
 * it. Showing the turn as immutable is honest about what actually happened.
 */
export function canEditTurn(turn: LiveTurn, mode: ChatMode): boolean {
  return mode === "oneshot" || !turn.sent;
}

export type TurnAction =
  | { type: "append"; id: string; roleId: string; text: string; at: number; sent: boolean }
  | { type: "edit"; id: string; text: string; mode: ChatMode }
  | { type: "delete"; id: string; mode: ChatMode }
  | { type: "markSent"; id: string }
  | { type: "clear" };

/**
 * The turn list. `edit` and `delete` go through `canEditTurn`, so the immutability rule is
 * enforced by the state itself and not only by a disabled button — a keyboard shortcut, a
 * restored draft or a future surface all hit the same wall.
 *
 * An edit down to empty text is a delete in disguise; it is refused instead, so a turn cannot
 * become a blank row nobody can select.
 */
export function turnReducer(turns: LiveTurn[], action: TurnAction): LiveTurn[] {
  switch (action.type) {
    case "append": {
      const text = action.text.trim();
      if (!text) return turns;
      return [
        ...turns,
        { id: action.id, roleId: action.roleId, text, at: action.at, sent: action.sent },
      ];
    }
    case "edit": {
      const text = action.text.trim();
      if (!text) return turns;
      const target = turns.find((t) => t.id === action.id);
      if (!target || !canEditTurn(target, action.mode)) return turns;
      return turns.map((t) => (t.id === action.id ? { ...t, text } : t));
    }
    case "delete": {
      const target = turns.find((t) => t.id === action.id);
      if (!target || !canEditTurn(target, action.mode)) return turns;
      return turns.filter((t) => t.id !== action.id);
    }
    case "markSent":
      return turns.map((t) => (t.id === action.id ? { ...t, sent: true } : t));
    case "clear":
      return [];
    default:
      return turns;
  }
}

/** The wire role for a turn — `owner` when the knowledge subject said it, `other` otherwise. */
export function wireRole(roles: LiveRole[], roleId: string): WireRole {
  const role = roles.find((r) => r.id === roleId);
  if (!role) return "unknown";
  return role.kind === "owner" ? "owner" : "other";
}

/** The turns not yet pushed on the socket, oldest first — what a `stream` send has to catch up. */
export function unsentTurns(turns: LiveTurn[]): LiveTurn[] {
  return turns.filter((t) => !t.sent);
}

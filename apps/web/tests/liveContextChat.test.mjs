/**
 * The Live Context chat reducers: roles, and the turn-immutability rule that separates the
 * two transports.
 *
 * The rule worth pinning is the one the UI cannot be trusted to enforce on its own. A turn
 * already pushed on the long-lived socket is inside a window the server has read; the stream
 * is append-only and there is no wire verb for retracting it. So editing it would leave the
 * client describing a conversation that never happened. A `disabled` attribute expresses that
 * as a hope; `turnReducer` refusing the action expresses it as a fact, and a keyboard path or
 * a restored draft hits the same wall.
 *
 * The role rules are the same kind of thing: three states the UI could otherwise reach and
 * not recover from — no owner, no roles at all, an `activeId` pointing at something deleted.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function tsModuleUrl(url) {
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const {
  roleReducer,
  turnReducer,
  canEditTurn,
  wireRole,
  unsentTurns,
  nextColour,
  ROLE_COLOURS,
} = await import(await tsModuleUrl(new URL("../src/lib/liveContextChat.ts", import.meta.url)));

const owner = { id: "r-owner", name: "本人", colour: "slate", kind: "owner" };
const other = { id: "r-1", name: "对方", colour: "amber", kind: "other" };
const roles = () => ({ roles: [owner, other], activeId: other.id });

const turn = (id, over = {}) => ({
  id,
  roleId: other.id,
  text: `话 ${id}`,
  at: 1_700_000_000_000,
  sent: false,
  ...over,
});

/* ------------------------------------------------------------------------ roles */

test("adding a role names it, colours it, and arms it", () => {
  const next = roleReducer(roles(), { type: "add", id: "r-2", name: "  产品  " });
  assert.equal(next.roles.length, 3);
  assert.equal(next.roles[2].name, "产品", "the name is trimmed");
  assert.equal(next.roles[2].kind, "other", "only the knowledge subject is an owner");
  assert.equal(next.activeId, "r-2", "a role you just added is the one you meant to speak as");
});

test("a blank name is refused rather than rendered as an unclickable pill", () => {
  const before = roles();
  assert.deepEqual(roleReducer(before, { type: "add", id: "r-2", name: "   " }), before);
  assert.deepEqual(roleReducer(before, { type: "rename", id: "r-1", name: "" }), before);
});

test("colours cycle so a seventh role is legible rather than undefined", () => {
  assert.equal(nextColour(0), ROLE_COLOURS[0]);
  assert.equal(nextColour(ROLE_COLOURS.length), ROLE_COLOURS[0]);
  assert.ok(ROLE_COLOURS.includes(nextColour(97)));
});

test("renaming and recolouring touch one role and leave activation alone", () => {
  const renamed = roleReducer(roles(), { type: "rename", id: "r-1", name: "供应商" });
  assert.equal(renamed.roles[1].name, "供应商");
  assert.equal(renamed.roles[0].name, "本人");
  assert.equal(renamed.activeId, other.id);

  const recoloured = roleReducer(renamed, { type: "recolour", id: "r-1", colour: "violet" });
  assert.equal(recoloured.roles[1].colour, "violet");
});

test("the knowledge subject cannot be removed", () => {
  // The gate distinguishes the owner's turns; a conversation with no owner cannot say whose
  // knowledge base it is about.
  const before = roles();
  assert.deepEqual(roleReducer(before, { type: "remove", id: "r-owner" }), before);
});

test("the last remaining role cannot be removed", () => {
  const single = { roles: [{ ...other }], activeId: other.id };
  assert.deepEqual(roleReducer(single, { type: "remove", id: other.id }), single);
});

test("removing the active role moves activation to a survivor", () => {
  const three = roleReducer(roles(), { type: "add", id: "r-2", name: "产品" });
  assert.equal(three.activeId, "r-2");
  const next = roleReducer(three, { type: "remove", id: "r-2" });
  assert.equal(next.roles.length, 2);
  assert.equal(next.activeId, "r-owner", "never left pointing at something that is gone");
});

test("activating an unknown role changes nothing", () => {
  const before = roles();
  assert.deepEqual(roleReducer(before, { type: "activate", id: "r-nope" }), before);
});

/* ------------------------------------------------------------------------ turns */

test("one-shot turns stay editable and deletable — the window is re-sent whole", () => {
  const sent = [turn("t1", { sent: true })];
  assert.equal(canEditTurn(sent[0], "oneshot"), true);
  const edited = turnReducer(sent, { type: "edit", id: "t1", text: "改过的话", mode: "oneshot" });
  assert.equal(edited[0].text, "改过的话");
  assert.deepEqual(turnReducer(edited, { type: "delete", id: "t1", mode: "oneshot" }), []);
});

test("a turn already pushed on the socket is frozen", () => {
  // Append-only: the server holds this turn inside the window it evaluates against, and there
  // is no wire verb that takes it back. Editing it locally would be a lie about the
  // conversation, so the state refuses rather than the button merely looking disabled.
  const sent = [turn("t1", { sent: true })];
  assert.equal(canEditTurn(sent[0], "stream"), false);
  assert.deepEqual(
    turnReducer(sent, { type: "edit", id: "t1", text: "偷改", mode: "stream" }),
    sent,
  );
  assert.deepEqual(turnReducer(sent, { type: "delete", id: "t1", mode: "stream" }), sent);
});

test("an unsent draft stays editable in stream mode", () => {
  const draft = [turn("t1", { sent: false })];
  assert.equal(canEditTurn(draft[0], "stream"), true);
  const edited = turnReducer(draft, { type: "edit", id: "t1", text: "还没发", mode: "stream" });
  assert.equal(edited[0].text, "还没发");
});

test("marking a turn sent freezes it from that moment", () => {
  const before = [turn("t1")];
  const after = turnReducer(before, { type: "markSent", id: "t1" });
  assert.equal(after[0].sent, true);
  assert.deepEqual(turnReducer(after, { type: "delete", id: "t1", mode: "stream" }), after);
});

test("empty text is never appended and never edited in", () => {
  assert.deepEqual(
    turnReducer([], { type: "append", id: "t1", roleId: "r-1", text: "   ", at: 0, sent: false }),
    [],
  );
  const one = [turn("t1")];
  assert.deepEqual(turnReducer(one, { type: "edit", id: "t1", text: "  ", mode: "oneshot" }), one);
});

test("appended text is trimmed and carries its role and clock", () => {
  const next = turnReducer([], {
    type: "append",
    id: "t1",
    roleId: "r-owner",
    text: "  交期确认了  ",
    at: 42,
    sent: true,
  });
  assert.deepEqual(next, [
    { id: "t1", roleId: "r-owner", text: "交期确认了", at: 42, sent: true },
  ]);
});

test("the wire role collapses the pills to owner / other, and an orphan to unknown", () => {
  assert.equal(wireRole([owner, other], "r-owner"), "owner");
  assert.equal(wireRole([owner, other], "r-1"), "other");
  assert.equal(wireRole([owner, other], "r-gone"), "unknown");
});

test("unsent turns are what a reconnecting stream has to catch up", () => {
  const list = [turn("t1", { sent: true }), turn("t2"), turn("t3", { sent: true })];
  assert.deepEqual(
    unsentTurns(list).map((t) => t.id),
    ["t2"],
  );
});

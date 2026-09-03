/**
 * The archive dialog's arithmetic.
 *
 * Three behaviours are worth pinning, and all three are places where the obvious
 * implementation would be wrong:
 *
 * 1. Ticking a row the PLAN left unselected re-plans with that row as a new seed. Flipping
 *    the flag locally would put an item on the list that no closure produced, with a reason
 *    field that cannot explain it — and the service refuses a ref it never computed anyway.
 * 2. Unticking narrows, and narrowing travels in the confirm's `items`. A confirm that
 *    changed nothing must send NO override at all, so the service executes the set it
 *    computed rather than a client's restatement of it.
 * 3. "Listed is not selected" is a group, not a filter: a source another live document still
 *    cites stays on screen with the documents that kept it.
 *
 * The i18n lookup is injected — the module is transpiled standalone here — and the fake
 * returns the key plus its params, which is also how a wrong key would show.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function load(path) {
  const url = new URL(path, import.meta.url);
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`
  );
}

const {
  CITED_BY_SHOWN,
  citedByLabel,
  recordFactsLine,
  recordReasonPreview,
  confirmSelection,
  groupItems,
  isSelected,
  isStalePlan,
  itemKey,
  reasonMessage,
  selectionCounts,
  summaryMessage,
  toggleItem,
  settleConfirm,
  withSeed,
} = await load("../src/views/archive/proposal.ts");
// The real guard, not a stand-in: the point of the confirm test below is that both of the
// dialog's per-user requests answer to the SAME rule.
const { makeGuard } = await load("../src/lib/requestGuard.ts");

const i18n = { t: (key, params) => (params ? `${key} ${JSON.stringify(params)}` : key) };

/* ------------------------------------------------------------------- the fixture */

/**
 * The design's own worked example: the owner names one document; its sources follow, one of
 * them kept by another live page; a second document is fully dependent and comes along.
 */
const SEED_DOC = {
  kind: "document",
  ref: "work/products/aurora.md",
  title: "Aurora",
  role: "seed",
  selected: true,
  reason: { note: "seed" },
  volumes: ["work/products/aurora/a01.md"],
};

const ORPHANED_SOURCE = {
  kind: "source",
  ref: "src_aurora_standup",
  title: "Aurora standup",
  role: "cascade",
  selected: true,
  reason: { note: "orphaned", cited_by_live: [] },
};

const KEPT_SOURCE = {
  kind: "source",
  ref: "src_platform_review",
  title: "Platform review",
  role: "cascade",
  selected: false,
  reason: {
    note: "still_cited",
    cited_by_live: ["work/products/orbit.md", "memory/topics/retrieval.md"],
  },
};

const DEPENDENT_DOC = {
  kind: "document",
  ref: "work/products/aurora-rollout.md",
  title: "Aurora rollout",
  role: "cascade",
  selected: true,
  reason: { note: "fully_dependent", dependence: [12, 12] },
};

const PROPOSAL = {
  proposal_id: "ap-1",
  action: "archive",
  status: "proposed",
  library_ref: "0b1c2d3",
  seeds: { documents: ["work/products/aurora.md"], sources: [] },
  items: [SEED_DOC, ORPHANED_SOURCE, KEPT_SOURCE, DEPENDENT_DOC],
};

/* -------------------------------------------------------------------- the grouping */

test("the three groups are what you named, what goes with it, and what stays", () => {
  const groups = groupItems(PROPOSAL.items);
  assert.deepEqual(groups.seeds.map((i) => i.ref), ["work/products/aurora.md"]);
  assert.deepEqual(groups.cascade.map((i) => i.ref), [
    "src_aurora_standup",
    "work/products/aurora-rollout.md",
  ]);
  // Listed is not selected — and it is LISTED, not filtered out. This row is the reason the
  // owner might stop.
  assert.deepEqual(groups.related.map((i) => i.ref), ["src_platform_review"]);
});

test("an unticked seed stays under the heading the owner recognises", () => {
  const overrides = { [itemKey("document", "work/products/aurora.md")]: false };
  const groups = groupItems(PROPOSAL.items, overrides);
  assert.deepEqual(groups.seeds.map((i) => i.ref), ["work/products/aurora.md"]);
  assert.equal(isSelected(SEED_DOC, overrides), false);
  assert.equal(groups.related.some((i) => i.ref === SEED_DOC.ref), false);
});

test("an unticked cascade item moves down into the group that is staying", () => {
  const overrides = { [itemKey("source", "src_aurora_standup")]: false };
  const groups = groupItems(PROPOSAL.items, overrides);
  assert.deepEqual(groups.cascade.map((i) => i.ref), ["work/products/aurora-rollout.md"]);
  assert.deepEqual(groups.related.map((i) => i.ref), [
    "src_aurora_standup",
    "src_platform_review",
  ]);
});

/* --------------------------------------------------------------------- the toggle */

test("ticking an unselected cascade item RE-PLANS with it as another seed", () => {
  const outcome = toggleItem(PROPOSAL, {}, KEPT_SOURCE, true);
  assert.equal(outcome.kind, "replan");
  assert.deepEqual(outcome.seeds, {
    documents: ["work/products/aurora.md"],
    sources: ["src_platform_review"],
  });
});

test("unticking a selected item is a local override, never a round trip", () => {
  const outcome = toggleItem(PROPOSAL, {}, DEPENDENT_DOC, false);
  assert.equal(outcome.kind, "override");
  assert.deepEqual(outcome.overrides, {
    "document:work/products/aurora-rollout.md": false,
  });
});

test("re-ticking what you just unticked puts the plan back rather than re-planning", () => {
  const off = toggleItem(PROPOSAL, {}, DEPENDENT_DOC, false).overrides;
  const back = toggleItem(PROPOSAL, off, DEPENDENT_DOC, true);
  assert.equal(back.kind, "override", "the plan already selected it — this is not widening");
  assert.deepEqual(back.overrides, {}, "an override equal to the plan is not an override");
});

test("a seed the plan left unselected is ticked locally, not re-planned", () => {
  // `already_archived`: the owner named something that is already in the archive. Ticking it
  // adds nothing to compute, so it must not cost a round trip.
  const already = { ...SEED_DOC, selected: false, reason: { note: "already_archived" } };
  const proposal = { ...PROPOSAL, items: [already] };
  const outcome = toggleItem(proposal, {}, already, true);
  assert.equal(outcome.kind, "override");
  assert.deepEqual(outcome.overrides, { "document:work/products/aurora.md": true });
});

test("a re-plan seed list keeps what was already there and never doubles a ref", () => {
  const once = withSeed(PROPOSAL.seeds, KEPT_SOURCE);
  const twice = withSeed(once, KEPT_SOURCE);
  assert.deepEqual(twice, once);
  assert.deepEqual(PROPOSAL.seeds, { documents: ["work/products/aurora.md"], sources: [] });
});

/* -------------------------------------------------------------------- the confirm */

test("a confirm that changed nothing sends no override at all", () => {
  assert.equal(confirmSelection(PROPOSAL.items, {}), undefined);
  // Even an override map that agrees with the plan is not a change.
  assert.equal(
    confirmSelection(PROPOSAL.items, { [itemKey("source", "src_aurora_standup")]: true }),
    undefined,
  );
});

test("a narrowed confirm states the WHOLE set, not only the rows that changed", () => {
  const overrides = { [itemKey("document", "work/products/aurora-rollout.md")]: false };
  assert.deepEqual(confirmSelection(PROPOSAL.items, overrides), [
    { kind: "document", ref: "work/products/aurora.md", selected: true },
    { kind: "source", ref: "src_aurora_standup", selected: true },
    { kind: "source", ref: "src_platform_review", selected: false },
    { kind: "document", ref: "work/products/aurora-rollout.md", selected: false },
  ]);
});

test("the counts are of the effective selection, kind by kind", () => {
  assert.deepEqual(selectionCounts(PROPOSAL.items), {
    documents: 2,
    sources: 1,
    total: 3,
  });
  const overrides = { [itemKey("source", "src_aurora_standup")]: false };
  assert.deepEqual(selectionCounts(PROPOSAL.items, overrides), {
    documents: 2,
    sources: 0,
    total: 2,
  });
});

/* ----------------------------------------------------------------------- the copy */

test("the summary names only the kinds it actually has", () => {
  assert.equal(
    summaryMessage("archive", { documents: 2, sources: 1, total: 3 }, i18n),
    'archive.summary.archive.both {"documents":2,"sources":1}',
  );
  assert.equal(
    summaryMessage("archive", { documents: 2, sources: 0, total: 2 }, i18n),
    'archive.summary.archive.documents {"documents":2}',
  );
  assert.equal(
    summaryMessage("unarchive", { documents: 0, sources: 3, total: 3 }, i18n),
    'archive.summary.unarchive.sources {"sources":3}',
  );
  assert.equal(
    summaryMessage("unarchive", { documents: 0, sources: 0, total: 0 }, i18n),
    "archive.summary.unarchive.none",
  );
});

test("the reason is the planner's own note, rendered as one short line", () => {
  assert.equal(reasonMessage(SEED_DOC, i18n), "archive.reason.seed");
  assert.equal(reasonMessage(ORPHANED_SOURCE, i18n), "archive.reason.orphaned");
  assert.equal(
    reasonMessage(DEPENDENT_DOC, i18n),
    'archive.reason.fullyDependent {"cited":12,"total":12}',
  );
  assert.equal(
    reasonMessage(
      { ...DEPENDENT_DOC, reason: { note: "partially_dependent", dependence: [3, 20] } },
      i18n,
    ),
    'archive.reason.partiallyDependent {"cited":3,"total":20}',
  );
  assert.equal(
    reasonMessage(KEPT_SOURCE, i18n),
    'archive.reason.stillCited {"documents":"work/products/orbit.md, memory/topics/retrieval.md"}',
  );
});

test("a note this build does not know renders as nothing, never as a raw code", () => {
  for (const note of ["unknown", "some_future_code", "", undefined]) {
    assert.equal(reasonMessage({ ...ORPHANED_SOURCE, reason: { note } }, i18n), "");
  }
  // A missing reason object at all is the same non-answer, not a crash.
  assert.equal(reasonMessage({ ...ORPHANED_SOURCE, reason: undefined }, i18n), "");
});

test("the keepers of a still-cited source are named, and then counted", () => {
  const many = ["a.md", "b.md", "c.md", "d.md", "e.md"];
  assert.equal(CITED_BY_SHOWN, 3);
  assert.equal(
    citedByLabel(many, i18n),
    'archive.reason.andMore {"shown":"a.md, b.md, c.md","count":2}',
  );
  assert.equal(citedByLabel(["a.md"], i18n), "a.md");
  assert.equal(citedByLabel([], i18n), "");
});

/* --------------------------------------------------------------- settling a confirm */

/**
 * The finding: a confirm settling after the reader switched library used to write the
 * previous owner's notice, hand their job id to `onExecuted` and close the dialog the
 * current owner is reading. `settleConfirm` is the decision that write now has to pass.
 */

test("a late confirmation for a previous user is ignored", () => {
  const guard = makeGuard();
  const forAda = guard.next(); // Ada confirms an archive…
  guard.next(); // …and the reader switches to Bo's library while it is on the wire.

  assert.deepEqual(
    settleConfirm(guard, forAda, { kind: "queued", jobId: "job-1" }),
    { kind: "ignored" },
    "Ada's queued job does not put a notice on Bo's screen, nor close Bo's dialog",
  );
});

test("a late confirmation's FAILURES are ignored too", () => {
  const guard = makeGuard();
  const forAda = guard.next();
  guard.next();

  // Both refusals are writes: one paints the stale panel, the other an error line. Neither
  // belongs to the library now on screen.
  assert.deepEqual(settleConfirm(guard, forAda, { kind: "stale" }), { kind: "ignored" });
  assert.deepEqual(
    settleConfirm(guard, forAda, { kind: "failed", message: "boom" }),
    { kind: "ignored" },
  );
});

test("a confirm that is still the current one is applied, whatever it says", () => {
  const guard = makeGuard();
  const token = guard.next();

  assert.deepEqual(settleConfirm(guard, token, { kind: "queued", jobId: "job-1" }), {
    kind: "queued",
    jobId: "job-1",
  });
  assert.deepEqual(settleConfirm(guard, token, { kind: "stale" }), { kind: "stale" });
  assert.deepEqual(settleConfirm(guard, token, { kind: "failed", message: "boom" }), {
    kind: "failed",
    message: "boom",
  });
});

test("closing or unmounting retires a confirm as surely as a switch does", () => {
  const guard = makeGuard();
  const token = guard.next();
  guard.invalidate(); // Cancel, or the view unmounting: the confirm is aborted.

  assert.deepEqual(settleConfirm(guard, token, { kind: "queued", jobId: "job-1" }), {
    kind: "ignored",
  });
});

/* ------------------------------------------------ the unarchive direction's own copy */

/**
 * Restoring reads the same graph from the other side, and two of its facts have no spelling
 * in the archive direction: a source comes back because a page that is coming back cites it
 * (`restored_with_page`), and a source that is coming back is ALSO cited by pages that are
 * staying in the archive (`cited_by_archived`). The second is the one an owner needs: it says
 * what will keep citing this source from where it is, which is not a reason to stop and is
 * not the same as `still_cited`.
 */

const RESTORED_SOURCE = {
  kind: "source",
  ref: "src_aurora_standup",
  title: "Aurora standup",
  role: "cascade",
  selected: true,
  reason: { note: "restored_with_page" },
};

test("a source that travels with the page being restored says so", () => {
  assert.equal(reasonMessage(RESTORED_SOURCE, i18n), "archive.reason.restoredWithPage");
});

test("the archived pages that keep citing a source are named beside the note", () => {
  const both = {
    ...RESTORED_SOURCE,
    reason: {
      note: "restored_with_page",
      cited_by_archived: ["archive/work/aurora.md", "archive/threads/invitation.md"],
    },
  };
  assert.equal(
    reasonMessage(both, i18n),
    "archive.reason.restoredWithPage · archive.reason.citedByArchived " +
      '{"documents":"archive/work/aurora.md, archive/threads/invitation.md"}',
  );
});

test("the archived keepers stand alone when the note has nothing of its own to add", () => {
  // The planner reusing `still_cited` in the unarchive direction with no LIVE keepers must
  // not print "still cited by: " with an empty list — the archived keepers are the answer.
  const onlyArchived = {
    ...RESTORED_SOURCE,
    reason: { note: "still_cited", cited_by_live: [], cited_by_archived: ["archive/a.md"] },
  };
  assert.equal(
    reasonMessage(onlyArchived, i18n),
    'archive.reason.citedByArchived {"documents":"archive/a.md"}',
  );
  // …and a note this build does not know still renders nothing but the keepers.
  assert.equal(
    reasonMessage(
      {
        ...RESTORED_SOURCE,
        reason: { note: "some_future_code", cited_by_archived: ["archive/a.md"] },
      },
      i18n,
    ),
    'archive.reason.citedByArchived {"documents":"archive/a.md"}',
  );
});

test("both sides of a still-cited source are stated, live first", () => {
  const both = {
    ...KEPT_SOURCE,
    reason: {
      note: "still_cited",
      cited_by_live: ["work/products/orbit.md"],
      cited_by_archived: ["archive/work/aurora.md"],
    },
  };
  assert.equal(
    reasonMessage(both, i18n),
    'archive.reason.stillCited {"documents":"work/products/orbit.md"} · ' +
      'archive.reason.citedByArchived {"documents":"archive/work/aurora.md"}',
  );
});

test("an item with no archived keepers reads exactly as it did before the field existed", () => {
  assert.equal(reasonMessage(SEED_DOC, i18n), "archive.reason.seed");
  assert.equal(
    reasonMessage(
      { ...KEPT_SOURCE, reason: { ...KEPT_SOURCE.reason, cited_by_archived: [] } },
      i18n,
    ),
    'archive.reason.stillCited {"documents":"work/products/orbit.md, memory/topics/retrieval.md"}',
  );
});

/* --------------------------------------------------------------- an out-of-date plan */

/**
 * A plan is computed against one canonical HEAD, and the dialog learns that HEAD moved in
 * either of two ways: its own confirm is refused `409 stale`, or the proposal it is holding
 * already carries `status: "stale"` (the service moves the row when it refuses). The panel
 * offering "re-plan" must not depend on which one arrived.
 */

test("a confirm refused stale puts the plan out of date", () => {
  assert.equal(isStalePlan(PROPOSAL, true), true);
});

test("a proposal that already came back stale is out of date without any refusal", () => {
  assert.equal(isStalePlan({ ...PROPOSAL, status: "stale" }), true);
  assert.equal(isStalePlan({ ...PROPOSAL, status: "stale" }, false), true);
});

test("a fresh plan nobody refused is not out of date, and neither is no plan at all", () => {
  assert.equal(isStalePlan(PROPOSAL), false);
  assert.equal(isStalePlan(PROPOSAL, false), false);
  assert.equal(isStalePlan(null), false);
  assert.equal(isStalePlan(undefined, false), false);
  // Every other terminal status is a fact about what happened, not about the library moving.
  for (const status of ["proposed", "confirmed", "executed", "failed", "dropped"]) {
    assert.equal(isStalePlan({ ...PROPOSAL, status }), false, status);
  }
});

/* --------------------------------------------------- the record left at the live path */

/**
 * Archiving a page does not empty its path — it leaves a short record standing there, and
 * that record is LIVE knowledge the glance and recall will read. The dialog therefore
 * previews it before the owner confirms, and the two helpers below are the whole of that
 * preview: the facts line, and the reason line as the note is typed.
 *
 * The properties worth pinning are the ones a convenient implementation would get wrong: a
 * subject with no span must not print an empty one, a service that ships no facts at all
 * must not print a subject with zero of everything, and the note must be previewed exactly
 * as the confirm will send it — trimmed.
 */

const RECORD = {
  title: "Aurora",
  definition: "Aurora was the orbital telemetry product, retired after the Meridian merge.",
  span: ["2024-03-11", "2025-08-02"],
  claims: 42,
  sources: 7,
  volumes: 2,
  inbound: 3,
};

test("the facts line states the span first, then the four counts, in one order", () => {
  assert.equal(
    recordFactsLine(RECORD, i18n),
    [
      'archive.record.span {"from":"2024-03-11","to":"2025-08-02"}',
      'archive.record.claims {"count":42}',
      'archive.record.sources {"count":7}',
      'archive.record.volumes {"count":2}',
      'archive.record.inbound {"count":3}',
    ].join(" · "),
  );
});

/**
 * The REAL copy, both locales — because the point of this line is that the console and the
 * record page say one sentence rather than two.
 *
 * The bundle is loaded the way `i18n.test.mjs` loads one (inline the `defineMessages`
 * identity so the file is self-contained), and the interpolation here is the plain
 * `{name}` substitution the four facts keys need: none of them inflects for number any
 * more, because the record page it mirrors is written by a channel with no model in it and
 * cannot inflect either.
 */
const archiveMessages = await (async () => {
  const url = new URL("../src/i18n/archive.ts", import.meta.url);
  const text = (await readFile(url, "utf8")).replace(
    /^import \{[^}]*\} from "\.\/define";$/m,
    "const defineMessages = (bundle) => bundle;",
  );
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  const mod = await import(
    `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`
  );
  return mod.archive;
})();

const realI18n = (locale) => ({
  t: (key, params) =>
    Object.entries(params ?? {}).reduce(
      (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
      archiveMessages[locale][key],
    ),
});

test("the console's facts line is the record page's own line, word for word", () => {
  // The same numbers core renders in `test_archive_record.py`, and the same words: an owner
  // who confirms this preview and then opens the live path must not read two spellings of
  // one fact. Labelled numbers, the figure last — nothing here inflects (validation
  // B-S9-3), and `ledger claims` names WHICH count it is (O4).
  const facts = { span: ["2026-01-04", "2026-06-30"], claims: 2, sources: 1, volumes: 0, inbound: 1 };
  assert.equal(
    recordFactsLine(facts, realI18n("en")),
    "Covered 2026-01-04–2026-06-30 · ledger claims 2 · sources 1 · closed volumes 0 · " +
      "linked from live pages 1",
  );
  assert.equal(
    recordFactsLine(facts, realI18n("zh")),
    "覆盖 2026-01-04–2026-06-30 · 账本 claim 2 条 · 源 1 个 · 已结卷 0 卷 · 被活页链接 1 处",
  );
});

test("a subject with no span states the counts alone — never an empty span", () => {
  for (const span of [null, undefined, [], ["", ""], ["2024-03-11", ""]]) {
    const line = recordFactsLine({ ...RECORD, span }, i18n);
    assert.equal(line.includes("archive.record.span"), false, JSON.stringify(span));
    assert.ok(line.startsWith("archive.record.claims"), JSON.stringify(span));
  }
});

test("a count of zero is still a fact the record states", () => {
  const line = recordFactsLine(
    { span: null, claims: 0, sources: 0, volumes: 0, inbound: 0 },
    i18n,
  );
  assert.equal(
    line,
    [
      'archive.record.claims {"count":0}',
      'archive.record.sources {"count":0}',
      'archive.record.volumes {"count":0}',
      'archive.record.inbound {"count":0}',
    ].join(" · "),
  );
});

test("a row that states no facts at all says nothing, rather than zero of everything", () => {
  // The inventory hands this helper its own rows, and a service that predates the record
  // sends none of these fields. It must read as it did before they existed.
  assert.equal(recordFactsLine({}, i18n), "");
  assert.equal(recordFactsLine({ path: "archive/work/aurora.md" }, i18n), "");
  assert.equal(recordFactsLine(null, i18n), "");
  assert.equal(recordFactsLine(undefined, i18n), "");
  // One field present is one fact stated; the rest read as zero rather than as a gap.
  assert.equal(
    recordFactsLine({ claims: 5 }, i18n),
    [
      'archive.record.claims {"count":5}',
      'archive.record.sources {"count":0}',
      'archive.record.volumes {"count":0}',
      'archive.record.inbound {"count":0}',
    ].join(" · "),
  );
});

test("the reason preview quotes the note the confirm will send — trimmed", () => {
  assert.equal(
    recordReasonPreview(null, "  superseded by Meridian  ", true, i18n),
    'archive.record.reason {"note":"superseded by Meridian"}',
  );
  // The typed note is the newer fact: the planner computed its sentence before this
  // keystroke, and the confirm carries the note.
  assert.equal(
    recordReasonPreview(
      { reason: "Archived by the owner.", reason_default: "Archived Aurora." },
      " done with it ",
      true,
      i18n,
    ),
    'archive.record.reason {"note":"done with it"}',
  );
});

test("an untyped note previews the sentence the record WILL carry, never a blank", () => {
  // The execution always writes a reason — the note, the statement it was asked for in, or a
  // default sentence. A preview that showed nothing here would have the owner confirm a
  // record whose one editorial line they never read.
  assert.equal(
    recordReasonPreview(
      { reason: "Archived by the owner on 2026-09-04." },
      "",
      false,
      i18n,
    ),
    'archive.record.reason {"note":"Archived by the owner on 2026-09-04."}',
  );
  // Whitespace alone, in a field nobody touched, is still the untouched field.
  assert.equal(
    recordReasonPreview(
      { reason: "  from the owner's statement  " },
      "   \n  ",
      false,
      i18n,
    ),
    'archive.record.reason {"note":"from the owner\'s statement"}',
  );
  // A service that predates the field, and a record that states no reason at all: nothing to
  // preview, and nothing shown — exactly as it read before the field existed.
  assert.equal(recordReasonPreview(undefined, "", false, i18n), "");
  assert.equal(recordReasonPreview({}, "   ", false, i18n), "");
  assert.equal(recordReasonPreview({ reason: "  " }, "", false, i18n), "");
});

test("clearing a note previews the default sentence, not the note being deleted", () => {
  // THREE states over one string, and the middle one is the bug this pins. The plan carried
  // a note, so `reason` is that note; the owner selects it and deletes it; the confirm sends
  // `note: ""`, which REPLACES the plan's note with nothing, and the record then quotes the
  // sentence the job writes when nothing is typed. Falling back to `reason` here — which is
  // what an `edited`-blind preview does — would show them the one line that is now certain
  // not to be written.
  const record = {
    reason: "superseded by Meridian",
    reason_default: "Archived Aurora.",
  };
  // 1. typed: the note, trimmed exactly as the confirm trims it.
  assert.equal(
    recordReasonPreview(record, "  still superseded  ", true, i18n),
    'archive.record.reason {"note":"still superseded"}',
  );
  // 2. edited to empty: the default sentence.
  assert.equal(
    recordReasonPreview(record, "   ", true, i18n),
    'archive.record.reason {"note":"Archived Aurora."}',
  );
  // 3. untouched: the plan's own line, which is what a confirm mentioning no note quotes.
  assert.equal(
    recordReasonPreview(record, "", false, i18n),
    'archive.record.reason {"note":"superseded by Meridian"}',
  );
  // A service that predates `reason_default` cannot preview the clearing, and shows nothing
  // rather than the deleted note: the owner reads a blank line instead of a false one.
  assert.equal(recordReasonPreview({ reason: "gone" }, "  ", true, i18n), "");
});

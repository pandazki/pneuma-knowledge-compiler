import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_E2E_USER,
  SOURCE_V2_KINDS,
  resolveE2EConfig,
  selectJourneyKeys,
} from "./screenshots-config.mjs";

const ALL_JOURNEYS = ["00", "01", "02", "10", "14"];

test("screenshot config preserves the example full-run defaults", () => {
  assert.equal(DEFAULT_E2E_USER, "u-opc-lin");
  assert.deepEqual(resolveE2EConfig({}), {
    scope: "all",
    user: DEFAULT_E2E_USER,
  });
  assert.deepEqual(
    selectJourneyKeys(ALL_JOURNEYS, { scope: "all", requested: [] }),
    ALL_JOURNEYS,
  );
});

test("screenshot config reads and trims the v2 tenant and scope", () => {
  assert.deepEqual(
    resolveE2EConfig({
      E2E_SCOPE: " sources-v2 ",
      E2E_USER: " tenant-opc-84d-v2 ",
    }),
    {
      scope: "sources-v2",
      user: "tenant-opc-84d-v2",
    },
  );
});

test("blank E2E_USER keeps the example user", () => {
  assert.equal(resolveE2EConfig({ E2E_USER: "  " }).user, DEFAULT_E2E_USER);
});

test("sources-v2 runs only Sources and History and can be narrowed", () => {
  assert.deepEqual(
    selectJourneyKeys(ALL_JOURNEYS, {
      scope: "sources-v2",
      requested: [],
    }),
    ["01", "10"],
  );
  assert.deepEqual(
    selectJourneyKeys(ALL_JOURNEYS, {
      scope: "sources-v2",
      requested: ["10"],
    }),
    ["10"],
  );
  assert.throws(
    () =>
      selectJourneyKeys(ALL_JOURNEYS, {
        scope: "sources-v2",
        requested: ["02"],
      }),
    /outside E2E_SCOPE=sources-v2/,
  );
});

test("unknown scope fails before a browser is launched", () => {
  assert.throws(
    () => resolveE2EConfig({ E2E_SCOPE: "typo" }),
    /unsupported E2E_SCOPE/,
  );
});

test("sources-v2 requires one real source from every official family", () => {
  assert.deepEqual(
    SOURCE_V2_KINDS.map(({ kind, label, slug }) => ({ kind, label, slug })),
    [
      { kind: "meeting", label: "会议", slug: "meeting" },
      {
        kind: "document_library",
        label: "文档库",
        slug: "document-library",
      },
      { kind: "im", label: "即时消息", slug: "im" },
      { kind: "email", label: "电子邮件", slug: "email" },
    ],
  );
});

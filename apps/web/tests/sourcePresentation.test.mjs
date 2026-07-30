import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/views/sources/sourcePresentation.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2021",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { buildSourcePresentation: build } = await import(moduleUrl);

// The module takes its wording by injection (it cannot import lib/i18n: this test transpiles
// it on its own). Resolving every key to its fallback keeps the assertions about structure.
const i18n = { tOr: (_key, fallback) => fallback };
const buildSourcePresentation = (source) => build(source, i18n);

test("meeting presentation joins normalized segments to participants and blocks", () => {
  const result = buildSourcePresentation({
    kind: "meeting",
    created_at: "2026-07-28T09:00:00+08:00",
    meta: {
      started_at: "2026-07-28T09:00:00+08:00",
      ended_at: "2026-07-28T09:30:00+08:00",
      timezone: "Asia/Shanghai",
      owner_participant_ids: ["p1"],
      participants: [
        { participant_id: "p1", display_name: "林知远" },
        { participant_id: "p2", display_name: "陈澄" },
      ],
      agenda: ["确认范围"],
      segments: [
        {
          segment_id: "s1",
          speaker_id: "p1",
          started_at: "2026-07-28T09:00:01+08:00",
          ended_at: null,
        },
      ],
    },
    blocks: [
      {
        index: 0,
        // The wire format the textualizer emits: `ingest.owner_wrapped` + `ingest.turn_line`.
        text: "Owner (林知远): 先确认范围。",
        section_path: ["2026-07-28"],
      },
    ],
  });

  assert.equal(result.kind, "meeting");
  if (result.kind !== "meeting") return;
  assert.equal(result.durationMinutes, 30);
  assert.equal(result.participants[0]?.owner, true);
  assert.deepEqual(result.segments[0], {
    blockIndex: 0,
    segmentId: "s1",
    speakerId: "p1",
    speaker: "林知远",
    owner: true,
    startedAt: "2026-07-28T09:00:01+08:00",
    endedAt: null,
    text: "先确认范围。",
  });
});

test("document presentation preserves vault hierarchy, frontmatter and links", () => {
  const result = buildSourcePresentation({
    kind: "document_library",
    created_at: "2026-07-28T09:00:00+08:00",
    meta: {
      library_id: "vault-1",
      library_title: "工作库",
      path: "01-Projects/Orion/项目总览.md",
      frontmatter: { status: "active", owner: "林知远" },
      tags: ["project/orion"],
      links: [{ target: "02-Areas/独立开发", label: null, embedded: false }],
      modified_at: "2026-07-28T10:00:00+08:00",
    },
    blocks: [
      {
        index: 0,
        text: "首期只做引用可回放。",
        section_path: ["项目总览", "范围"],
      },
    ],
  });

  assert.equal(result.kind, "document_library");
  if (result.kind !== "document_library") return;
  assert.deepEqual(result.pathParts, ["01-Projects", "Orion", "项目总览.md"]);
  assert.equal(result.frontmatter.status, "active");
  assert.equal(result.links[0]?.target, "02-Areas/独立开发");
});

test("IM presentation resolves senders, thread replies and reactions", () => {
  const result = buildSourcePresentation({
    kind: "im",
    created_at: "2026-07-28T09:00:00+08:00",
    meta: {
      conversation_type: "channel",
      owner_user_ids: ["U1"],
      users: [
        { user_id: "U1", display_name: "林知远" },
        { user_id: "U2", display_name: "陈澄" },
      ],
      messages: [
        {
          message_id: "m2",
          sender_id: "U2",
          sent_at: "2026-07-28T11:00:00+08:00",
          thread_id: "m1",
          reactions: [{ name: "eyes", count: 2 }],
        },
      ],
    },
    blocks: [
      {
        index: 0,
        // Full-width colon on purpose: a block normalised by an older build still splits.
        text: "陈澄：字段表发你了。",
        section_path: ["2026-07-28"],
      },
    ],
  });

  assert.equal(result.kind, "im");
  if (result.kind !== "im") return;
  assert.equal(result.messages[0]?.speaker, "陈澄");
  assert.equal(result.messages[0]?.isReply, true);
  assert.deepEqual(result.messages[0]?.reactions, [{ name: "eyes", count: 2 }]);
});

test("email presentation separates RFC-like headers from the citable body", () => {
  const result = buildSourcePresentation({
    kind: "email",
    created_at: "2026-07-28T09:00:00+08:00",
    meta: {
      owner_addresses: ["lin@example.dev"],
      messages: [
        {
          message_id: "<m1@example.dev>",
          sent_at: "2026-07-28T12:00:00+08:00",
          from: { address: "lin@example.dev", display_name: "林知远" },
          to: [{ address: "client@example.dev", display_name: "陈澄" }],
          cc: [],
          subject: "试点",
          in_reply_to: null,
          references: [],
          attachments: [
            {
              filename: "proposal.pdf",
              content_type: "application/pdf",
              size_bytes: 1024,
            },
          ],
        },
      ],
    },
    blocks: [
      {
        index: 0,
        // `ingest.owner_wrapped` / `ingest.email.subject` / `ingest.email.attachments`.
        text:
          "Owner (林知远 <lin@example.dev>) → 陈澄 <client@example.dev>\n" +
          "Subject: 试点\n" +
          "方案见附件。\n" +
          "Attachments: proposal.pdf (application/pdf, 1024 bytes)",
        section_path: ["2026-07-28"],
      },
    ],
  });

  assert.equal(result.kind, "email");
  if (result.kind !== "email") return;
  assert.equal(result.messages[0]?.owner, true);
  assert.equal(result.messages[0]?.body, "方案见附件。");
  assert.equal(result.messages[0]?.attachments[0]?.filename, "proposal.pdf");
});

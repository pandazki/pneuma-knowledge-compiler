export const DEFAULT_E2E_USER = "u-opc-lin";

export const SOURCE_V2_KINDS = Object.freeze([
  Object.freeze({ kind: "meeting", label: "会议", slug: "meeting" }),
  Object.freeze({
    kind: "document_library",
    label: "文档库",
    slug: "document-library",
  }),
  Object.freeze({ kind: "im", label: "即时消息", slug: "im" }),
  Object.freeze({ kind: "email", label: "电子邮件", slug: "email" }),
]);

const SOURCE_V2_JOURNEYS = Object.freeze(["01", "10"]);
const SUPPORTED_SCOPES = new Set(["all", "sources-v2"]);

export function resolveE2EConfig(env = process.env) {
  const scope = env.E2E_SCOPE?.trim() || "all";
  if (!SUPPORTED_SCOPES.has(scope)) {
    throw new Error(
      `unsupported E2E_SCOPE=${JSON.stringify(scope)}; expected "all" or "sources-v2"`,
    );
  }
  return {
    scope,
    user: env.E2E_USER?.trim() || DEFAULT_E2E_USER,
  };
}

export function selectJourneyKeys(
  allJourneyKeys,
  { scope, requested },
) {
  const available = new Set(allJourneyKeys);
  const requestedKeys = requested.filter((key) => available.has(key));

  if (scope === "all") {
    return requested.length === 0
      ? [...allJourneyKeys]
      : allJourneyKeys.filter((key) => requestedKeys.includes(key));
  }

  const outsideScope = requested.filter(
    (key) => !SOURCE_V2_JOURNEYS.includes(key),
  );
  if (outsideScope.length > 0) {
    throw new Error(
      `journey ${outsideScope.join(", ")} is outside E2E_SCOPE=sources-v2; expected 01 or 10`,
    );
  }
  return requested.length === 0
    ? [...SOURCE_V2_JOURNEYS]
    : SOURCE_V2_JOURNEYS.filter((key) => requestedKeys.includes(key));
}

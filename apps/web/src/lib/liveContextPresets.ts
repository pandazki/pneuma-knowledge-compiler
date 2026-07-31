/**
 * Preset workstreams for the Live Context bench, so the project owner can click instead of
 * type. The synthetic conversations model a project owner preparing a public
 * release. Two carry an explicit expectation; the third exists because silence is the
 * feature's steady state and a bench that only shows firing cases is misleading.
 *
 * `expect` is a note to the human reading the page, not a contract — whether a card
 * actually fires depends on what the selected user's knowledge base contains. A preset
 * against an empty KB is correctly silent: the citation gate drops any suggestion that cannot
 * point at a real source.
 *
 * The copy is synthetic UI material rather than data, so it is translated — but this table is
 * a module-level constant, evaluated once at import. Rendering it through `tx()` here would
 * freeze whichever locale happened to be active at import time and never follow the header
 * toggle. So the preset carries message KEYS and the view resolves them with `t()` on every
 * render. The type-only import keeps this module free of runtime imports too, which matters
 * for the standalone-transpile test pattern.
 */
import type { MessageKey } from "./i18n";

export interface PresetTurn {
  speakerKey: MessageKey;
  textKey: MessageKey;
  role: "owner" | "other";
}

export interface LiveContextPreset {
  key: string;
  labelKey: MessageKey;
  /** what this scenario is meant to probe, in one line */
  summaryKey: MessageKey;
  /** the expected outcome, for eyeballing against what actually lands */
  expectKey: MessageKey;
  turns: PresetTurn[];
}

const OWNER: MessageKey = "liveContext.preset.speaker.owner";
const COLLABORATOR: MessageKey = "liveContext.preset.speaker.collaborator";
const FRIEND: MessageKey = "liveContext.preset.speaker.friend";

export const LIVE_CONTEXT_PRESETS: LiveContextPreset[] = [
  {
    key: "release-license",
    labelKey: "liveContext.preset.releaseLicense.label",
    summaryKey: "liveContext.preset.releaseLicense.summary",
    expectKey: "liveContext.preset.releaseLicense.expect",
    turns: [
      {
        speakerKey: COLLABORATOR,
        role: "other",
        textKey: "liveContext.preset.releaseLicense.turn1",
      },
      {
        speakerKey: OWNER,
        role: "owner",
        textKey: "liveContext.preset.releaseLicense.turn2",
      },
      {
        speakerKey: COLLABORATOR,
        role: "other",
        textKey: "liveContext.preset.releaseLicense.turn3",
      },
    ],
  },
  {
    key: "release-progress",
    labelKey: "liveContext.preset.releaseProgress.label",
    summaryKey: "liveContext.preset.releaseProgress.summary",
    expectKey: "liveContext.preset.releaseProgress.expect",
    turns: [
      {
        speakerKey: COLLABORATOR,
        role: "other",
        textKey: "liveContext.preset.releaseProgress.turn1",
      },
      {
        speakerKey: OWNER,
        role: "owner",
        textKey: "liveContext.preset.releaseProgress.turn2",
      },
      {
        speakerKey: COLLABORATOR,
        role: "other",
        textKey: "liveContext.preset.releaseProgress.turn3",
      },
    ],
  },
  {
    key: "smalltalk",
    labelKey: "liveContext.preset.smalltalk.label",
    summaryKey: "liveContext.preset.smalltalk.summary",
    expectKey: "liveContext.preset.smalltalk.expect",
    turns: [
      { speakerKey: FRIEND, role: "other", textKey: "liveContext.preset.smalltalk.turn1" },
      { speakerKey: OWNER, role: "owner", textKey: "liveContext.preset.smalltalk.turn2" },
      { speakerKey: FRIEND, role: "other", textKey: "liveContext.preset.smalltalk.turn3" },
    ],
  },
];

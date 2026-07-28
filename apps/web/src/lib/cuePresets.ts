/**
 * Preset transcripts for the AI-cue bench, so the project owner can click instead of
 * type. The synthetic conversations model a solo developer preparing an open-source
 * release. Two carry an explicit expectation; the third exists because silence is the
 * feature's steady state and a bench that only shows firing cases is misleading.
 *
 * `expect` is a note to the human reading the page, not a contract — whether a card
 * actually fires depends on what the selected user's knowledge base contains. A preset
 * against an empty KB is correctly silent: the citation gate drops any cue that cannot
 * point at a real source.
 */

export interface PresetTurn {
  speaker: string;
  text: string;
  role: "owner" | "other";
}

export interface CuePreset {
  key: string;
  label: string;
  /** what this scenario is meant to probe, in one line */
  summary: string;
  /** the expected outcome, for eyeballing against what actually lands */
  expect: string;
  turns: PresetTurn[];
}

export const CUE_PRESETS: CuePreset[] = [
  {
    key: "release-license",
    label: "开源许可",
    summary: "讨论里出现一个许可证概念，本人没有追问，系统应主动补充它的含义",
    expect: "期望 concept 卡（概念解释）",
    turns: [
      {
        speaker: "协作者",
        role: "other",
        text: "发布前还要确认依赖许可证兼容性，特别是 copyleft 的传递范围。",
      },
      {
        speaker: "林知远",
        role: "owner",
        text: "我先把依赖清单和生成代码的归属整理出来。",
      },
      {
        speaker: "协作者",
        role: "other",
        text: "README 里也最好解释一下 permissive license 和 copyleft 的区别。",
      },
    ],
  },
  {
    key: "release-progress",
    label: "发布进度",
    summary: "讨论里出现一个知识库能直接回答的发布问题，系统应把事实递上来",
    expect: "期望 fact 卡（事实问答）",
    turns: [
      {
        speaker: "协作者",
        role: "other",
        text: "Atlas 的公开预览版现在推进到哪一步了？",
      },
      {
        speaker: "林知远",
        role: "owner",
        text: "我记得已经跑过本地导出，但具体还缺哪一道发布检查一时想不起来。",
      },
      {
        speaker: "协作者",
        role: "other",
        text: "那你确认一下知识库里记录的门禁，别把未脱敏的实验材料打进公开包。",
      },
    ],
  },
  {
    key: "smalltalk",
    label: "闲聊（对照组）",
    summary: "没有任何值得提词的内容——四道闸门应当把一切挡掉",
    expect: "期望 0 张卡：沉默是正常工作状态，不是故障",
    turns: [
      { speaker: "朋友", role: "other", text: "今天风挺大，出门走一圈比坐着舒服。" },
      { speaker: "林知远", role: "owner", text: "是啊，我准备工作告一段落就去散会儿步。" },
      { speaker: "朋友", role: "other", text: "回来吃什么？楼下那家新开的还没试过。" },
    ],
  },
];

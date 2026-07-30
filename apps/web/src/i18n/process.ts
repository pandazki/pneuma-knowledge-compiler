import { defineMessages } from "./define";

/**
 * The compile-job ledger. Job ids, kinds, `detail` and refs are server data and stay
 * untranslated; everything here is the page's own account of them.
 *
 * `process.status.*` is keyed by the job status the API returns. An unknown status renders as
 * its raw machine name (see ProcessView's `statusText`), so a new pipeline state shows up
 * rather than vanishing.
 */
export const process = defineMessages({
  zh: {
    "process.description": "compile job 账页：每次编译一行——状态、来源、耗时与落版 ref。",

    "process.status.compiled": "已编译",
    "process.status.failed": "失败",
    "process.status.running": "运行中",
    "process.status.queued": "排队中",

    "process.noUser.title": "未选择用户",
    "process.noUser.description": "先在顶栏选择一个 user_id，再查看它的编译任务账页。",

    "process.compile.action": "触发编译",
    "process.compile.hint": "把未消化的 source 入 compile 队列",
    "process.compile.readOnlyHint": "历史快照为只读",
    "process.compile.failed": "触发编译失败",

    "process.readOnly.body": "正在查看历史快照，触发编译已禁用；切回 HEAD 后才能操作。",

    "process.patch.prefix": "此 patch",
    "process.patch.suffix": "在「版本 History」查看。",
    "process.patch.goHistory": "去版本 History",

    "process.enqueued.title": "已入队",
    "process.enqueued.none": "没有待编译的 source（全部已消化）。",

    "process.loadFailed": "加载 job 账页失败",

    "process.empty.title": "尚无编译任务",
    "process.empty.description": "先在「导入 Ingest」添加原料，再回到这里触发编译。",
    "process.empty.action": "去导入",

    "process.row.created": "创建",
    "process.row.completed": "完成",
    "process.jobNoun": "个 job",
  },
  en: {
    "process.description":
      "The compile-job ledger: one line per compile — status, sources, duration and the ref it landed on.",

    "process.status.compiled": "Compiled",
    "process.status.failed": "Failed",
    "process.status.running": "Running",
    "process.status.queued": "Queued",

    "process.noUser.title": "No user selected",
    "process.noUser.description":
      "Choose a user_id in the top bar to see its compile-job ledger.",

    "process.compile.action": "Run a compile",
    "process.compile.hint": "Queue every undigested source for compilation",
    "process.compile.readOnlyHint": "A historical snapshot is read-only",
    "process.compile.failed": "Could not start the compile",

    "process.readOnly.body":
      "You are viewing a historical snapshot, so running a compile is disabled; switch back to HEAD first.",

    "process.patch.prefix": "This patch",
    "process.patch.suffix": "is shown under History.",
    "process.patch.goHistory": "Go to History",

    "process.enqueued.title": "Queued",
    "process.enqueued.none": "No source is waiting to be compiled (all digested).",

    "process.loadFailed": "Could not load the job ledger",

    "process.empty.title": "No compile jobs yet",
    "process.empty.description":
      "Add material under Ingest first, then come back here and run a compile.",
    "process.empty.action": "Go to Ingest",

    "process.row.created": "created",
    "process.row.completed": "completed",
    "process.jobNoun": "jobs",
  },
});

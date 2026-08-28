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
    "process.noUser.description": "在右上角选择一个 user_id，再查看它的编译任务账页。",

    "process.compile.action": "触发编译",
    "process.compile.hint": "把未消化的 source 入 compile 队列",
    "process.compile.readOnlyHint": "历史快照为只读",
    "process.compile.failed": "触发编译失败",

    "process.readOnly.body": "正在查看历史快照，触发编译已禁用；切回 HEAD 后才能操作。",

    "process.locate.searching": "正在向后翻页定位 job {job}…",
    "process.locate.notFound":
      "job {job} 不在最近 {count} 条里。它可能更早，或已不在本用户的账页上。",
    "process.job.openSource": "打开这条来源的校样",
    "process.job.sourceUntitled": "（标题加载中）",

    "process.patch.prefix": "此版次",
    "process.patch.suffix": "在「版次 History」查看。",
    "process.patch.goHistory": "去版次 History",

    "process.enqueued.title": "已入队",
    "process.enqueued.none": "没有待编译的 source（全部已消化）。",

    "process.loadFailed": "加载 job 账页失败",

    "process.empty.title": "尚无编译任务",
    "process.empty.description": "先在「导入 Ingest」添加来源，再回到这里触发编译。",
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
      "Choose a user_id in the top right to see its compile-job ledger.",

    "process.compile.action": "Run a compile",
    "process.compile.hint": "Queue every undigested source for compilation",
    "process.compile.readOnlyHint": "A historical snapshot is read-only",
    "process.compile.failed": "Could not start the compile",

    "process.readOnly.body":
      "You are viewing a historical snapshot, so running a compile is disabled; switch back to HEAD first.",

    "process.locate.searching": "Paging forward to find job {job}…",
    "process.locate.notFound":
      "Job {job} is not among the most recent {count}. It may be older, or no longer on this user's ledger.",
    "process.job.openSource": "Open this source's galley",
    "process.job.sourceUntitled": "(title loading)",

    "process.patch.prefix": "This edition",
    "process.patch.suffix": "is shown under History.",
    "process.patch.goHistory": "Go to History",

    "process.enqueued.title": "Queued",
    "process.enqueued.none": "No source is waiting to be compiled (all digested).",

    "process.loadFailed": "Could not load the job ledger",

    "process.empty.title": "No compile jobs yet",
    "process.empty.description":
      "Add a source under Ingest first, then come back here and run a compile.",
    "process.empty.action": "Go to Ingest",

    "process.row.created": "created",
    "process.row.completed": "completed",
    "process.jobNoun": "jobs",
  },
});

import { defineMessages } from "./define";

/**
 * Journal event names, keyed by the event `type` the canonical projection emits. An unknown
 * type falls back to the raw type string (see `lib/events.ts::eventMeta`), so a new event
 * shows up as its machine name rather than disappearing.
 */
export const events = defineMessages({
  zh: {
    "event.job_created": "Job 创建",
    "event.job_planned": "Job 规划",
    "event.driver_started": "Driver 启动",
    "event.driver_finished": "Driver 完成",
    "event.gate_checked": "Gate 校验通过",
    "event.gate_rejected": "Gate 拒绝",
    "event.gate_repair_retry": "Gate 修复重试",
    "event.patch_committed": "版次提交",
    "event.job_failed": "Job 失败",
    "event.bundle_published": "Bundle 发布",
    "event.viz_exported": "Viz 导出",
    "event.bypass_reconciled": "旁路收编",
    "event.rollback": "回滚",
    "event.job_replanned": "Job 重规划",
    "event.limits_exceeded": "超限告警",
  },
  en: {
    "event.job_created": "Job created",
    "event.job_planned": "Job planned",
    "event.driver_started": "Driver started",
    "event.driver_finished": "Driver finished",
    "event.gate_checked": "Gate passed",
    "event.gate_rejected": "Gate rejected",
    "event.gate_repair_retry": "Gate repair retry",
    "event.patch_committed": "Edition committed",
    "event.job_failed": "Job failed",
    "event.bundle_published": "Bundle published",
    "event.viz_exported": "Viz exported",
    "event.bypass_reconciled": "Bypass reconciled",
    "event.rollback": "Rollback",
    "event.job_replanned": "Job replanned",
    "event.limits_exceeded": "Limits exceeded",
  },
});

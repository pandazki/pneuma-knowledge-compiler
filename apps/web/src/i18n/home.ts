import { defineMessages } from "./define";

/**
 * The home face: the library switcher that replaces the tenant picker on a personal edition,
 * and the Home view's health page (docs/design/single-machine-edition.md §4.12, §10).
 *
 * The vocabulary is the edition's own — 「本机」, a library by name, an engine as a process —
 * and deliberately not the library's. Nothing here appears on a project deployment, because
 * nothing here is rendered when the home probe answered 404.
 */
export const home = defineMessages({
  zh: {
    "nav.group.machine": "本机",
    "nav.view.home": "本机 Home",
    // The three model-lane entries keep their place in the contents; this is the mark they
    // carry when the machine says this library has no key to run them with.
    "nav.modelLane.badge": "密钥",
    "nav.modelLane.title": "这一页要调模型通道，本机这个知识库还没配置 API 密钥",

    "modelLane.notice.what": "这一页调用引擎的模型通道，是用来质检知识库答得怎么样的工具。",
    "modelLane.notice.title": "没有密钥，这个质检工具用不了",
    "modelLane.notice.why": "本机这个知识库没有配置 API 密钥，模型通道跑不起来。配置密钥：",
    "modelLane.notice.retrieval": "日常检索不在这里：让管家去读这个知识库。",
    "modelLane.notice.goSteward": "去管家 Steward",

    "home.picker.choose": "选择知识库",
    "home.picker.switchAria": "切换知识库",
    "home.picker.filterPlaceholder": "输入知识库名称…",
    "home.picker.empty": "没有匹配的知识库",
    "home.picker.engineDown": "引擎未运行",

    "home.title": "本机",
    "home.description": "这台机器上的中间件、引擎与知识库——只读的一眼。",
    "home.absent": "这个控制台不是由单机版引擎提供的，没有可看的本机状态。",

    "home.section.machine": "机器",
    "home.section.libraries": "知识库",

    "home.docker": "Docker",
    "home.docker.reachable": "可达",
    "home.docker.unreachable": "不可达",
    "home.docker.unknown": "未探测",

    "home.service.postgres": "Postgres",
    "home.service.qdrant": "Qdrant",
    "home.service.meili": "Meilisearch",
    "home.service.rustfs": "RustFS",
    "home.service.up": "运行中",
    "home.service.down": "已停止",
    "home.service.unknown": "未探测",

    "home.path": "位置",
    "home.version": "版本",
    // A port and a pid are labels beside a raw number, never interpolated: `{port}` would
    // be grouped as a cardinal count and print 「20,001」.
    "home.port": "端口",
    "home.pid": "pid",

    "home.library.current": "当前",
    "home.library.engineUp": "引擎运行中",
    "home.library.engineDown": "引擎未运行",
    "home.library.uptime": "已运行",
    "home.library.queue": "队列",
    "home.library.queuePending": "{pending} 待处理",
    "home.library.queueFailed": "{failed} 失败",
    "home.library.queueFailedByKind": "{failed} 失败（{kinds}）",
    "home.library.queueSucceeded": "{succeeded} 成功",
    "home.library.queueClear": "无积压",
    "home.library.queueUnknown": "引擎未运行，读不到队列",
    "home.library.lastCompile": "最近编译",
    "home.library.key": "密钥",
    "home.library.keyPresent": "已配置",
    "home.library.keyMissing": "未配置",
    "home.library.keyModelLanes": "模型通道：质检工具，无密钥即关闭",
    "home.library.skill": "skill 包",
    "home.library.skillFresh": "最新",
    "home.library.skillStale": "已过期 · 需重新渲染",
    "home.library.skillUnknown": "未渲染",
    "home.library.canonical": "正本 HEAD",
    "home.library.engineDir": "引擎目录",
    "home.library.lastUsed": "最近使用",
    "home.library.steps": "启动步骤",
    "home.library.stepsDone": "{done} / {total}",
    "home.library.none": "这台机器上还没有知识库。",

    "home.step.infra": "基础设施",
    "home.step.credentials": "密钥",
    "home.step.profile": "画像",
    "home.step.skill": "skill 包",
    "home.step.first_compile": "首次编译",
    "home.step.pending": "未完成",
  },
  en: {
    "nav.group.machine": "This machine",
    "nav.view.home": "Home",
    "nav.modelLane.badge": "key",
    "nav.modelLane.title": "This page calls a model lane, and this library has no API key in this home",

    "modelLane.notice.what":
      "This page calls the engine's model lanes — a tool for quality-testing how well the library answers.",
    "modelLane.notice.title": "No key, so this quality tool cannot run",
    "modelLane.notice.why":
      "This library has no API key in this home, so the model lanes cannot run. Set one with:",
    "modelLane.notice.retrieval": "Day-to-day retrieval is not here: let the Steward read the library.",
    "modelLane.notice.goSteward": "Open the Steward",

    "home.picker.choose": "Choose a library",
    "home.picker.switchAria": "Switch library",
    "home.picker.filterPlaceholder": "Type a library name…",
    "home.picker.empty": "No matching library",
    "home.picker.engineDown": "engine not running",

    "home.title": "This machine",
    "home.description":
      "The middleware, the engines and the libraries on this machine — a read-only glance.",
    "home.absent": "This console is not served by a personal-edition engine; there is no home to show.",

    "home.section.machine": "Machine",
    "home.section.libraries": "Libraries",

    "home.docker": "Docker",
    "home.docker.reachable": "reachable",
    "home.docker.unreachable": "unreachable",
    "home.docker.unknown": "not probed",

    "home.service.postgres": "Postgres",
    "home.service.qdrant": "Qdrant",
    "home.service.meili": "Meilisearch",
    "home.service.rustfs": "RustFS",
    "home.service.up": "up",
    "home.service.down": "down",
    "home.service.unknown": "not probed",

    "home.path": "Home",
    "home.version": "Version",
    "home.port": "port",
    "home.pid": "pid",

    "home.library.current": "current",
    "home.library.engineUp": "engine up",
    "home.library.engineDown": "engine not running",
    "home.library.uptime": "up",
    "home.library.queue": "Queue",
    "home.library.queuePending": "{pending} pending",
    "home.library.queueFailed": "{failed} failed",
    "home.library.queueFailedByKind": "{failed} failed ({kinds})",
    "home.library.queueSucceeded": "{succeeded} succeeded",
    "home.library.queueClear": "clear",
    "home.library.queueUnknown": "engine down — no queue to read",
    "home.library.lastCompile": "Last compile",
    "home.library.key": "Key",
    "home.library.keyPresent": "present",
    "home.library.keyMissing": "missing",
    "home.library.keyModelLanes": "model lanes: quality tools, off without a key",
    "home.library.skill": "Skill",
    "home.library.skillFresh": "fresh",
    "home.library.skillStale": "stale · re-render it",
    "home.library.skillUnknown": "not rendered",
    "home.library.canonical": "Canonical HEAD",
    "home.library.engineDir": "Engine dir",
    "home.library.lastUsed": "Last used",
    "home.library.steps": "Setup",
    "home.library.stepsDone": "{done} / {total}",
    "home.library.none": "No libraries on this machine yet.",

    "home.step.infra": "infra",
    "home.step.credentials": "credentials",
    "home.step.profile": "profile",
    "home.step.skill": "skill",
    "home.step.first_compile": "first compile",
    "home.step.pending": "not done",
  },
});

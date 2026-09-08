export type Locale = 'en' | 'zh-CN';

const en = {
  ask: 'Ask the library…', search: 'Search', settings: 'Settings', back: 'Library', quit: 'Quit',
  checked: 'Checked {time}', applying: 'Applying…', unavailable: 'Status unavailable',
  dismiss: 'Dismiss message', language: 'Language', systemLanguage: 'Follow system',
  noLibrary: 'No library yet', pasteHint: 'Paste this into your coding agent:',
  setupPrompt: 'Help me set up a personal knowledge library with pkchome, using my own data.',
  chooseLibrary: 'Choose a library', chooseHelp: 'Choose the current library in Settings to search it.',
  emptyLibraries: 'Ask your coding agent to create your first library with pkchome.',
  engine: 'Engine', queue: 'Queue', lastCompile: 'Last compile', sync: 'Sync', key: 'Key', skill: 'Skill',
  up: 'up', down: 'off', unknown: '—', never: 'never', noneYet: 'None yet',
  present: 'present', absent: 'absent', fresh: 'fresh', stale: 'stale',
  done: 'done', pending: 'pending', failed: 'failed', watching: 'watching', held: 'held',
  justNow: 'just now', minuteAgo: '{count} min ago', hourAgo: '{count} hr ago', dayAgo: '{count}d ago',
  start: 'Start', stop: 'Stop', restart: 'Restart', syncNow: 'Sync now', syncing: 'Syncing…',
  openConsole: 'Open console', allLibraries: 'Engine actions apply to all libraries.',
  started: 'Home started', stopped: 'Home stopped', restarted: 'Home restarted', synced: 'Sync requested',
  engineOff: 'The engine is off —', startIt: 'start it', processWaiting: 'Process running; waiting for its port.',
  searching: 'Searching {name}…', answer: 'Search answer', evidence: 'Sources',
  noEvidence: 'No direct evidence returned.', searchHint: 'Citations open the evidence in your console.',
  citation: 'Open source {number}', derivedSummary: 'Derived episode summary',
  detailedUnavailable: 'Detailed health is unavailable.', detailedOffline: 'Detailed health returns when the engine starts.',
  rewritten: '{count} rewritten sessions need review.', skipped: '{count} skipped; inspect a dry sync in the terminal.',
  machine: 'Machine', healthGrey: 'Set up your home', healthGreen: 'All engines ready',
  healthAmber: 'Needs attention', healthRed: 'Docker is unreachable', serviceUp: 'up', serviceDown: 'down',
  setup: 'Setup progress', infra: 'Infra', credentials: 'Key', profile: 'Profile', firstCompile: 'Compile',
  complete: 'complete', incomplete: 'not completed', current: 'Current library',
  embeddingKey: 'Embedding key', credentialName: 'Credential name', pasteKey: 'Paste your key', save: 'Save',
  keyHelp: 'Use the credential name required by your embedding provider.', keySaved: 'Embedding key saved',
  keySaveFailed: 'Key could not be saved. Check the credential name and try again.',
  sharedKey: 'Shared across your libraries', semantic: 'Semantic retrieval', retrievalSaved: 'Retrieval preference saved',
  unattended: 'Compile unattended', unattendedHelp: 'Off keeps jobs for your session; changing this restarts the engine.',
  unattendedSaved: 'Compile preference saved · engine restarted', backend: 'Compile backend', backendSaved: 'Compile backend saved',
  modelApi: 'Model API', autoSync: 'Automatic sync', autoSyncSaved: 'Sync preference saved',
  interval: 'Interval (min)', intervalHelp: 'Sync schedule applies to all libraries.', intervalSaved: 'Sync interval saved',
  minuteUnit: 'min', decreaseInterval: 'Decrease sync interval', increaseInterval: 'Increase sync interval',
  directories: 'Watched directories', directoryHint: 'Add a project to bring its coding sessions into this library.',
  directoryPlaceholder: '~/projects/notes', remove: 'remove', removeDirectory: 'Remove {path}',
  removed: 'Directory removed', add: 'Add', added: 'Directory added', login: 'Launch at login',
  on: 'on', off: 'off', switched: 'Switched to {name}', choosePreferences: 'Choose a library to set retrieval and compile preferences.',
  loadFailed: 'PKC could not load its cached state: {error}',
} as const;

const zh: Record<keyof typeof en, string> = {
  ask: '问问这座库…', search: '搜索', settings: '设置', back: '知识库', quit: '退出',
  checked: '检查于 {time}', applying: '正在应用…', unavailable: '状态暂不可用',
  dismiss: '关闭消息', language: '语言', systemLanguage: '跟随系统',
  noLibrary: '还没有知识库', pasteHint: '将这句话粘贴给你的编程代理：',
  setupPrompt: '请用 pkchome 帮我以自己的数据建立一个个人知识库。',
  chooseLibrary: '选择知识库', chooseHelp: '请在设置中选择当前知识库，再开始搜索。',
  emptyLibraries: '请让编程代理用 pkchome 创建你的第一个知识库。',
  engine: '引擎', queue: '队列', lastCompile: '最近编译', sync: '同步', key: '密钥', skill: 'skill 包',
  up: '运行', down: '已停止', unknown: '—', never: '尚未同步', noneYet: '尚未编译',
  present: '已配置', absent: '未配置', fresh: '最新', stale: '待更新',
  done: '完成', pending: '待处理', failed: '失败', watching: '监看', held: '暂存',
  justNow: '刚刚', minuteAgo: '{count} 分钟前', hourAgo: '{count} 小时前', dayAgo: '{count} 天前',
  start: '启动', stop: '停止', restart: '重启', syncNow: '立即同步', syncing: '同步中…',
  openConsole: '打开控制台', allLibraries: '引擎操作适用于所有知识库。',
  started: '知识库已启动', stopped: '知识库已停止', restarted: '知识库已重启', synced: '已请求同步',
  engineOff: '引擎已停止，', startIt: '启动它', processWaiting: '进程已运行，正在等待端口。',
  searching: '正在搜索 {name}…', answer: '搜索回答', evidence: '来源',
  noEvidence: '未返回直接证据。', searchHint: '点击引用，在控制台中查看证据。',
  citation: '打开来源 {number}', derivedSummary: '派生片段摘要',
  detailedUnavailable: '详细状态暂不可用。', detailedOffline: '引擎启动后可查看详细状态。',
  rewritten: '{count} 个重写会话需要检查。', skipped: '已跳过 {count} 项；请在终端中预演同步以查看详情。',
  machine: '本机', healthGrey: '请先配置知识库', healthGreen: '所有引擎已就绪',
  healthAmber: '有服务需要检查', healthRed: 'Docker 无法连接', serviceUp: '运行', serviceDown: '已停止',
  setup: '配置进度', infra: '服务', credentials: '密钥', profile: '档案', firstCompile: '编译',
  complete: '已完成', incomplete: '未完成', current: '当前知识库',
  embeddingKey: '嵌入密钥', credentialName: '凭据名称', pasteKey: '粘贴密钥', save: '保存',
  keyHelp: '填写嵌入服务商要求的凭据名称。', keySaved: '嵌入密钥已保存',
  keySaveFailed: '密钥未能保存。请检查凭据名称后重试。',
  sharedKey: '所有知识库共享', semantic: '语义检索', retrievalSaved: '检索偏好已保存',
  unattended: '无人值守编译', unattendedHelp: '关闭后任务留待你的会话处理；更改此项会重启引擎。',
  unattendedSaved: '编译偏好已保存 · 引擎已重启', backend: '编译后端', backendSaved: '编译后端已保存',
  modelApi: '模型 API', autoSync: '自动同步', autoSyncSaved: '同步偏好已保存',
  interval: '间隔（分钟）', intervalHelp: '同步周期适用于所有知识库。', intervalSaved: '同步间隔已保存',
  minuteUnit: '分钟', decreaseInterval: '缩短同步间隔', increaseInterval: '延长同步间隔',
  directories: '监看目录', directoryHint: '添加项目目录，将其中的编程会话同步到这座库。',
  directoryPlaceholder: '~/projects/notes', remove: '移除', removeDirectory: '移除 {path}',
  removed: '目录已移除', add: '添加', added: '目录已添加', login: '登录时启动',
  on: '开', off: '关', switched: '已切换到 {name}', choosePreferences: '选择知识库以设置检索和编译偏好。',
  loadFailed: 'PKC 无法载入缓存状态：{error}',
};

export type Message = keyof typeof en;
export function t(locale: Locale, key: Message, values: Record<string, string | number> = {}): string {
  const message = (locale === 'zh-CN' ? zh : en)[key];
  return message.replace(/\{(\w+)\}/g, (token, name: string) => String(values[name] ?? token));
}
export function resolveLocale(preference: string | null, languages: readonly string[]): Locale {
  if (preference === 'en' || preference === 'zh-CN') return preference;
  return languages[0]?.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en';
}
export function textLanguage(text: string): Locale | undefined {
  return /[\u3400-\u9fff]/u.test(text) ? 'zh-CN' : undefined;
}

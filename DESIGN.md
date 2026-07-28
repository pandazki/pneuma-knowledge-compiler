# Pneuma Knowledge Compiler · Web 设计系统（2026-07 重设计）

本文档是当前 Web UI（`apps/web`）的唯一设计权威。本轮为 blank-slate 重设计：
旧视觉资产全部废弃，本文档从 API contract 与产品叙事独立推导。

产品一句话：面向 AI-Native 个人开发者的开源**知识编译器**——把持续产生的对话、
文档与实验材料，编译为可追溯的 source、可重建的索引、带引用的 canonical
knowledge 与可回滚的 Git 版本，并在 recall / 问答 / 主动提示的取用面上施加引用门禁。

---

## 1. 三个候选视觉方向（仅文字与 tokens）

### 方向 A ·「校样 Galley」— 编辑室与印厂

世界：一张编辑桌上的校样。纸、墨、发丝线、脚注。产品的核心承诺——
"每个 claim 都能回到精确 source span"——在这个世界里就是**脚注**：正文里的
上标编号，页边的出处栏。UI 外壳用无衬线，阅读面（canonical 正文、问答、引用
原文）用衬线，ID / Git ref / 模型 lineage 用等宽——三种字体的分工本身就是
"编辑—文本—机器"三层结构的表达。结构靠发丝线与留白，不靠卡片。

- 中性色：暖纸色系（light `#f6f5f1` 底 / `#20201d` 墨）与暖石板系（dark `#17171a` 底 / `#e8e6e0` 墨）
- 唯一强调色：**蓝铅笔**（编辑改稿用的蓝铅笔）light `#3d5a99` / dark `#93a9d6`
- 语义色仅用于真实状态：ok 灰绿、warn 赭黄、danger 赭红，全部低饱和
- 标志性元素：上标脚注引用、页边出处栏（marginalia）、章节编号（§01）、
  历史快照的"档案戳"（只读印）、以标尺线绘制的"生产流程"图解

### 方向 B ·「信号链 Signal Chain」— 母带工作台

世界：一台母带处理台的信号通路。材料是输入信号，compile 是处理链路，
门禁是噪声门，canonical 是母带。深色优先，细单线 SVG 示波图，等宽字体主导，
唯一的荧光琥珀做信号指示。

- 中性色：暖近黑 `#141311` 系
- 强调色：示波琥珀 `#c98a2b`
- 放弃理由：等宽字体主导与"中文正文稳定舒展"冲突；仪表隐喻容易滑回
  dashboard；引用—溯源这个故事在示波器语言里没有等价物，完成度上限低。

### 方向 C ·「账册 Ledger」— 档案登记簿

世界：档案馆的登记账册。冷石灰中性色、表格数字、accession number
（2026.014 式编号）、双栏账页、橡皮章状态。

- 中性色：冷石灰 `#f4f4f2` 系
- 强调色：褪色孔雀石绿 `#3f6f5e`
- 放弃理由：账册的本质是表格，与"避免 admin dashboard / 密集表格"的硬约束
  正面冲突；登记隐喻强于"编译"隐喻，讲不清 L1/L2/L3 的层次。

### 选定：方向 A「校样 Galley」

理由：

1. **叙事同构**。引证即脚注、溯源即查校样、版本即版次、门禁即校对红笔——
   产品的每个机制在编辑室语言里都有原生表达，不需要发明装饰性隐喻。
2. **质感路径正确**。编辑感靠排版、字距、发丝线与留白建立，天然低饱和、
   克制、成熟；正好是本轮要解决的问题的反面。
3. **双主题不反色**。light 是"纸上墨"，dark 是"灯箱上的底片/夜航校样"，
   两套独立调校的表面与墨阶，而非机械反色。
4. **反卡片**。发丝线分节 + 页边栏 + 编号章节，结构性替代 card 容器。

---

## 2. 设计 Tokens（单一 source of truth）

全部颜色集中在 `apps/web/src/styles/tokens.css`，以 CSS custom properties 定义，
经 Tailwind v4 `@theme inline` 映射为 utilities。**组件内禁止出现十六进制颜色、
禁止出现 `rgb()`/`hsl()` 字面值**；唯一的例外是 tokens.css 本身与
`color-mix()` 对既有变量的推导。

### 2.1 颜色 · 日间「纸 Paper」

| token | 值 | 用途 |
|---|---|---|
| `--bg` | `#f6f5f1` | 页面纸底 |
| `--surface` | `#fbfaf7` | 阅读面 / 面板底 |
| `--raised` | `#ffffff` | 浮层（popover/dialog/menu） |
| `--ink` | `#20201d` | 主文字 |
| `--ink-2` | `#57554e` | 次级文字 |
| `--ink-3` | `#8b887e` | 弱化文字 / 占位 |
| `--line` | `#e3e1d9` | 发丝线 |
| `--line-2` | `#cfcdc3` | 强调分隔线 / 控件边框 |
| `--accent` | `#3d5a99` | 蓝铅笔：链接、选中、脚注编号、focus |
| `--accent-ink` | `#fbfaf7` | accent 底上的文字 |
| `--ok` | `#4a7257` | 真实成功状态 |
| `--warn` | `#94650f` | 真实警告状态 |
| `--danger` | `#a03d2c` | 真实错误状态 |

派生（一律用 `color-mix` 从上述变量推导，不写新 hex）：
`--accent-soft` = accent 10% on bg（选中底）、`--accent-line` = accent 35%
（选中边）、`--hover` = ink 4%（悬停底）、`--active` = ink 7%、
`--ok-soft` / `--warn-soft` / `--danger-soft` 同理（10%）。

### 2.2 颜色 · 夜间「灯箱 Lightbox」

不是反色：底更暖、墨略降纯、发丝线保留可见层次。

| token | 值 |
|---|---|
| `--bg` | `#17171a` |
| `--surface` | `#1d1d21` |
| `--raised` | `#252529` |
| `--ink` | `#e8e6e0` |
| `--ink-2` | `#a6a39a` |
| `--ink-3` | `#6f6c65` |
| `--line` | `#2c2c31` |
| `--line-2` | `#3d3d44` |
| `--accent` | `#93a9d6` |
| `--accent-ink` | `#17171a` |
| `--ok` | `#7fa98c` |
| `--warn` | `#cfa458` |
| `--danger` | `#d08574` |

对比度约束（WCAG 2.2 AA）：正文/控件文字 ≥ 4.5:1；大字与图标 ≥ 3:1；
focus 环与底 ≥ 3:1。accent 两色均按正文级对比度选取。

### 2.3 字体与排版

| token | 值 | 用途 |
|---|---|---|
| `--font-sans` | `system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif` | UI 外壳、导航、按钮、表单 |
| `--font-serif` | `"LXGW WenKai Screen"`（随包内嵌，OFL）, `"Songti SC"`, `"Noto Serif SC"`, `"Source Han Serif SC"`, Georgia, `"Times New Roman"`, serif | 阅读面：canonical 正文、问答答案、引用原文、页标题 |
| `--font-mono` | `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace` | ID、路径、Git ref、lineage、block 编号、token 计数 |

字号阶（px）：`12 / 13 / 14 / 16 / 20 / 24 / 30 / 38`。
**中文可见文本最小 12px**；12 仅用于脚注、辅助元信息。
行高：正文 1.75（中文舒展）、UI 1.5、标题 1.25。
阅读宽度：阅读面 `max-width: 68ch`；UI 栏不超 `--measure`。
字重：400 / 500 / 650（仅标题与强调；不用 700+ 粗黑堆层级）。

禁止：大面积 uppercase + letter-spacing 伪造专业感；把下拉/正文/中文按钮
设为等宽字体（mono 只给真正等宽语义的内容）。

### 2.4 空间 / 形状 / 动效

- 间距：4 基线网格，`4/8/12/16/24/32/48/64`
- 圆角：`--r-1: 2px`（小控件）、`--r-2: 4px`（输入/按钮）、`--r-3: 8px`（浮层）；
  编辑感 = 近乎直角，禁止大圆角气泡
- 阴影：基本不用；浮层用 `0 1px 2px rgb(0 0 0 / .06), 0 8px 24px rgb(0 0 0 / .08)`
  （dark 下加深），内容区一律以发丝线分隔代替阴影与卡片
- 动效：`--dur-1: 120ms / --dur-2: 200ms`，`ease-out`；仅 fade / 2–4px 位移；
  `@media (prefers-reduced-motion: reduce)` 下全部动效归零
- z 轴：`--z-nav: 40 / --z-overlay: 50 / --z-toast: 60`

---

## 3. 信息架构

hash 路由与 deep link 契约**不变**（`lib/hash.ts` 的 12 个视图 + selection
编码全部保留）。变化的是命名、分组、排序与首屏叙事。

导航按"一本书的目录"组织，左栏为目录轨（桌面），移动端收进抽屉：

| 章 | 视图（route） | 目录名 | 用户故事 |
|---|---|---|---|
| 卷首 | `overview` | 卷首 · 这是一个编译器 | 故事 1：为什么是"知识编译器" |
| 原料篇 | `sources` / `ingest` | 原料 Sources · 导入 Ingest | 故事 2：导入材料、看编译计划 |
| 工序篇 | `process` | 工序 Process | 编译 job 与状态 |
| 取用篇 | `recall` / `ask` / `context_stream` | 检索 Recall · 问答 Ask · 提示 Cue | 故事 4/5/6 |
| 正典篇 | `library` / `graph` / `history` | 正典 Canonical · 图谱 Graph · 版本 History | 故事 3/7 |
| 演化篇 | `evolve` | 演化 Evolve | 故事 8 |
| 卷末 | `profile` | 画像 Profile | synthetic 用户档案 |

另有隐藏路由 `#/components`：表单组件统一状态页（验收用，不进目录）。

顶栏（贯穿）：字标 `Pneuma · Knowledge Compiler`、目录按钮（移动端）、
右侧 UserPicker（synthetic 用户切换）、SnapshotPicker（HEAD / 历史快照）、
主题切换。历史快照选中时，内容区顶部出现"档案戳"横幅：
`历史快照 · 只读` + mono ref，全部写操作禁用。

首屏（overview）必须回答：材料如何进入 → 如何编译索引 → claim 如何回到
source span → 如何进入版本 → 取用面如何被引用门禁保护 → 数据全是 synthetic。
形式：一纸"校样"——题字（serif 大标题）、一段编者说明、一幅**标尺线生产
流程图**（§1 原料 → §2 编译 → §3 正典 → §4 取用，发丝线 + 编号，节点上是
当前数据集的实时计数）、L0–L3 层的定义表、按六个故事的"翻阅指引"、
synthetic 数据披露。禁止线路图/彩色站点/交通隐喻。

---

## 4. 组件系统

分层：`src/ui/`（primitives）→ `src/components/`（composed，业务通用）→
`src/views/`（页面）。底层统一使用 **Radix UI** headless primitives（只用这一套）。

### 4.1 Primitives（`src/ui/`）

每个控件必须：受控、键盘可达、visible focus（`--accent` 2px outline + 2px offset）、
aria label/description、支持 disabled / error / loading / empty、双主题、
390px 可用、三浏览器一致外观。禁止任何原生控件外观泄漏。

- `Button`（variant: primary=accent / default=墨线框 / ghost / danger；size: sm/md）
- `IconButton`（方形，lucide 图标，必须 aria-label）
- `TextField` / `SearchField`（完整 reset：去原生 outline/autofill 黄底/
  clear 按钮统一自绘；支持前后缀、error、hint）
- `TextArea`（自动行数可配，禁原生 resize 样式，自绘 resize 手柄或禁用）
- `Select`（Radix Select：自绘 trigger/listbox/item，带 check 指示与滚动按钮）
- `Combobox`（Radix Popover + 过滤输入；供 SnapshotPicker / UserPicker 复用）
- `NumberField`（去原生 spinner，自绘 ± stepper 按钮，键盘上下键）
- `Slider`（Radix Slider：track/range/thumb 全自绘，显示当前值）
- `Switch`（Radix Switch）
- `Checkbox`（Radix Checkbox：自绘方框 + check，indeterminate 支持）
- `RadioGroup`（Radix RadioGroup：自绘圆点）
- `SegmentedControl`（Radix Tabs 实现的分段选择；fast/deep/rag 等模式切换）
- `FilePicker`（visually-hidden native input + 自绘拖放区；显示文件名/大小）
- `Dialog` / `Drawer`（Radix Dialog；Drawer = 移动端从侧/底部滑入的变体）
- `Popover` / `Tooltip`（Radix；Tooltip 仅桌面 hover + focus 触发）
- `Tabs`（Radix Tabs，下划线式，发丝线）
- `Menu`（Radix DropdownMenu）
- `Spinner` / `Skeleton`（统一 loading：骨架屏用于内容位，spinner 仅按钮内）
- `Kbd`（快捷键提示）、`Badge`（中性标签）、`Stamp`（档案戳：旋转 -2deg
  的线框章，仅"只读 / synthetic / 状态"用语义色描边）
- `EmptyState`（图标 + 一行说明 + 可选动作，全产品唯一 empty 实现）
- `ErrorState`（错误说明 + 重试，全产品唯一 error 实现）
- `Callout`（notice/info/warn/danger 四阶，左边 2px 语义色条 + 中性底）
- `Footnote`（**签名组件**：上标 accent 编号 `[n]`，hover/focus 出 citation
  卡片，点击跳 source span）
- `Mono`（等宽内联：ID/ref/路径；自动 `font-variant-numeric: tabular-nums`）
- `SectionRule`（章节发丝线 + 编号 + 标题，`§01` 式）
- `DefinitionList`（术语—定义双栏，L0–L3 说明用）

### 4.2 Composed（`src/components/`）

- `AppShell`：顶栏 + 目录轨 + 内容栏 + 快照档案戳横幅 + notice 条
- `TocNav`：目录导航（章节分组、编号、当前页 accent 左标线；移动端 Drawer）
- `UserPicker`（Combobox：avatar 字标 + display_name + mono id + "新建画像"）
- `SnapshotPicker`（Combobox：HEAD + 历史 ref 列表，mono，只读提示）
- `ThemeToggle`（IconButton，日/夜）
- `PageHeader`（serif 页题 + 一行说明 + 右侧操作区）
- `SourceSpanSheet`（引用落点：source 原文 + block 编号 + 高亮 span +
  fetch-locator 精确段；recall/ask/cue/library 共用）
- `ClaimRow`（canonical claim：serif 正文 + 脚注 + flag 标记 + 锚点 mono）
- `CitationList`（引用列表：编号 + source 标题 + block 区间 + 跳转）
- `GateLedger`（cue 门禁账：`unparsed/repeat/uncited/low_confidence/capped`
  五栏计数账页，仅真实状态上色）
- `GraphCanvas`（lazy 加载 @xyflow/react + dagre；墨色节点 + typeGlyph 形状冗余编码）

### 4.3 状态规范（全部视图统一）

- loading：骨架屏（内容位），操作中 spinner 进按钮；禁止逐视图自造
- empty：`EmptyState` 单实现，文案给"下一步动作"
- error：`ErrorState` 单实现，附 ApiError detail 与重试
- offline/reconnect：顶栏下 notice 条（`Callout` 行内变体），WS 视图额外
  在页头显示连接态（connecting/open/closed 用文字 + 单点，不用彩色灯组）
- 历史快照只读：档案戳横幅 + 所有 mutation 控件 `disabled`

---

## 5. 视图规范（每视图：目的 / 构成 / 关键交互 / 状态）

### overview 卷首
目的：60 秒讲清"知识编译器"。构成：serif 题字 + 编者说明（≤5 行）；标尺线
生产流程图（§1→§4，节点实时计数：sources/jobs/documents+claims/snapshots）；
L0–L3 DefinitionList；六故事翻阅指引（编号列表链到各视图）；synthetic 披露
（Stamp）。交互：流程图节点点击进对应篇。状态：无数据时计数显示 `—`，
指引仍然可读。

### sources 原料
master-detail：左为 source 目录（标题、kind、block 数、消化态——消化态用
文字+时间，不用彩色灯），右为选中 source 的"校样页"：结构地图（section 树）、
原文 blocks（mono 块号 + serif 正文）、span 高亮落点。交互：`focusSource`
落点滚动 + 高亮；locator fetch 精确段。状态：空库 → EmptyState 指向 ingest。

### ingest 导入
两步：编辑（标题 + TextArea / FilePicker + archetype Select + source_class
RadioGroup）→ 机械预览（section 树、block/char 计数、proposed IntakePlan
双旋钮展示、archetype 映射）。交互：preview → 确认 ingest → 结果页（source_id、
deduplicated、去 sources 查看）。会话导入（turns 编辑）作为第二个 Tab。

### process 工序
job 账页：每次 compile 一行（job_id mono、kind、状态文字、时间、snapshot_ref）。
选中展开：来源、detail、lineage（model/provider/tokens，mono 定义表）。
操作：`compile` 触发按钮（primary）。

### recall 检索
SegmentedControl：rag / fast / deep。rag → L1/L2 融合命中账（score、source、
block 区间、Footnote 跳 source span）。fast → 答案（serif）+ used_claims 脚注。
deep → SSE 逐步 trail（工具调用时间线）+ 答案。token_usage 以 mono 定义表呈现。
模式即"检索 lane"对比：同 query 可切换三种模式重跑。

### ask 问答
briefing 构建（query/来源多选/字符预算 NumberField）→ 连续问答线程（serif
问答对 + 引用脚注 + 逐轮 token_usage）。引用点击 → SourceSpanSheet。

### context_stream 提示
双链路面板：SSE 一次性（转录窗口编辑 + focus/kind Select + min_confidence
Slider + 评估 → 存活卡片 + GateLedger 门禁账）；WS 长连接（连接态、config、
turn 追加、flush、want_more 展开 cue_detail）。卡片：标题 + serif 正文 +
trigger + confidence（数字，非仪表）+ 引用。门禁被吃掉的内容只在
GateLedger 计数中呈现——门禁的严肃性靠"消失"表达。

### library 正典
左：文档目录树（DirNode）；右：选中文档的"版样"——serif 排版正文、claim
锚点 mono、脚注引用、flag（disputed/open_question）以页边注呈现
（sidecarNotes）。claim 选中 → deep link `#/library/claim/...`。

### graph 图谱
lazy GraphCanvas：墨色节点（typeGlyph 形状+墨阶冗余编码，不上彩色）、
发丝线边、选中节点 + 邻域展开（1–2 度）、右侧详情栏（节点 → 文档/演化
跳转）。移动端：图谱在上、详情在下纵向排。

### history 版本
Git 时间线：snapshot / job / patch 三类记录的统一账页（mono ref、时间、
changed paths、sources consumed、lineage）。选中 patch → 详情（escalations、
flag_counts、claims trace）。snapshot 行可"查看此快照"→ SnapshotPicker 切到
只读态。

### evolve 演化
skill 信息（version、content_hash、path_templates、packs）+ evolve 任务账：
draft 任务展开 proposal/rationale/changed_files（old/new 对照）、dropped
anchors、TTL 倒计时；adopt/drop 操作（primary/danger）。409 单飞冲突以
Callout 呈现。

### profile 画像
synthetic 用户档案：avatar 字标 + display_name + 核心字段定义表
（industry/role/level/level_style/workspace/preferences/interests）；
编辑表单（全部走 primitives）；AI 生成画像（一句话 → generateProfile 预填）。
明示"演示用 synthetic 人设"。

### components 组件状态页（隐藏路由 `#/components`）
全部 primitives 的默认/hover(focus)/disabled/error/loading/empty 矩阵，
用于验收截图与回归。

---

## 6. 硬性规则（实现时逐条自查）

1. 颜色只在 tokens.css；组件零 hex、零 `rgb/hsl` 字面值（color-mix 推导除外）。
2. 业务页面零原生控件外观：select/number spinner/range/checkbox/radio/file/
   datalist/date picker 一律走 primitives；visually-hidden native input 仅作
   可访问性/文件选择后备。
3. 中文可见文本 ≥ 12px；mono 不给中文正文/按钮/下拉。
4. 一个产品一个强调色（蓝铅笔）；模块不分配各自颜色；语义色只给真实状态。
5. 不用卡片堆叠、不用 KPI 数字墙、不用渐变/霓虹/玻璃拟态/高饱和蓝紫。
6. dark 不是反色：两主题独立调校，dark 保留墨阶层次、禁纯黑底。
7. 宽屏不无限拉长：内容栏 max-width 约束，graph 等宽幅视图单独 breakout。
8. 390px 无横向溢出；所有交互在 390px 可达。
9. `prefers-reduced-motion` 下动效归零。
10. WCAG 2.2 AA：对比度、focus 可见、键盘全可达。
11. 图谱依赖（@xyflow/react + dagre）继续 lazy load；主包保持克制。
12. 所有界面文案开源、业务无关、synthetic；禁止真实客户/公司/内部内容。
13. 删除旧视觉资产：旧 components/views/styles/index.css 不保留为覆盖层。

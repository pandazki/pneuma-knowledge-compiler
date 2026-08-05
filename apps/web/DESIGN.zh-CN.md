# apps/web · 设计系统

[English](DESIGN.md) | **简体中文**

`apps/web` 的设计权威；源码注释里的 `§` 引用（`DESIGN.md §2.4`、`hard rule 4` …）指向本文。同一套规则还有两份可执行形态——`src/styles/tokens.css`（全部颜色）与 `src/index.css`（prose、滚动分区、原生控件 reset）——隐藏路由 `#/components` 则把每个 primitive 的每种状态摆出来看。本文说明这些决定的含义，以及其中哪些是承重的。

---

## 1. 世界：一张校样

编辑桌上的一张校样。纸、墨、发丝线、脚注。产品的核心承诺——每个 claim 都能回到精确的 source span——在这个世界里就是**脚注**：正文里的上标编号，页边的出处栏。三种字体承载产品的三层：无衬线给编辑外壳，衬线给阅读面，等宽给机器文本。结构来自发丝线与留白，而不是卡片。

在代码与文案里反复出现的词汇：**footnote 脚注**（引用标记）、**marginalia 页边注**（正文旁的 flag 与出处）、**§ 编号**（章与节）、**ruler line / hairline 标尺线与发丝线**（结构与图解）、**archive stamp 档案戳**（只读、synthetic）、**galley 校样**（源材料的编译视图，与原文并置）。

这个隐喻站得住的原因：

1. **叙事同构**。引证即脚注、溯源即查校样、版本即版次、引用门禁即校对红笔。每个机制都有原生表达，不需要发明装饰性隐喻。
2. **质感来自排印**。编辑感由字体、字距、发丝线与行宽建立，天然低饱和、克制。
3. **两个真实表面**。日间是纸上墨，夜间是灯箱上的底片：两套独立调校的表面，而非一套的反色。
4. **反卡片**。发丝线分节、页边栏与编号章节替代 card 容器。

---

## 2. 设计 tokens（单一 source of truth）

全部颜色以 CSS custom properties 住在 `src/styles/tokens.css`，经 `src/index.css` 的 `@theme inline` 映射为 Tailwind v4 utilities。**组件内零十六进制、零 `rgb()`/`hsl()` 字面值**；唯一的例外是 tokens.css 本身，以及对其中既有变量做 `color-mix()` 推导。

`lib/cn.ts` 把这些 token 名注册进 tailwind-merge——颜色归颜色、尺寸归尺寸、圆角归圆角。不注册的话，tailwind-merge 会把 `text-accent-ink` 读成字号并在 merge 时丢掉它，primary 按钮就是这样丢过一次颜色的。

### 2.1 颜色 · 日间「纸 Paper」

| token | 值 | 用途 |
|---|---|---|
| `--bg` | `#f6f5f1` | 页面纸底 |
| `--surface` | `#fbfaf7` | 阅读面 / 面板底 |
| `--raised` | `#ffffff` | 浮层（popover / dialog / menu） |
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

派生色一律由上表变量 `color-mix` 得到，绝不新写 hex：`--accent-soft`（accent 10% on bg，选中底）、`--accent-line`（accent 35%，选中边）、`--hover`（ink 4%，做成叠加层因此在任何底色上都成立）、`--active`（ink 7%），以及 `--ok-soft` / `--warn-soft` / `--danger-soft`（10%）。

### 2.2 颜色 · 夜间「灯箱 Lightbox」

不是反色：底更暖、墨略降纯、发丝线仍然读得出是一层。

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

夜间的派生比例比日间高几个点（soft 底 12%，hover / active 用 ink 5% / 9%），因为同样的比例在深底上读起来更弱。

对比度（WCAG 2.2 AA）：正文与控件文字 ≥ 4.5:1，大字与图标 ≥ 3:1，focus 环与其底 ≥ 3:1。两个 accent 都按正文级对比度选取。

### 2.3 字体与字号

| token | 栈 | 用途 |
|---|---|---|
| `--font-sans` | `system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif` | 编辑外壳：导航、按钮、表单 |
| `--font-serif` | `"LXGW WenKai Screen"`（随包内嵌，OFL）、`"Songti SC"`、`"Noto Serif SC"`、`"Source Han Serif SC"`、Georgia、`"Times New Roman"`、serif | 阅读面：canonical 正文、答案、source 原文、页标题 |
| `--font-mono` | `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace` | 机器文本：ID、路径、git ref、lineage、block 编号、token 计数 |

Web 字体在 `index.css` 里按 unicode-range 分片引入，浏览器只下载用到的字形，未落地时回退到系统宋体 / serif。

字号阶（px）：`12 / 13 / 14 / 16 / 20 / 24 / 30 / 38`。**中文可见文本最小 12px**，且 12 只留给脚注与辅助元信息。行高在 `@theme` 里按字号绑定：UI 尺寸 1.5，16（正文）1.75，20 起（标题）1.25。阅读行宽 `--measure: 68ch`；内容栏 `--content-max: 1080px`。字重 400 / 500 / 650——层级不靠 700+ 堆出来。

由此排除两件事：用大面积 uppercase + letter-spacing 伪造专业感；把中文正文、按钮、下拉设成等宽（mono 只给真正等宽语义的内容）。

### 2.4 阅读层（`.prose`）

一切 serif 阅读面——答案、claim 正文、source 原文、引用段、suggestion 卡片正文——统一走 `index.css` 的 `.prose` / `.prose-lede`。规则提炼自 [kami](https://github.com/tw93/kami) 的 print 排版纪律，其中大多数是踩过一次才知道的：

- 中文屏读行高 1.65（正文）/ 1.7（lede），配密度补偿 `letter-spacing` 0.015em / 0.03em。这是楷体在屏幕字号下需要的呼吸感，不是装饰性 tracking。
- `strong` 锁 500。LXGW WenKai 只有一个字重，浏览器被要求 700 时会合成糊掉的伪粗体。
- 行内 `code` 把 `letter-spacing` 归零——中文补偿会把等宽串撑松。
- 标题邻近律：上距 ≥ 2× 下距。标题 `text-wrap: balance`，正文 `pretty`。
- 列表用原生 marker 并着 accent；引文是 2px accent 左边条 + ink-2；`pre` 有填充无边框；表格无框、发丝行线、ink-2 表头、tabular-nums；链接 accent 无下划线，hover 向墨色压深。
- 图解标注与指标数字用 serif + tabular-nums，不用 mono。

`.prose` 是组件层类，调用点用 utilities（`text-14`、`text-ink-2`）覆盖尺寸与颜色。阅读面不应再散写 `font-serif leading-[1.65] tracking-[0.015em]` 这样的一次性组合。

### 2.5 空间 / 形状 / 动效——以及滚动

- **间距**：4px 基线——`4 / 8 / 12 / 16 / 24 / 32 / 48 / 64`。
- **圆角**：`--r-1` 2px（小控件）、`--r-2` 4px（输入、按钮）、`--r-3` 8px（浮层）。近乎直角就是编辑感的信号；胶囊与气泡圆角不属于这套系统。
- **阴影**：只给浮层（`--shadow-overlay`，dark 下加深）。内容区一律以发丝线分隔，代替阴影与卡片。
- **动效**：`--dur-1` 120ms / `--dur-2` 200ms，`ease-out`；只有 fade 或 2–4px 位移，没有别的。`prefers-reduced-motion: reduce` 下 base 层把全部动画与过渡归零。
- **z 轴**：`--z-nav` 40 / `--z-overlay` 50 / `--z-toast` 60。
- **分区滚动总纲**：每个视图把动线控制区（页头、查询栏、lane 切换）钉住，把每块内容区交给 `ScrollRegion`——滚一个区不会把整页拽走，锚跳转落在自己那一区里。溢出是被声明的而不是被装饰的：藏着内容的那一边用 `mask` 渐隐（走 alpha，因此在任何底色、两套主题下都成立，也不需要新 token），滚动条槽位在区域溢出后占住并保持可见——不该要求读者先 hover 才知道这里能滚。边缘算术是无 import 的 `lib/scrollRegion.ts`；CSS 在 `.scroll-region`；`AppShell` 的 `VIEWPORT_PANE_VIEWS` 在 ≥lg 时把这样搭的视图内容栏限到视口高。

---

## 3. 信息架构

hash 路由就是 deep link 契约（`lib/hash.ts`）：12 个视图加 selection 编码。导航按一本书的目录组织——桌面为目录轨，移动端收进 Drawer。§ 编号、顺序与分组住在 `components/TocNav.tsx` 的 `TOC`，词句住在 `i18n/nav.ts`：编号是结构，标签是文案。

| 章 | § | 视图（route） | 做什么 |
|---|---|---|---|
| 卷首 | 01 | `overview` | 为什么这是一个**编译器** |
| 原料篇 | 02 / 03 | `sources` / `ingest` | 读进来的东西；导入并看它的计划 |
| 工序篇 | 04 | `process` | 编译 job 与状态 |
| 取用篇 | 05 / 06 / 07 | `recall` / `ask` / `live_context` | 三条检索 lane、briefing、即时建议 |
| 正典篇 | 08 / 09 / 10 | `library` / `graph` / `history` | canonical 文档、结构健康、版本 |
| 演化篇 | 11 | `evolve` | 待评审的 schema 草案 |
| 卷末 | 12 | `profile` | 当前租户的画像 |

`#/components` 是隐藏的第 13 条路由（primitive 陈列），不进目录。

顶栏贯穿所有视图：字标、移动端目录按钮，右侧是 UserPicker（租户）、SnapshotPicker（当前 HEAD / 可问答的冻结快照 / canonical 提交仅浏览）、LocaleToggle 与 ThemeToggle。选中快照期间，内容栏顶部出现档案戳横幅，所有写操作控件禁用（§4.3）。

`overview` 必须在一屏内回答：材料如何进入 → 如何编译索引 → claim 如何回到 source span → 如何进入版本 → 取用面如何被门禁保护 → 数据全是 synthetic。形式是一纸校样——serif 题字、一段简短编者说明、一幅标尺线生产流程图（原料 → 编译 → 正典 → 取用，发丝线 + § 编号，节点上是实时计数）、L0–L3 定义表、按编号进入各视图的翻阅指引、synthetic 披露。不做线路图，不做彩色管道图形。无数据时计数显示 `—`，指引仍然可读。

---

## 4. 组件系统

分层：`src/ui/`（primitives）→ `src/components/`（composed，业务通用）→ `src/views/`（页面）。headless 行为一律取自 **Radix UI**，只用这一套。样式是引用 token 的 Tailwind utilities（`bg-surface`、`text-ink-2`、`border-line`、`rounded-2`、`text-14`、`max-w-measure`、`max-w-content`），不写一次性 CSS 文件。

### 4.1 Primitives（`src/ui/`）

每个 primitive 都受控、键盘可达、focus 走全局规范（accent 2px outline + 2px offset，已全局生效，不要自造）、有 label（`aria-label` / description）、带上适用于它的 disabled / error / loading / empty 状态、双主题成立、390px 可用、三引擎外观一致。原生控件外观不外泄；`index.css` 已全局剥除（§6 规则 2）。

值得在类型之外说清的契约：

- **Button** — `variant`：`primary`（accent 底）/ `default`（墨线框）/ `ghost` / `danger`；`size`：`sm`（h-7，13px）/ `md`（h-9，14px）；`loading` 把 spinner 移进按钮、置 `aria-busy` 并阻止重复提交。
- **IconButton** — 方形，lucide 图标，`aria-label` 是**必填** prop（TS 强制）。
- **TextField / SearchField / TextArea / NumberField / FilePicker** — reset 是彻底的：没有原生 outline、没有 autofill 黄底、没有数字 spinner、没有 resize 手柄、没有 file-selector 按钮。清空按钮、± stepper 与拖放区都自绘；原生 input 以 visually-hidden 形态保留，用于可访问性与文件选择。`TextArea` 靠 `autoRows` 增高，不靠原生 resize。
- **Select / Combobox / Menu / Tabs / SegmentedControl / Dialog / Drawer / Popover / Tooltip / Switch / Checkbox / RadioGroup / Slider** — 底层 Radix，上层全自绘。`Combobox`（Popover + 过滤输入）是 UserPicker 与 SnapshotPicker 共用的那一个，它的 `footer(query, close)` 是放「新建画像『query』」这类动作的位置。`SegmentedControl` 只渲染分段触发器——面板由调用方按 `value` 自切。`Tooltip` 仅桌面 hover + focus 且只放单行；富内容归 `Footnote` 或 `Popover`。
- **Spinner / Skeleton / SkeletonText** — loading 只有一种形状：内容位用骨架屏，spinner 只进按钮。
- **EmptyState / ErrorState** — 全产品唯一的 empty 与 error 实现。empty 文案给出下一步动作；error 带 `ApiError` detail（mono）与重试。
- **Callout** — `tone`：notice（accent）/ info（ink-3）/ warn / danger；`variant`：`block` 或 `inline`（顶栏下的通栏 notice 条）。中性底 + 2px 语义色左边条。
- **Footnote** — 签名组件。正文内上标 accent `[n]`，hover 或 focus 出 citation 卡片，点击跳到 source span（通常经 `focusSource(sourceId, { start, end })`）。
- **Mono / Kbd / Badge / Stamp** — 自动 tabular-nums 的机器文本（绝不给中文正文、按钮、下拉）；键帽；四阶中性标签；以及档案戳（-2deg 线框章），只用于只读 / synthetic / 真实状态。
- **SectionRule / DefinitionList** — `§01 ── 标题 ────────` 式分节（用它替代卡片），以及发丝线分隔的术语—定义行。
- **ScrollRegion** — 分区滚动总纲的唯一承载（§2.5）。**高度由调用方给**（钉住的分栏里用 `flex-1 min-h-0`，随流布局里用 `max-h-…`）；不给高度则永不溢出，自然退化成整页滚动，窄屏直接复用同一份标记。组件只量自己，并把边缘状态写成 `data-fade`（none/top/bottom/both）与 `data-overflowing`；渐隐与细滚动条槽位都在 CSS 里。

### 4.2 Composed（`src/components/`）

`AppShell`（顶栏 + 232px 目录轨 + `max-w-content` 内容栏 + notice 条 + 离线条 + 快照横幅）、`TocNav`、`UserPicker`、`SnapshotPicker`、`ThemeToggle`、`LocaleToggle`、`PageHeader`（24 号 serif 页题 + 一行 ink-2 说明 + 操作区）、`PaginationBar`、`ActivityHeatmap`。

其中带设计决定的几个：

- **SourceSpanSheet** — 引用的落点：右侧 Drawer，原文（mono 块号 + serif 正文）、目标 span 以 accent-soft 高亮、附「fetch 精确段」的 locator 调用。recall / ask / live_context / library 共用，所以引用永远以同一种方式落地。
- **CitationList** — 脚注体：块首一条发丝线，行间不再分线；`[n]` 用 mono ink-3，因为 accent 只属于正文里的 `Footnote` 标记；标题 12px ink-2，span 与 id 12px ink-3，行距收紧到 1.45。弱化只在视觉——整行仍可 hover / 点击回到 source span，hover 时标题抬回 ink。
- **ClaimRow** — serif 正文 + `Footnote` 序列 + mono 锚点；flags（disputed / open_question）在 ≥md 时以右侧页边注呈现，窄屏落到正文下。
- **GateLedger** — 五个丢弃计数（`unparsed / repeat / uncited / low_confidence / capped`）排成账页；只有真实状态上色（uncited 为 danger，其余 warn，0 为 ink-3）。门禁吃掉的内容**只**以计数出现：门禁的严肃性由「消失」表达。
- **`views/library/NeighborhoodCard`** — 出向 / 入向两栏，每行是对方文档的标题 + **写出这条链接的那句 claim**。边的信息量**就是**那句话，所以凡展示边的地方都必须带上它。结构永不用图形渲染库画（规则 11）。

### 4.3 状态规范（全部视图统一）

| 状态 | 做法 |
|---|---|
| loading（内容位） | `Skeleton` / `SkeletonText`，不逐视图自造 |
| loading（操作中） | `Button loading` |
| empty | `EmptyState`，文案给出下一步动作 |
| error | `ErrorState`，附 `ApiError` detail 与 `onRetry` |
| offline / 重连 | 顶栏下 `Callout variant="inline"`（AppShell 已处理 `usersError`）；WS 视图另在页头以文字 + 单点显示 connecting/open/closed，不用彩色灯组 |
| 历史快照只读 | AppShell 档案戳横幅 + 所有 mutation 控件 `disabled`（`currentSnapshot != null`） |

状态整体上用文字 + 墨阶表达，不用交通灯；未知的机器状态原样显示其机器名，而不是留白。阅读面的排版纪律在 §2.4。`#/components` 是这张状态矩阵的可视形态。

### 4.4 文案与 i18n

词典在 `src/i18n/`，每个 view 一个命名空间文件，经 `defineMessages()` 声明，使 zh/en 的 key 集合在**编译期**恒等：一个 key 只在一种语言里出现就是 `tsc -b` 错误。`tests/i18n.test.mjs` 是第二道网，同时也抓跨 bundle 的重复 key。`src/` 里不写任何面向用户的字面量。

- **新增文案只往对应命名空间文件加**，key 以该命名空间开头（`library.claim.empty`）。通用词——重试、关闭、上一页、flag、gate、分页、footnote——已经在 `i18n/common.ts` 里。
- **后端封闭词表**（intake archetype / context focus / suggestion kind / source kind）在 `i18n/enums.ts`，key 就是 API 给的稳定 `key`，一律用 **`useTOr()` + 服务端 label 兜底**——这样服务端加值时降级成那句英文，而不是空白。
- **数据不译**：canonical 正文、source 内容、人名、服务端给的 rationale / detail / 错误 message。
- **纯函数模块不得在运行期 import i18n**——`lib/evolve.ts`、`lib/citations.ts`、`views/*/…Presentation.ts`，也就是被测试单独 esbuild 成 `data:` URL 的那些。返回 message key 让视图翻译，或者把翻译函数注入进去。
- primitives 的默认文案已从词典取（`ErrorState.title`、`Select.placeholder`、`Combobox.filterPlaceholder`/`emptyText`、`SearchField.clearLabel`、`PaginationBar.noun` 都是 optional，不传即走 `common.*`）。

`locale` 在 store 里与 `theme` 同形（`s.locale` / `setLocale` / `toggleLocale`），`LocaleToggle` 在顶栏紧挨 `ThemeToggle`——切换即时生效，不刷新。解析顺序：localStorage 显式选择 → `navigator.language`（`zh*` → zh）→ **en**。`lib/format.ts` 的 `fmtTime` / `fmtDate` 已随 locale 走 `Intl`，调用点不用管。

---

## 5. 视图

- **overview** — 用 60 秒讲清「这是一个知识编译器」，构成见 §3。
- **sources** — master-detail：左为 source 目录（标题、kind、block 数、消化态用文字 + 时间而不是彩灯）；右侧分两个阅读层。**来源视图**按各契约还原原生阅读语法（meeting：会议抬头、参与者、带时间逐字稿；document-library：vault 路径、frontmatter、标签与双链；IM：频道语境、日期、thread 缩进；email：thread 抬头、收发件人、附件）。**编译校样**保留 intake plan、结构地图、归一化 blocks（mono 块号 + serif 正文）与 span 高亮。四种来源共享同一套 tokens——差异来自信息结构，而不是四套颜色。旧 source 缺少新增展示元信息时按 blocks 降级，不猜 provider 字段。
- **ingest** — 两步：编辑（标题 + TextArea / FilePicker + archetype Select + source class RadioGroup）→ 机械预览（结构树、block 与字符计数、proposed IntakePlan 的双旋钮、archetype 映射）→ 确认 → 结果（source_id、deduplicated、去 sources 查看）。preview-first 是要点：计划可见之前不导入任何东西。
- **process** — job 账页，每次 compile 一行（mono job_id、kind、状态文字、时间、snapshot_ref）；选中行展开来源、detail 与 lineage（model / provider / tokens 以 mono 定义表呈现）。`compile` 是 primary 动作。
- **recall** — SegmentedControl 切三条 lane：`rag`（L1/L2 融合命中，带 score、source、block 区间、进 span 的 Footnote）、`fast`（serif 答案 + used_claims 脚注）、`deep`（SSE 逐步 trail，然后是答案）。token 用量以 mono 定义表呈现。三条 lane 的输入与结果都留在 `store.recallCache`，去 sources 读原文再回来不会丢。
- **ask** — briefing 构建（query、来源多选、字符预算 NumberField），然后是连续的 serif 问答线程，带引用脚注与逐轮用量。点击引用打开 `SourceSpanSheet`。
- **live_context** — 一个视图里两条链路：一次性 SSE（工作流窗口、focus/kind、min-confidence Slider → 存活卡片 + `GateLedger`）与长连接 WS（连接态、config、turn 追加、flush、`want_more`）。卡片是标题 + serif 正文 + trigger + confidence 数字，不是仪表。
- **library** — 左为文档树；右为选中文档的版样：serif 正文、mono claim 锚点、脚注引用、flag 作页边注。选中 claim deep-link 到 `#/library/claim/…`。顺藤摸瓜发生在邻域卡（§4.2）里。
- **graph** — 结构**透镜**，不是探索 canvas：全库自由力导图答不了人们真正带来的问题。两个 tab——**结构健康**（先用几句话直说最异常的三件事，其下集中度、连通性、族均衡，异常条目可点进对应文档）与**时间对比**（选两个快照：指标差值表、主体增减清单、新增内链且每条带成边的那句话）。老 `#/graph/node/<id>` 链接解析到该节点代表的文档（或原料）。
- **history** — snapshot / job / patch 三类记录的统一账页（mono ref、时间、changed paths、sources consumed、lineage）。patch 展开为 escalations、flag counts 与 claims trace；snapshot 行可经 SnapshotPicker 以只读态打开。
- **evolve** — 三个面：演化时间线（状态即站点的形状与语义色）、任务详情（proposal 依据、pack 草案全文、会消失的 anchors、changed-file diff、adopt/drop）、schema 轴（族与 path template 随时间累积）。409 单飞冲突以 `Callout` 呈现。`#/evolve/evolve-task/<id>` 落在详情上。
- **profile** — 当前租户的画像：身份加一张编译契约会读的字段定义表，以及全部由 primitives 搭的编辑表单。AI 生成只属于「新建画像」onboarding（一句话 → 草稿 → 用户确认）；已有画像不显示生成入口。
- **components**（隐藏 `#/components`）— 全部 primitives 的默认 / hover / focus / disabled / error / loading / empty 矩阵，用于验收截图与回归。

---

## 6. 硬性规则

1. 颜色只住 `tokens.css`；组件零 hex、零 `rgb()`/`hsl()` 字面值（`color-mix` 推导除外）。
2. 业务页面零原生控件外观：select、number spinner、range、checkbox、radio、file、datalist、date picker 一律走 primitives；visually-hidden 的原生 input 仅作可访问性与文件选择的后备。
3. 中文可见文本 ≥ 12px；mono 不给中文正文、按钮、下拉。
4. 一个产品一个强调色（蓝铅笔）。模块不分配各自颜色，语义色只给真实状态。
5. 不用卡片堆叠、不用 KPI 数字墙、不用渐变 / 霓虹 / 玻璃拟态 / 高饱和蓝紫。
6. dark 不是反色：两套主题独立调校，dark 保留墨阶层次，禁纯黑底。
7. 宽屏不无限拉长：内容栏有 max-width 约束；真正宽幅的视图（表格、长账页）自行横向滚动。
8. 390px 无横向溢出，且所有交互在该宽度可达。
9. `prefers-reduced-motion` 下动效归零。
10. WCAG 2.2 AA：对比度、focus 可见、键盘全可达。
11. 不引图形渲染库：结构一律以排印表达（表格、账页、发丝线条形），主包保持克制。
12. 所有界面文案开源可用、业务无关、synthetic——禁止真实客户 / 公司 / 内部内容。

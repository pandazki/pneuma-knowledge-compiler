# UI 组件系统（src/ui + src/components）

视图实现者的唯一参考。分层：`src/ui/`（primitives）→ `src/components/`（composed，
业务通用）→ `src/views/`（页面）。硬性约束见仓库根 `DESIGN.md` §2/§6，要点：

- 样式一律 Tailwind utilities 引用 token（`bg-surface` / `text-ink-2` / `border-line`
  / `rounded-2` / `text-14` / `max-w-measure` / `max-w-content` …），禁止 hex、
  禁止 `rgb()`/`hsl()` 字面值（`color-mix` 推导允许）、禁止一次性 CSS 文件。
- 全部组件受控、键盘可达；focus 规范已全局生效（accent 2px outline + 2px offset），
  不要自造 focus 样式。
- loading：内容位用 `Skeleton`，spinner 只进按钮；empty/error 各只有
  `EmptyState` / `ErrorState` 一个实现。
- 历史快照只读态（`useApp((s) => s.currentSnapshot) != null`）：所有 mutation
  控件 `disabled`。

```tsx
import { Button } from "@/ui/Button";
import { PageHeader } from "@/components/PageHeader";
// 合并 className：cn()（clsx + tailwind-merge）
import { cn } from "@/ui/cn";
```

---

## Primitives（src/ui/）

### Button
`variant: "primary"(accent 底) | "default"(墨线框) | "ghost" | "danger"`，
`size: "sm"(h-7) | "md"(h-9)`，`loading?: boolean`（spinner 进按钮并禁用）。
继承原生 button 属性。

```tsx
<Button variant="primary" loading={busy} onClick={compile}>编译</Button>
```

### IconButton
方形图标按钮（`size: "sm" | "md"`）。**`aria-label` 为必填 prop**（TS 强制）。

```tsx
<IconButton aria-label="关闭" onClick={close}><X size={15} /></IconButton>
```

### TextField
`label / hint / error / prefix / suffix / wrapperClassName` + 原生 input 属性。
`error` 非空即 error 态（红框 + 错误文案）。focus 环在 wrapper（focus-within）。

```tsx
<TextField label="标题" value={v} onChange={(e) => setV(e.target.value)}
  hint="≤ 80 字" error={tooLong && "太长了"} />
```

### SearchField
`value: string; onChange: (v: string) => void`；Search 图标前缀 + 自绘清空按钮
（`clearLabel` 可改 aria-label）。

### TextArea
`label / hint / error` + `autoRows?: boolean`（随内容增高）+ `maxRows?: number`。
原生 resize 已禁用（`resize-none`），要可变高度就用 autoRows。

### Select（Radix）
`value: string | null; onChange; options: { value; label; disabled? }[]`；
`placeholder / label / hint / error / disabled`。自绘 trigger/listbox/item，
带 check 指示与滚动按钮。

```tsx
<Select label="archetype" value={v} onChange={setV}
  options={[{ value: "note", label: "笔记" }]} placeholder="请选择" />
```

### Combobox（Radix Popover + 过滤输入）
供 UserPicker / SnapshotPicker 复用的带过滤下拉。

```tsx
interface ComboboxItem {
  value: string; label: string; keywords?: string;
  disabled?: boolean; group?: string; render?: () => ReactNode;
}
<Combobox value onChange items trigger triggerAriaLabel
  filterPlaceholder? emptyText? disabled? disabledNote?
  footer?: (query, close) => ReactNode  // 底部动作区，如「新建画像「query」」
/>
```
键盘：↑↓ 移动、Enter 选中、Esc 关闭；`group` 相同的连续项归为一节。

### NumberField
`value: number | null; onChange; min? max? step?`（默认 1）。自绘 ± stepper，
↑↓ 键步进，blur 时 clamp；无原生 spinner（type=text + inputMode）。

### Slider（Radix）
`value: number; onChange; min? max? step?`；`showValue`（默认开，右侧 mono
当前值）、`formatValue`、`label / hint / disabled`。

### Switch（Radix）
`checked: boolean; onCheckedChange; label? hint? disabled?`。

### Checkbox（Radix）
`checked: boolean | "indeterminate"; onCheckedChange; label? hint? disabled?`。

### RadioGroup（Radix）
`value: string | null; onChange; options: { value; label; description?; disabled? }[]`；
`label / hint / error`。

### SegmentedControl（Radix Tabs 实现）
只渲染分段触发器，不渲染 panel —— 面板由调用方按 value 自切。

```tsx
<SegmentedControl aria-label="检索模式" value={mode} onChange={setMode}
  options={[{ value: "rag", label: "rag" }, { value: "fast", label: "fast" }]} />
```

### FilePicker
`file: File | null; onFile; accept? label? hint? error?`。
visually-hidden native input + 自绘点击/拖放区；选中后显示文件名 + mono 大小。

### Dialog（Radix）
`open; onOpenChange; title; description?; children; footer?`。
居中面板（max-w-md，可用 `contentClassName` 调），Esc/遮罩关闭，自带关闭按钮。

### Drawer（Radix Dialog 变体）
`open; onOpenChange; title?; side: "left" | "right" | "bottom"`。
移动端目录（left）、SourceSpanSheet（right）、底栏（bottom）用。

### Popover（Radix 轻封装）
`trigger`（asChild）+ `children`；`side / align / open / onOpenChange`。

### Tooltip（Radix）
`content; children`（asChild trigger）；桌面 hover + focus 触发，自带 Provider。
只放单行短文案；富内容用 Footnote/Popover。

### Tabs（Radix，下划线式）
`value; onChange; tabs: { value; label; panel; disabled? }[]; aria-label`。

### Menu（Radix DropdownMenu）
`trigger`（asChild）+ `items: { key; label; icon?; danger?; disabled?; onSelect?; separator? }[]`。

### Spinner / Skeleton / SkeletonText
`Spinner({ size })`：仅按钮内（Button loading 已内置）。
`Skeleton({ className })` 块 / `SkeletonText({ lines })` 段落骨架：内容位统一 loading。

### Kbd / Badge / Stamp
- `Kbd`：快捷键键帽（mono）。
- `Badge({ tone: "neutral" | "accent" | "ok" | "warn" | "danger" })`：中性小标签。
- `Stamp({ tone })`：档案戳（-2deg 线框章），只用于「只读 / synthetic / 真实状态」。

### EmptyState（唯一 empty 实现）
`icon: LucideIcon; title; description?; action?`。

```tsx
<EmptyState icon={Inbox} title="还没有原料"
  description="去「导入 Ingest」添加第一条 source。"
  action={<Button size="sm">去导入</Button>} />
```

### ErrorState（唯一 error 实现）
`error: Error | string; title?; onRetry?`。detail 以 mono 呈现。

### Callout
`tone: "notice"(accent) | "info"(ink-3) | "warn" | "danger"`；
`variant: "block" | "inline"`（inline = 顶栏下通栏 notice 条）；
`title? onDismiss?`。左边 2px 语义色条 + 中性底。

### Footnote（签名组件）
`index: number; citation: { title?; sourceId; blockStart?; blockEnd?; snippet? }; onJump?`。
正文内上标 `[n]`（accent mono），hover/focus 出 citation 卡片，点击经 `onJump`
跳 source span（通常接 `useApp.getState().focusSource(sourceId, {start, end})`）。

### Mono
等宽内联（ID/ref/路径/计数），自动 tabular-nums。不给中文正文/按钮/下拉用。

### SectionRule
`no: number | string; title; actions?` → `§01 ── 标题 ───────`。
视图内分节一律用它，不用卡片。

### DefinitionList
`items: { term; definition }[]`：术语—定义双栏，行间发丝线（L0–L3 说明用）。

---

## Composed（src/components/）

### AppShell
`{ children }`。顶栏（字标 + 移动端目录 Drawer 按钮 + UserPicker /
SnapshotPicker / ThemeToggle）+ 桌面目录轨（232px）+ 内容栏
（`max-w-content` = 1080px）+ notice 条（store.notice）+ usersError 离线条
（含重试）+ 历史快照档案戳横幅（Stamp + mono ref +「回到 HEAD」）。

### TocNav
目录轨本体（章节分组 + §编号 + accent 左标线）；`onNavigate?`（移动端关闭
Drawer 用）。章节表导出为 `TOC`。

### UserPicker
store 驱动（users / currentUser / profileNames / recentUsers / setUser /
createUser / ensureNames）。进入时自动 `ensureNames(users)`；过滤词无匹配时
footer 出「新建画像「query」」。

### SnapshotPicker
HEAD + store.snapshots；选中非 HEAD 走 `setSnapshot(ref)`（只读历史态）；
无快照时禁用并注明「尚无版本」。

### ThemeToggle
IconButton（Sun/Moon），接 store.toggleTheme。

### PageHeader
`title; description?; actions?`：serif 页题（24）+ 一行 ink-2 说明 + 右侧操作区。

### CitationList
`citations: { sourceId; blockStart?; blockEnd?; title?; description? }[]; onJump?`：
编号 + 标题/id + block 区间 + 跳转行。

### ClaimRow
`claim: Claim（lib/types）; onJumpCitation?: (c: Citation) => void`：
serif 正文 + Footnote 序列 + mono 锚点；flags（disputed/open_question/…）以
页边注呈现（≥md 右侧边栏，窄屏落正文下）。

### GateLedger
`dropped: SuggestionDropped（lib/api）`：unparsed/repeat/uncited/low_confidence/capped
五栏计数账；>0 栏 danger（uncited）/ warn（其余），0 栏 ink-3。

### SourceSpanSheet
`open; onOpenChange; sourceId; blockStart?; blockEnd?`：右侧 Drawer，
用 `api.getSource` 拉原文（mono 块号 + serif 正文），目标区间 accent-soft 高亮，
附「fetch 精确段」（`api.fetchLocator`）。recall/ask/suggestion/library 共用。

### GraphCanvas（graph/index.ts）
`export const GraphCanvas = lazy(() => import("./GraphCanvas"))` —— 当前为空壳，
视图阶段填充 @xyflow/react + dagre 实现。**只允许经 lazy 引用**（硬性规则 11）。

---

## 状态规范速查（DESIGN.md §4.3）

| 状态 | 做法 |
|---|---|
| loading（内容位） | `Skeleton` / `SkeletonText` |
| loading（操作） | `Button loading` |
| empty | `EmptyState`（文案给下一步动作） |
| error | `ErrorState`（附 ApiError detail + onRetry） |
| offline | 顶栏下 `Callout variant="inline"`（AppShell 已处理 usersError） |
| 历史快照只读 | AppShell 档案戳横幅 + mutation 控件 `disabled` |

状态矩阵总览见隐藏路由 `#/components`（ComponentsGallery）。

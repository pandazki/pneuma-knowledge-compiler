import { useState, type ReactNode } from "react";
import {
  Bell,
  CircleAlert,
  Inbox,
  Info,
  Moon,
  Plus,
  Settings,
  Trash2,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Checkbox } from "@/ui/Checkbox";
import { Combobox } from "@/ui/Combobox";
import { DefinitionList } from "@/ui/DefinitionList";
import { Dialog } from "@/ui/Dialog";
import { Drawer } from "@/ui/Drawer";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { FilePicker } from "@/ui/FilePicker";
import { Footnote } from "@/ui/Footnote";
import { IconButton } from "@/ui/IconButton";
import { Kbd } from "@/ui/Kbd";
import { Menu } from "@/ui/Menu";
import { Mono } from "@/ui/Mono";
import { NumberField } from "@/ui/NumberField";
import { Popover } from "@/ui/Popover";
import { RadioGroup } from "@/ui/RadioGroup";
import { SearchField } from "@/ui/SearchField";
import { SectionRule } from "@/ui/SectionRule";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";
import { Slider } from "@/ui/Slider";
import { Spinner } from "@/ui/Spinner";
import { Stamp } from "@/ui/Stamp";
import { Switch } from "@/ui/Switch";
import { Tabs } from "@/ui/Tabs";
import { TextArea } from "@/ui/TextArea";
import { TextField } from "@/ui/TextField";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";

/** 单个演示格：状态名 + 内容。 */
function Demo({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <p className="font-mono text-12 text-ink-3">{label}</p>
      <div className="flex flex-wrap items-start gap-2">{children}</div>
    </div>
  );
}

const GRID = "grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-2";

/**
 * DESIGN.md §5「components 组件状态页」：全部 primitives 的
 * 默认 / focus 说明 / disabled / error / loading / empty 矩阵（验收截图用）。
 */
export default function ComponentsGallery() {
  const [text, setText] = useState("校样文字");
  const [search, setSearch] = useState("脚注");
  const [area, setArea] = useState("纸、墨、发丝线、脚注。");
  const [num, setNum] = useState<number | null>(2048);
  const [slide, setSlide] = useState(7);
  const [sw, setSw] = useState(true);
  const [check, setCheck] = useState<boolean | "indeterminate">("indeterminate");
  const [radio, setRadio] = useState<string | null>("workstream");
  const [seg, setSeg] = useState("rag");
  const [sel, setSel] = useState<string | null>("contract");
  const [combo, setCombo] = useState<string | null>("head");
  const [tab, setTab] = useState("one");
  const [file, setFile] = useState<File | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="组件状态矩阵"
        description="全部 primitives 的默认 / focus 说明 / disabled / error / loading / empty。此页不进目录，仅供验收与回归。"
      />

      <div className="flex flex-col gap-10">
        {/* §01 按钮 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={1} title="按钮 Button / IconButton" />
          <div className={GRID}>
            <Demo label="variant">
              <Button variant="primary">编译</Button>
              <Button>默认</Button>
              <Button variant="ghost">幽灵</Button>
              <Button variant="danger">放弃</Button>
            </Demo>
            <Demo label="size / icon">
              <Button size="sm">小号</Button>
              <Button size="md">中号</Button>
              <Button>
                <Plus size={14} aria-hidden /> 带图标
              </Button>
              <IconButton aria-label="设置">
                <Settings size={16} aria-hidden />
              </IconButton>
            </Demo>
            <Demo label="disabled / loading">
              <Button disabled>禁用</Button>
              <Button variant="primary" disabled>
                禁用
              </Button>
              <Button variant="primary" loading>
                编译中
              </Button>
            </Demo>
            <Demo label="focus 说明">
              <p className="text-13 text-ink-2">
                Tab 聚焦任意按钮：accent 2px outline + 2px offset。
              </p>
            </Demo>
          </div>
        </section>

        {/* §02 文本输入 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={2} title="文本输入 TextField / SearchField / TextArea" />
          <div className={GRID}>
            <Demo label="默认 / 前后缀">
              <TextField
                label="标题"
                value={text}
                onChange={(e) => setText(e.target.value)}
                hint="输入即受控更新"
                wrapperClassName="w-full"
              />
              <TextField
                label="路径"
                defaultValue="notes/reading.md"
                prefix={<Mono className="text-12">~/</Mono>}
                wrapperClassName="w-full"
              />
            </Demo>
            <Demo label="error / disabled">
              <TextField
                label="user_id"
                defaultValue="bad id!"
                error="只能包含字母、数字与连字符"
                wrapperClassName="w-full"
              />
              <TextField label="禁用" defaultValue="不可编辑" disabled wrapperClassName="w-full" />
            </Demo>
            <Demo label="SearchField">
              <SearchField
                value={search}
                onChange={setSearch}
                placeholder="检索 canonical…"
                wrapperClassName="w-full"
              />
              <SearchField value="" onChange={() => {}} placeholder="空值占位" wrapperClassName="w-full" />
            </Demo>
            <Demo label="TextArea（autoRows）/ error">
              <TextArea
                label="正文"
                value={area}
                onChange={(e) => setArea(e.target.value)}
                autoRows
                maxRows={5}
                hint="随内容增高，至多 5 行"
                wrapperClassName="w-full"
              />
              <TextArea label="错误态" defaultValue="x" error="不能为空" wrapperClassName="w-full" />
            </Demo>
          </div>
        </section>

        {/* §03 选择 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={3} title="选择 Select / Combobox / SegmentedControl" />
          <div className={GRID}>
            <Demo label="Select 默认 / error / disabled">
              <Select
                label="archetype"
                value={sel}
                onChange={setSel}
                options={[
                  { value: "contract", label: "合同 Contract" },
                  { value: "novel", label: "长文 Novel" },
                  { value: "note", label: "笔记 Note" },
                ]}
                wrapperClassName="w-full"
              />
              <Select
                value={null}
                onChange={() => {}}
                options={[]}
                placeholder="必选一项"
                error="不能为空"
                wrapperClassName="w-full"
              />
              <Select
                value="a"
                onChange={() => {}}
                options={[{ value: "a", label: "禁用态" }]}
                disabled
                wrapperClassName="w-full"
              />
            </Demo>
            <Demo label="Combobox（过滤 + 分组）/ disabled">
              <Combobox
                value={combo}
                onChange={setCombo}
                items={[
                  { value: "head", label: "HEAD", group: "版本" },
                  { value: "src-a1b2", label: "初版", keywords: "src-a1b2", group: "版本" },
                  { value: "src-c3d4", label: "二校", keywords: "src-c3d4", group: "版本" },
                ]}
                trigger={<Mono className="text-13">{combo}</Mono>}
                triggerAriaLabel="演示 combobox"
              />
              <Combobox
                value={null}
                onChange={() => {}}
                items={[]}
                trigger={<span>空数据</span>}
                triggerAriaLabel="禁用 combobox"
                disabled
                disabledNote="尚无版本"
              />
            </Demo>
            <Demo label="SegmentedControl">
              <SegmentedControl
                aria-label="检索模式"
                value={seg}
                onChange={setSeg}
                options={[
                  { value: "rag", label: "rag" },
                  { value: "fast", label: "fast" },
                  { value: "deep", label: "deep" },
                ]}
              />
              <SegmentedControl
                aria-label="禁用分段"
                value="a"
                onChange={() => {}}
                options={[{ value: "a", label: "禁用" }]}
                size="sm"
              />
            </Demo>
            <Demo label="focus 说明">
              <p className="text-13 text-ink-2">
                Select / Combobox 触发器与列表项均键盘可达：↑↓ 移动，Enter 选中，Esc 关闭。
              </p>
            </Demo>
          </div>
        </section>

        {/* §04 数值与滑动 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={4} title="数值 NumberField / Slider" />
          <div className={GRID}>
            <Demo label="NumberField 默认 / error / disabled">
              <NumberField
                label="字符预算"
                value={num}
                onChange={setNum}
                min={256}
                max={8192}
                step={256}
                hint="± 按钮与 ↑↓ 键步进 256"
                wrapperClassName="w-full"
              />
              <NumberField value={0} onChange={() => {}} error="超出预算" wrapperClassName="w-full" />
              <NumberField value={42} onChange={() => {}} disabled wrapperClassName="w-full" />
            </Demo>
            <Demo label="Slider 默认 / disabled">
              <Slider
                label="min_confidence"
                value={slide}
                onChange={setSlide}
                min={1}
                max={10}
                wrapperClassName="w-full"
              />
              <Slider label="禁用" value={5} onChange={() => {}} disabled wrapperClassName="w-full" />
            </Demo>
          </div>
        </section>

        {/* §05 开关与勾选 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={5} title="Switch / Checkbox / RadioGroup" />
          <div className={GRID}>
            <Demo label="Switch on / off / disabled">
              <Switch label="统计帧" checked={sw} onCheckedChange={setSw} />
              <Switch label="关闭态" checked={false} onCheckedChange={() => {}} />
              <Switch label="禁用" checked={true} onCheckedChange={() => {}} disabled />
            </Demo>
            <Demo label="Checkbox checked / indeterminate / disabled">
              <Checkbox label="全选" checked={check} onCheckedChange={setCheck} />
              <Checkbox label="已选" checked={true} onCheckedChange={() => {}} />
              <Checkbox label="禁用" checked={false} onCheckedChange={() => {}} disabled />
            </Demo>
            <Demo label="RadioGroup 默认 / error">
              <RadioGroup
                label="source_class"
                value={radio}
                onChange={setRadio}
                options={[
                  { value: "workstream", label: "工作流", description: "持续产生的对话与实验" },
                  { value: "reference", label: "参考资料", description: "稳定的外部文档" },
                ]}
              />
              <RadioGroup
                value={null}
                onChange={() => {}}
                options={[{ value: "x", label: "未选" }]}
                error="必选一类"
              />
            </Demo>
            <Demo label="FilePicker 空 / 已选 / error">
              <FilePicker file={file} onFile={setFile} hint="Markdown / 纯文本" wrapperClassName="w-full" />
              <FilePicker file={null} onFile={() => {}} error="文件过大" wrapperClassName="w-full" />
            </Demo>
          </div>
        </section>

        {/* §06 浮层 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={6} title="浮层 Dialog / Drawer / Popover / Tooltip / Menu / Tabs" />
          <div className={GRID}>
            <Demo label="Dialog / Drawer">
              <Button onClick={() => setDialogOpen(true)}>打开 Dialog</Button>
              <Button onClick={() => setDrawerOpen(true)}>打开 Drawer</Button>
            </Demo>
            <Demo label="Popover / Tooltip / Menu">
              <Popover trigger={<Button>Popover</Button>}>
                <p className="w-48 text-13 text-ink-2">浮层内容：raised 底 + 发丝线 + 浅影。</p>
              </Popover>
              <Tooltip content="快捷键提示见 Kbd">
                <Button variant="ghost">hover 我</Button>
              </Tooltip>
              <Menu
                trigger={<Button variant="ghost">菜单</Button>}
                items={[
                  { key: "a", label: "重命名", icon: <Plus size={13} aria-hidden /> },
                  { key: "b", label: "删除", icon: <Trash2 size={13} aria-hidden />, danger: true },
                  { key: "s", label: "", separator: true },
                  { key: "c", label: "禁用项", disabled: true },
                ]}
              />
            </Demo>
            <Demo label="Tabs（下划线式）" className="sm:col-span-2">
              <Tabs
                aria-label="演示 tabs"
                value={tab}
                onChange={setTab}
                tabs={[
                  { value: "one", label: "文档", panel: <p className="text-14 text-ink-2">第一页面板。</p> },
                  { value: "two", label: "会话", panel: <p className="text-14 text-ink-2">第二页面板。</p> },
                  { value: "three", label: "禁用", panel: null, disabled: true },
                ]}
              />
            </Demo>
          </div>
        </section>

        {/* §07 反馈与状态 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={7} title="反馈 Callout / Empty / Error / Loading / Badge / Stamp" />
          <div className={GRID}>
            <Demo label="Callout 四阶" className="sm:col-span-2">
              <div className="flex w-full flex-col gap-2">
                <Callout tone="notice" title="提示">
                  数据集已回退到默认样例。
                </Callout>
                <Callout tone="info" title="信息">
                  这是一个中性补充说明。
                </Callout>
                <Callout tone="warn" title="警告">
                  服务不可达，面板已降级。
                </Callout>
                <Callout tone="danger" title="错误" onDismiss={() => {}}>
                  编译失败，可关闭此提示。
                </Callout>
              </div>
            </Demo>
            <Demo label="EmptyState / ErrorState" className="sm:col-span-2">
              <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
                <EmptyState
                  icon={Inbox}
                  title="还没有原料"
                  description="去「导入 Ingest」添加第一条 source。"
                  action={<Button size="sm">去导入</Button>}
                />
                <ErrorState error="502 Bad Gateway：compile queue unreachable" onRetry={() => {}} />
              </div>
            </Demo>
            <Demo label="Spinner / Skeleton">
              <Spinner />
              <Spinner size={20} />
              <div className="w-40">
                <SkeletonText lines={3} />
              </div>
            </Demo>
            <Demo label="Badge / Stamp / Kbd">
              <Badge>neutral</Badge>
              <Badge tone="accent">accent</Badge>
              <Badge tone="ok">ok</Badge>
              <Badge tone="warn">warn</Badge>
              <Badge tone="danger">danger</Badge>
              <Stamp tone="warn">历史快照 · 只读</Stamp>
              <Stamp tone="accent">synthetic</Stamp>
              <Kbd>⌘</Kbd>
              <Kbd>K</Kbd>
            </Demo>
          </div>
        </section>

        {/* §08 排版与引用 */}
        <section className="flex flex-col gap-5">
          <SectionRule no={8} title="排版 Footnote / Mono / DefinitionList" />
          <div className={GRID}>
            <Demo label="Footnote（hover 出卡片，点击跳源）" className="sm:col-span-2">
              <p className="prose max-w-measure">
                每个 claim 都能回到精确的 source span
                <Footnote
                  index={1}
                  citation={{
                    title: "编译器原理笔记",
                    sourceId: "src-a1b2",
                    blockStart: 12,
                    blockEnd: 14,
                    snippet: "溯源不是功能，是这套系统的地基。",
                  }}
                  onJump={() => {}}
                />
                ，这是引用门禁成立的前提
                <Footnote
                  index={2}
                  citation={{ sourceId: "src-c3d4", blockStart: 3 }}
                  onJump={() => {}}
                />
                。
              </p>
            </Demo>
            <Demo label="Mono">
              <p className="text-14 text-ink">
                snapshot <Mono>src-c7a3f9</Mono> · tokens <Mono>12,288</Mono>
              </p>
            </Demo>
            <Demo label="DefinitionList" className="sm:col-span-2">
              <DefinitionList
                items={[
                  { term: <Mono>L0</Mono>, definition: "原始材料：对话、文档、实验记录。" },
                  { term: <Mono>L1</Mono>, definition: "source 块索引：可定位、可 fetch。" },
                  { term: <Mono>L2</Mono>, definition: "语义索引：recall 的命中面。" },
                  { term: <Mono>L3</Mono>, definition: "canonical knowledge：带引用的正典。" },
                ]}
              />
            </Demo>
            <Demo label="图标基线（lucide 中性用法）">
              <Bell size={15} aria-hidden className="text-ink-2" />
              <Info size={15} aria-hidden className="text-accent" />
              <CircleAlert size={15} aria-hidden className="text-danger" />
              <Moon size={15} aria-hidden className="text-ink-2" />
            </Demo>
          </div>
        </section>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="确认编译"
        description="把当前未消化的 source 编译进 canonical。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={() => setDialogOpen(false)}>
              编译
            </Button>
          </>
        }
      >
        <p className="text-14 text-ink-2">正文区：表单或说明文字。</p>
      </Dialog>
      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen} side="right" title="侧栏抽屉">
        <p className="p-4 text-14 text-ink-2">SourceSpanSheet 等侧栏内容的容器。</p>
      </Drawer>
    </>
  );
}

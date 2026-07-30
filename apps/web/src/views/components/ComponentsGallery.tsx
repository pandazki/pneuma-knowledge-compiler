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
import { useT } from "@/lib/useT";
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

/** One demo cell: the state's name plus the specimen. */
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
 * DESIGN.md §5, "the components state page": every primitive in its
 * default / focus / disabled / error / loading / empty state (used for acceptance shots).
 *
 * The three editable fields hold `null` until touched so their specimen copy follows the
 * active locale; once typed into, what the user wrote wins.
 */
export default function ComponentsGallery() {
  const t = useT();
  const [text, setText] = useState<string | null>(null);
  const [search, setSearch] = useState<string | null>(null);
  const [area, setArea] = useState<string | null>(null);
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
      <PageHeader title={t("gallery.title")} description={t("gallery.description")} />

      <div className="flex flex-col gap-10">
        {/* §01 buttons */}
        <section className="flex flex-col gap-5">
          <SectionRule no={1} title={t("gallery.section.buttons")} />
          <div className={GRID}>
            <Demo label="variant">
              <Button variant="primary">{t("gallery.button.compile")}</Button>
              <Button>{t("gallery.button.default")}</Button>
              <Button variant="ghost">{t("gallery.button.ghost")}</Button>
              <Button variant="danger">{t("gallery.button.danger")}</Button>
            </Demo>
            <Demo label="size / icon">
              <Button size="sm">{t("gallery.button.small")}</Button>
              <Button size="md">{t("gallery.button.medium")}</Button>
              <Button>
                <Plus size={14} aria-hidden /> {t("gallery.button.withIcon")}
              </Button>
              <IconButton aria-label={t("gallery.button.settings")}>
                <Settings size={16} aria-hidden />
              </IconButton>
            </Demo>
            <Demo label="disabled / loading">
              <Button disabled>{t("gallery.state.disabled")}</Button>
              <Button variant="primary" disabled>
                {t("gallery.state.disabled")}
              </Button>
              <Button variant="primary" loading>
                {t("gallery.button.compiling")}
              </Button>
            </Demo>
            <Demo label={t("gallery.demo.focusNote")}>
              <p className="text-13 text-ink-2">{t("gallery.button.focusHint")}</p>
            </Demo>
          </div>
        </section>

        {/* §02 text input */}
        <section className="flex flex-col gap-5">
          <SectionRule no={2} title={t("gallery.section.text")} />
          <div className={GRID}>
            <Demo label={t("gallery.demo.textDefault")}>
              <TextField
                label={t("gallery.text.titleLabel")}
                value={text ?? t("gallery.text.value")}
                onChange={(e) => setText(e.target.value)}
                hint={t("gallery.text.titleHint")}
                wrapperClassName="w-full"
              />
              <TextField
                label={t("gallery.text.pathLabel")}
                defaultValue="notes/reading.md"
                prefix={<Mono className="text-12">~/</Mono>}
                wrapperClassName="w-full"
              />
            </Demo>
            <Demo label="error / disabled">
              <TextField
                label="user_id"
                defaultValue="bad id!"
                error={t("gallery.text.userIdError")}
                wrapperClassName="w-full"
              />
              <TextField
                label={t("gallery.state.disabled")}
                defaultValue={t("gallery.text.disabledValue")}
                disabled
                wrapperClassName="w-full"
              />
            </Demo>
            <Demo label="SearchField">
              <SearchField
                value={search ?? t("gallery.search.value")}
                onChange={setSearch}
                placeholder={t("gallery.search.placeholder")}
                wrapperClassName="w-full"
              />
              <SearchField
                value=""
                onChange={() => {}}
                placeholder={t("gallery.search.emptyPlaceholder")}
                wrapperClassName="w-full"
              />
            </Demo>
            <Demo label={t("gallery.demo.textArea")}>
              <TextArea
                label={t("gallery.textArea.label")}
                value={area ?? t("gallery.textArea.value")}
                onChange={(e) => setArea(e.target.value)}
                autoRows
                maxRows={5}
                hint={t("gallery.textArea.hint")}
                wrapperClassName="w-full"
              />
              <TextArea
                label={t("gallery.state.error")}
                defaultValue="x"
                error={t("gallery.state.required")}
                wrapperClassName="w-full"
              />
            </Demo>
          </div>
        </section>

        {/* §03 choice */}
        <section className="flex flex-col gap-5">
          <SectionRule no={3} title={t("gallery.section.choice")} />
          <div className={GRID}>
            <Demo label={t("gallery.demo.select")}>
              <Select
                label="archetype"
                value={sel}
                onChange={setSel}
                options={[
                  { value: "contract", label: t("gallery.select.contract") },
                  { value: "novel", label: t("gallery.select.novel") },
                  { value: "note", label: t("gallery.select.note") },
                ]}
                wrapperClassName="w-full"
              />
              <Select
                value={null}
                onChange={() => {}}
                options={[]}
                placeholder={t("gallery.select.requiredPlaceholder")}
                error={t("gallery.state.required")}
                wrapperClassName="w-full"
              />
              <Select
                value="a"
                onChange={() => {}}
                options={[{ value: "a", label: t("gallery.state.disabledLabel") }]}
                disabled
                wrapperClassName="w-full"
              />
            </Demo>
            <Demo label={t("gallery.demo.combobox")}>
              <Combobox
                value={combo}
                onChange={setCombo}
                items={[
                  { value: "head", label: "HEAD", group: t("gallery.combobox.group") },
                  {
                    value: "src-a1b2",
                    label: t("gallery.combobox.first"),
                    keywords: "src-a1b2",
                    group: t("gallery.combobox.group"),
                  },
                  {
                    value: "src-c3d4",
                    label: t("gallery.combobox.second"),
                    keywords: "src-c3d4",
                    group: t("gallery.combobox.group"),
                  },
                ]}
                trigger={<Mono className="text-13">{combo}</Mono>}
                triggerAriaLabel={t("gallery.combobox.demoAria")}
              />
              <Combobox
                value={null}
                onChange={() => {}}
                items={[]}
                trigger={<span>{t("gallery.combobox.emptyTrigger")}</span>}
                triggerAriaLabel={t("gallery.combobox.disabledAria")}
                disabled
                disabledNote={t("gallery.combobox.noneNote")}
              />
            </Demo>
            <Demo label="SegmentedControl">
              <SegmentedControl
                aria-label={t("gallery.segmented.modeAria")}
                value={seg}
                onChange={setSeg}
                options={[
                  { value: "rag", label: "rag" },
                  { value: "fast", label: "fast" },
                  { value: "deep", label: "deep" },
                ]}
              />
              <SegmentedControl
                aria-label={t("gallery.segmented.disabledAria")}
                value="a"
                onChange={() => {}}
                options={[{ value: "a", label: t("gallery.state.disabled") }]}
                size="sm"
              />
            </Demo>
            <Demo label={t("gallery.demo.focusNote")}>
              <p className="text-13 text-ink-2">{t("gallery.select.focusHint")}</p>
            </Demo>
          </div>
        </section>

        {/* §04 numbers and sliding */}
        <section className="flex flex-col gap-5">
          <SectionRule no={4} title={t("gallery.section.numbers")} />
          <div className={GRID}>
            <Demo label={t("gallery.demo.numberField")}>
              <NumberField
                label={t("gallery.number.label")}
                value={num}
                onChange={setNum}
                min={256}
                max={8192}
                step={256}
                hint={t("gallery.number.hint")}
                wrapperClassName="w-full"
              />
              <NumberField
                value={0}
                onChange={() => {}}
                error={t("gallery.number.error")}
                wrapperClassName="w-full"
              />
              <NumberField value={42} onChange={() => {}} disabled wrapperClassName="w-full" />
            </Demo>
            <Demo label={t("gallery.demo.slider")}>
              <Slider
                label="min_confidence"
                value={slide}
                onChange={setSlide}
                min={1}
                max={10}
                wrapperClassName="w-full"
              />
              <Slider
                label={t("gallery.state.disabled")}
                value={5}
                onChange={() => {}}
                disabled
                wrapperClassName="w-full"
              />
            </Demo>
          </div>
        </section>

        {/* §05 toggles and checks */}
        <section className="flex flex-col gap-5">
          <SectionRule no={5} title={t("gallery.section.toggles")} />
          <div className={GRID}>
            <Demo label="Switch on / off / disabled">
              <Switch label={t("gallery.switch.label")} checked={sw} onCheckedChange={setSw} />
              <Switch label={t("gallery.state.off")} checked={false} onCheckedChange={() => {}} />
              <Switch
                label={t("gallery.state.disabled")}
                checked={true}
                onCheckedChange={() => {}}
                disabled
              />
            </Demo>
            <Demo label="Checkbox checked / indeterminate / disabled">
              <Checkbox label={t("gallery.checkbox.all")} checked={check} onCheckedChange={setCheck} />
              <Checkbox
                label={t("gallery.checkbox.checked")}
                checked={true}
                onCheckedChange={() => {}}
              />
              <Checkbox
                label={t("gallery.state.disabled")}
                checked={false}
                onCheckedChange={() => {}}
                disabled
              />
            </Demo>
            <Demo label={t("gallery.demo.radioGroup")}>
              <RadioGroup
                label="source_class"
                value={radio}
                onChange={setRadio}
                options={[
                  {
                    value: "workstream",
                    label: t("gallery.radio.workstream"),
                    description: t("gallery.radio.workstreamNote"),
                  },
                  {
                    value: "reference",
                    label: t("gallery.radio.reference"),
                    description: t("gallery.radio.referenceNote"),
                  },
                ]}
              />
              <RadioGroup
                value={null}
                onChange={() => {}}
                options={[{ value: "x", label: t("gallery.radio.unselected") }]}
                error={t("gallery.radio.error")}
              />
            </Demo>
            <Demo label={t("gallery.demo.filePicker")}>
              <FilePicker
                file={file}
                onFile={setFile}
                hint={t("gallery.filePicker.hint")}
                wrapperClassName="w-full"
              />
              <FilePicker
                file={null}
                onFile={() => {}}
                error={t("gallery.filePicker.error")}
                wrapperClassName="w-full"
              />
            </Demo>
          </div>
        </section>

        {/* §06 overlays */}
        <section className="flex flex-col gap-5">
          <SectionRule no={6} title={t("gallery.section.overlays")} />
          <div className={GRID}>
            <Demo label="Dialog / Drawer">
              <Button onClick={() => setDialogOpen(true)}>{t("gallery.overlay.openDialog")}</Button>
              <Button onClick={() => setDrawerOpen(true)}>{t("gallery.overlay.openDrawer")}</Button>
            </Demo>
            <Demo label="Popover / Tooltip / Menu">
              <Popover trigger={<Button>Popover</Button>}>
                <p className="w-48 text-13 text-ink-2">{t("gallery.popover.body")}</p>
              </Popover>
              <Tooltip content={t("gallery.tooltip.content")}>
                <Button variant="ghost">{t("gallery.tooltip.trigger")}</Button>
              </Tooltip>
              <Menu
                trigger={<Button variant="ghost">{t("gallery.menu.trigger")}</Button>}
                items={[
                  {
                    key: "a",
                    label: t("gallery.menu.rename"),
                    icon: <Plus size={13} aria-hidden />,
                  },
                  {
                    key: "b",
                    label: t("gallery.menu.delete"),
                    icon: <Trash2 size={13} aria-hidden />,
                    danger: true,
                  },
                  { key: "s", label: "", separator: true },
                  { key: "c", label: t("gallery.menu.disabledItem"), disabled: true },
                ]}
              />
            </Demo>
            <Demo label={t("gallery.demo.tabs")} className="sm:col-span-2">
              <Tabs
                aria-label={t("gallery.tabs.aria")}
                value={tab}
                onChange={setTab}
                tabs={[
                  {
                    value: "one",
                    label: t("gallery.tabs.one"),
                    panel: <p className="text-14 text-ink-2">{t("gallery.tabs.onePanel")}</p>,
                  },
                  {
                    value: "two",
                    label: t("gallery.tabs.two"),
                    panel: <p className="text-14 text-ink-2">{t("gallery.tabs.twoPanel")}</p>,
                  },
                  { value: "three", label: t("gallery.state.disabled"), panel: null, disabled: true },
                ]}
              />
            </Demo>
          </div>
        </section>

        {/* §07 feedback and status */}
        <section className="flex flex-col gap-5">
          <SectionRule no={7} title={t("gallery.section.feedback")} />
          <div className={GRID}>
            <Demo label={t("gallery.demo.callout")} className="sm:col-span-2">
              <div className="flex w-full flex-col gap-2">
                <Callout tone="notice" title={t("gallery.callout.noticeTitle")}>
                  {t("gallery.callout.noticeBody")}
                </Callout>
                <Callout tone="info" title={t("gallery.callout.infoTitle")}>
                  {t("gallery.callout.infoBody")}
                </Callout>
                <Callout tone="warn" title={t("gallery.callout.warnTitle")}>
                  {t("gallery.callout.warnBody")}
                </Callout>
                <Callout tone="danger" title={t("gallery.callout.dangerTitle")} onDismiss={() => {}}>
                  {t("gallery.callout.dangerBody")}
                </Callout>
              </div>
            </Demo>
            <Demo label="EmptyState / ErrorState" className="sm:col-span-2">
              <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
                <EmptyState
                  icon={Inbox}
                  title={t("gallery.empty.title")}
                  description={t("gallery.empty.description")}
                  action={<Button size="sm">{t("gallery.empty.action")}</Button>}
                />
                <ErrorState error={t("gallery.errorState.detail")} onRetry={() => {}} />
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
              <Stamp tone="warn">{t("gallery.stamp.snapshot")}</Stamp>
              <Stamp tone="accent">synthetic</Stamp>
              <Kbd>⌘</Kbd>
              <Kbd>K</Kbd>
            </Demo>
          </div>
        </section>

        {/* §08 typography and citations */}
        <section className="flex flex-col gap-5">
          <SectionRule no={8} title={t("gallery.section.typography")} />
          <div className={GRID}>
            <Demo label={t("gallery.demo.footnote")} className="sm:col-span-2">
              <p className="prose max-w-measure">
                {t("gallery.footnote.lead")}
                <Footnote
                  index={1}
                  citation={{
                    title: t("gallery.footnote.citationTitle"),
                    sourceId: "src-a1b2",
                    blockStart: 12,
                    blockEnd: 14,
                    snippet: t("gallery.footnote.citationSnippet"),
                  }}
                  onJump={() => {}}
                />
                {t("gallery.footnote.tail")}
                <Footnote
                  index={2}
                  citation={{ sourceId: "src-c3d4", blockStart: 3 }}
                  onJump={() => {}}
                />
                {t("gallery.footnote.stop")}
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
                  { term: <Mono>L0</Mono>, definition: t("gallery.level.l0") },
                  { term: <Mono>L1</Mono>, definition: t("gallery.level.l1") },
                  { term: <Mono>L2</Mono>, definition: t("gallery.level.l2") },
                  { term: <Mono>L3</Mono>, definition: t("gallery.level.l3") },
                ]}
              />
            </Demo>
            <Demo label={t("gallery.demo.icons")}>
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
        title={t("gallery.dialog.title")}
        description={t("gallery.dialog.description")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              {t("gallery.dialog.cancel")}
            </Button>
            <Button variant="primary" onClick={() => setDialogOpen(false)}>
              {t("gallery.button.compile")}
            </Button>
          </>
        }
      >
        <p className="text-14 text-ink-2">{t("gallery.dialog.body")}</p>
      </Dialog>
      <Drawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        side="right"
        title={t("gallery.drawer.title")}
      >
        <p className="p-4 text-14 text-ink-2">{t("gallery.drawer.body")}</p>
      </Drawer>
    </>
  );
}

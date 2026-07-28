---
name: "Pneuma Knowledge Compiler"
description: "A dual-theme transit atlas for running and tracing an open-source personal knowledge compiler."
colors:
  porcelain-canvas: "#f2f1e9"
  porcelain-card: "#fffef9"
  porcelain-muted: "#e7ebe8"
  atlas-navy: "#0b203a"
  atlas-slate: "#40556b"
  porcelain-border: "#cdd6d5"
  midnight-canvas: "#07172b"
  midnight-card: "#0e2542"
  midnight-muted: "#132d4c"
  enamel-ink: "#f7f2e6"
  enamel-slate: "#c3cfda"
  midnight-border: "#294561"
  action-coral-day: "#df4a2b"
  action-coral-night: "#f06a43"
  route-green-day: "#16845b"
  route-green-night: "#4ad39c"
  route-cobalt-day: "#1766c2"
  route-cobalt-night: "#62a3ff"
  route-amber-day: "#d9900d"
  route-amber-night: "#f6bd4d"
  route-scarlet-day: "#d73a49"
  route-scarlet-night: "#ff6675"
  inferred-violet-day: "#6d48bd"
  inferred-violet-night: "#b69cff"
  destination-paper-day: "#fffaf0"
  destination-paper-night: "#f8f2e6"
typography:
  hero:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "clamp(2.7rem, 5.2vw, 5.4rem)"
    fontWeight: 680
    lineHeight: 0.96
    letterSpacing: "-0.065em"
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "clamp(3rem, 7vw, 6.5rem)"
    fontWeight: 360
    lineHeight: 1.03
    letterSpacing: "0"
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 660
    lineHeight: 1.05
    letterSpacing: "-0.04em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 660
    lineHeight: 1.2
    letterSpacing: "-0.035em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  control:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 540
    lineHeight: 1.2
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 540
    lineHeight: 1.4
    letterSpacing: "0.04em"
  microcopy:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 540
    lineHeight: 1.4
    letterSpacing: "0.07em"
  data:
    fontFamily: "SFMono-Regular, Cascadia Code, Roboto Mono, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  control: "8px"
  sheet: "14px"
  stage: "22px"
  route: "999px"
spacing:
  "1": "0.25rem"
  "2": "0.5rem"
  "3": "0.75rem"
  "4": "1rem"
  "5": "1.25rem"
  "6": "1.5rem"
  "8": "2rem"
components:
  button-primary:
    backgroundColor: "{colors.action-coral-day}"
    textColor: "{colors.destination-paper-day}"
    typography: "{typography.control}"
    rounded: "{rounded.route}"
    padding: "0 1rem"
    height: "2.5rem"
  button-secondary:
    backgroundColor: "{colors.porcelain-muted}"
    textColor: "{colors.atlas-navy}"
    typography: "{typography.control}"
    rounded: "{rounded.route}"
    padding: "0 1rem"
    height: "2.5rem"
  chip:
    backgroundColor: "{colors.porcelain-muted}"
    textColor: "{colors.atlas-navy}"
    typography: "{typography.microcopy}"
    rounded: "{rounded.route}"
    padding: "0.25rem 0.625rem"
  card:
    backgroundColor: "{colors.porcelain-card}"
    textColor: "{colors.atlas-navy}"
    rounded: "{rounded.sheet}"
    padding: "1.25rem"
  input:
    backgroundColor: "{colors.porcelain-muted}"
    textColor: "{colors.atlas-navy}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 0.75rem"
    height: "2.5rem"
---

# Design System: Pneuma Knowledge Compiler

## Overview

**Creative North Star: "Knowledge Transit Atlas"**

Pneuma Knowledge Compiler 把系统架构画成一张可以运行的城市线路图，而不是把功能拆成一组后台管理卡片。原始材料、权威存储、双层检索、编译门与 Canonical Git 是六个站点；实线与虚线说明权威层和可重建层，真实 source、claim、canonical 与 patch 则沿线路形成可查验的行程。

日间模式是一张瓷白城市导视图：奶白画布、深海军蓝文字、珊瑚动作与清晰线路。夜间模式是一间午夜珐琅控制室：深蓝表面、暖白文字和更明亮的线路色。两种主题分别调校表面、阴影与对比度，但站点、线路责任、状态含义和证据路径完全一致。

**Key Characteristics:**

- 六站知识线路是第一视口的主视觉与架构说明，不是装饰插图。
- 绿色、钴蓝、琥珀与猩红线路编码系统责任；珊瑚色单独承担动作和到站信号。
- 真实 dataset 点亮 source → claim → canonical → patch/Git 行程，不使用伪造 KPI。
- 站点页把现有任务装入宽阔的 destination sheet，而非永久展示密集表单网格。
- 桌面与 390px 移动端都呈现完整六站线路，并持续显示 SYNTHETIC 披露。
- 系统无衬线字负责阅读，等宽字只负责线路代码、路径、ID、ref 与运行元数据。

## Colors

色彩由双主题中性材料、一个动作色和四条责任线路组成；线路颜色是系统语义，不是卡片分类装饰。

### Primary

- **Action Coral:** 日间与夜间分别调校，用于主要动作、到站提示和少量当前状态，不替代线路责任色。
- **Atlas Navy / Enamel Ink:** 日间以海军蓝为主要文字和地图底色，夜间以暖白珐琅字承载阅读层。

### Secondary

- **Route Green:** Source 与 PostgreSQL 的权威来源线路，同时承载 verified / success。
- **Route Cobalt:** L1 词法检索、检索实验和信息状态。
- **Route Amber:** L2 语义检索、主动提示与开放问题。
- **Route Scarlet:** 编译门、Canonical Git、patch 行程与 disputed / danger。

### Tertiary

- **Inferred Violet:** 仅表示推断证据，不参与六站架构线路。
- **Destination Paper:** 地图中的站点说明 sheet 在两种主题下都保持纸张式高对比阅读面。

### Neutral

- **Porcelain Daylight:** 瓷白画布、暖白卡片、浅青灰辅助面、海军蓝字与冷灰边界。
- **Midnight Enamel:** 午夜蓝画布、深蓝卡片、蓝灰辅助面、暖白字与钢蓝边界。

### Named Rules

**The Route Identity Rule.** 绿色、钴蓝、琥珀和猩红只编码系统责任、线路与对应状态；不得为任意卡片轮换配色。

**The Coral Action Rule.** 珊瑚色回答“接下来做什么”或“哪一站刚到达”；它不与猩红编译线路争夺语义。

**The Theme Continuity Rule.** 日夜主题可以改变材料、亮度与阴影，但六站顺序、线路含义、状态映射和焦点可见性不得变化。

## Typography

**Display Font:** 系统无衬线字族（含 Noto Sans SC、PingFang SC 与 Microsoft YaHei 回退）

**Body Font:** 同一系统无衬线字族

**Label/Mono Font:** SFMono-Regular、Cascadia Code、Roboto Mono、Consolas

**Character:** 首页 Hero 像城市导视墙上的目的地宣言，短、重、紧；canonical display 则保持轻字重，让长文标题与操作舞台分层。正文保持开源技术说明的直接性。等宽字形成线路代码和运行凭证的第二声部，但不进入普通叙述。

### Hierarchy

- **Hero**（680，流体尺寸，0.96）：仅用于系统线路首页的主宣言。
- **Display**（360，流体尺寸，1.03）：用于 canonical 文档大标题。
- **Headline**（660，2.25rem，1.05）：章节级旅程标题和关键对象。
- **Title**（660，1.75rem，1.2）：destination sheet、统计与局部任务标题。
- **Body**（400，1rem，1.6）：解释、知识正文与操作反馈。
- **Control**（540，0.9375rem，1.2）：按钮、导航与表单控制。
- **Label**（540，0.8125rem，0.04em）：站点名、路由标签与辅助标题。
- **Microcopy**（540，0.75rem，0.07em）：12px 是中文注释、状态和线路说明的系统下限。
- **Data**（400，0.75rem，1.5）：站点代码、路径、ID、Git ref、时间和模型 lineage。

### Named Rules

**The Readable Annotation Rule.** 所有用户可见的注释与元数据至少为 12px；生成稿中的更小英文微字不得成为产品规范。

**The Machine Wayfinding Rule.** 等宽字只用于站点代码、路径、标识符、版本与运行数据；中文标题、说明和动作保持无衬线字。

## Layout

桌面端使用 212px 分组线路导航、68px 顶部状态条和单一主舞台；1180px 以下导航收窄至 180px。系统线路首页在 1380px 最大宽度内先呈现宣言与路线动作，再放置至少 520px 高的六站线路壁画、真实 destination sheet、synthetic manifest 和四段证据行程。

820px 以下进入移动编排：导航变为横向站点带，主宣言单列，SVG 壁画替换为完整的六站纵向有序线路，destination sheet 落在线路之后。该编排在 390px 视口仍显示 S0、P0、L1、L2、C1、G1 全部站点；不允许用横向裁切或只显示当前站代替完整系统心智模型。

除首页外，每个任务都进入带站点代码、线路色和说明的 `RouteFrame`。工作内容位于 22px 圆角 destination workbench 中；移动端 workbench 与视口边缘对齐，功能范围不缩减。

**The Whole Line Rule.** 六站线路在桌面和 390px 都必须完整可达；响应式只改变线路方向和说明位置，不删除站点。

**The Station Sheet Rule.** 表单、列表和调试面板只在明确站点的 workbench 中出现；首页不退化为功能卡片或 bento dashboard。

## Elevation & Depth

系统使用宽而柔和的城市导视层次。瓷白模式以低透明海军蓝阴影托起导航、地图舞台和 destination sheet；午夜模式增加黑色深度以分离珐琅表面。站点线路本身依靠颜色、粗细、虚实与圆形换乘节点建立层级，不额外发光。

### Shadow Vocabulary

- **Transit Sheet:** 日间 `0 8px 26px rgb(20 45 65 / 8%)`，夜间 `0 10px 30px rgb(0 0 0 / 24%)`；用于站点 workbench 和轻量卡片。
- **Control Room Overlay:** 日间 `0 24px 70px rgb(5 22 41 / 24%)`，夜间 `0 28px 80px rgb(0 0 0 / 58%)`；用于弹窗和真正脱离线路舞台的浮层。
- **Route Mural:** 首页地图使用一层宽幅海军蓝环境阴影，表达整块导视墙而非独立卡片集合。

### Named Rules

**The Layered Enamel Rule.** 阴影只区分画布、舞台、sheet 与浮层四个材料层；线路和普通状态不得添加霓虹光晕。

## Shapes

形状语言来自城市导视：8px 控件倒角、14px sheet、22px 舞台与完整胶囊按钮共同组成柔和但清晰的层级。站点、换乘节点、状态点和 Pneuma 四点标记使用圆形；地图连接使用圆头粗线。任务 workbench 保留大圆角，内部数据表仍可使用较小倒角以维持密度。

**The Route Geometry Rule.** 圆形代表站点或状态，胶囊代表动作或当前路线，宽圆角矩形代表 destination sheet；不得把所有内容都包装成同一种胶囊。

## Components

### Buttons

- **Shape:** 标准高度 40px，小号 32px，完整胶囊轮廓。
- **Primary:** Action Coral 底配暖白文字；用于每个阶段唯一的主要出发动作。
- **Secondary / Ghost / Outline:** 中性辅助面或透明底；outline 使用内嵌 1px 边界，不制造额外卡片。
- **Hover / Focus:** hover 只改变中性面或轻微透明度；键盘焦点使用主题钴蓝 2px 环并留 2px 间距。

### Chips

- **Style:** 中性辅助面、完整胶囊、4px × 10px 内边距和 12px 文本。
- **State:** 可选 7px 状态点；颜色遵循 Route Identity Rule。

### Cards / Containers

- **Corner Style:** 普通 card 14px，主 workbench 22px，首页 route mural 30px。
- **Background:** 日间为暖白瓷面，夜间为深蓝珐琅面。
- **Shadow Strategy:** 普通 card 使用 Transit Sheet；静态列表行不单独投影。
- **Internal Padding:** 常见为 16px、20px 或 24px。

### Inputs / Fields

- **Style:** 浅色辅助面、顶部 8px 倒角和强调底边，标准字号 15px。
- **Focus:** 底边切换为当前站点线路色，同时保留全局可见焦点环。
- **Error / Disabled:** error 使用 disputed / scarlet；disabled 通过不透明度降低但保留标签和边界。

### Navigation

桌面导航按“线路 / 运行演示 / 核对证据 / 探索内部”分组。active 项使用主题反相胶囊和珊瑚到站点；移动端保留同一顺序、图标和短标签并允许横向滚动。SYNTHETIC 在桌面底部与移动品牌旁持续可见。

### Six-station Route Map

桌面 SVG 用绿色实线连接 S0 Source 与 P0 PostgreSQL，钴蓝和琥珀虚线分别经过 L1 Meilisearch 与 L2 Qdrant，在 C1 编译门汇合并以猩红实线到达 G1 Canonical Git。选中站点放大 halo 并打开 destination sheet；真实 trace 会降低无关线路透明度并加粗有效路径。移动端以六项纵向有序线路完整替代 SVG。

### Destination Sheet

地图右上方的暖白 sheet 展示当前站点职责；当 source 存在真实 citation 时，切换为 LIVE TRACE，列出 source/span、claim anchor、canonical path 与 patch/ref，并提供查验原文入口。两种主题都保持高对比纸面，而不是随背景变成低对比暗卡。

### Evidence Journey

首页 manifest 之后以四站行程展示 source → claim → canonical → patch/Git，并直接跳转到对应功能。所有值来自当前 model；没有数据时显示“等待第一份材料”的真实空态。

### Synthetic Disclosure

桌面导航显示 `OPEN DEMO / SYNTHETIC · OPC`，移动品牌旁显示完整 `SYNTHETIC`，首页 manifest 再次说明中文人设与数据均为仓库内置合成内容。任何断点都不得把披露缩写为不可理解的代号或完全隐藏。

## Do's and Don'ts

### Do:

- **Do** 让六站顺序、线路颜色、实线/虚线含义在日夜主题和 390px 视口中保持一致。
- **Do** 从当前 dataset 派生 source、claim、canonical 和 patch/ref，缺失时呈现真实空态。
- **Do** 把复杂任务放入具名站点的 destination workbench，并保留全局 owner、snapshot 与 theme 控制。
- **Do** 在桌面、移动端和首页内容层重复但不夸张地披露 SYNTHETIC。
- **Do** 为线路站点、导航、按钮和移动列表提供键盘操作、可见焦点与 reduced-motion 回退。

### Don't:

- **Don't** 把首页改成 KPI 卡片、bento dashboard、上传 dropzone 大拼盘或后台表单网格。
- **Don't** 为任意内容卡轮换使用四条线路色，或把 Coral 与 Scarlet 混成同一种状态。
- **Don't** 在移动端裁掉 L1/L2 分支、编译门或 Git 终点；390px 必须能走完整条线路。
- **Don't** 用假客户、假 benchmark、假计数或生成稿英文 filler 替代仓库内的真实 synthetic 数据。
- **Don't** 把夜间模式实现成简单反色，或给线路添加霓虹光晕和无语义的装饰动画。

# PKC 桌面应用

[English](README.md)

面向个人知识库 home 的 Tauri 3 开发者版菜单栏客户端。宽 380 点、随内容调整高度的面板包含 Dashboard、Search、
Settings 三个页签。应用读取 `~/.pkc`（或 `PKC_HOME`），自行探测机器状态，再叠加各引擎
的 `/home/status` 响应。应用不写 home 文件：启动、停止、重启、选库、凭据和偏好设置
都交给 `pkchome`。登录时启动通过 Tauri autostart 插件调用操作系统，并且默认开启：首次启动
由应用自己向系统注册，并把这次决定记入配置目录中 `preferences.json` 的 `login` 键。只要存在
记录——无论是应用的默认还是设置里的开关——应用便不再决定，因此 Owner 关掉之后不会被重新打开；
注册被系统拒绝时不写入任何记录，设置面板将开关显示为关闭，并说明系统给出的原因。

## 开发

使用 Node 22.13+（本次使用 Node 25）、pnpm 11.21.0、Rust 1.95.0（由 `rust-toolchain.toml` 选择），并安装平台要求的
[Tauri 前置依赖](https://v2.tauri.app/start/prerequisites/)。在本目录运行：

```sh
pnpm install
pnpm tauri dev
```

点击菜单栏的书本图标打开面板。Esc、点击外部或关闭按钮会隐藏面板；退出托盘不会停止
知识库。右键菜单提供 Open PKC、Search、Call the library、Quit。Linux 桌面若不提供
托盘坐标，面板会打开在当前显示器右上角。

独立手动冒烟时，先将 `PKC_HOME` 指向临时空目录再启动；图标应为灰色，面板应说明
`pkchome setup`。只有确实要操作实际 home 时，才对它使用 Start/Stop。

```sh
PKC_HOME=/tmp/pkc-tray-smoke pnpm tauri dev
pnpm test
cd src-tauri
cargo test
cargo fmt --check
```

前端依赖 Tauri IPC 桥接；单独运行 `pnpm dev` 可以提供资源，但不能显示实时状态。
首次 React 渲染前先读取 Rust 缓存，随后通过事件更新。打开面板时先提交缓存对应的 DOM，
再显示原生面板；打开路径没有状态转圈或 HTTP 请求。

## 构建与发布

```sh
pnpm run build
pnpm tauri build --debug
pnpm tauri build
# 从源图重新生成平台图标：
pnpm tauri icon src-tauri/icons/app.svg
```

产物位于 `src-tauri/target/{debug,release}/bundle/`：macOS 为 `macos/PKC.app` 与
`dmg/*.dmg`；Windows 为 `nsis/*-setup.exe` / `msi/*.msi`；Linux 为 `deb/*.deb`、
`rpm/*.rpm`、`appimage/*.AppImage`，具体取决于本机构建工具。请在目标操作系统上构建。
签名、公证、发布属于分发步骤；本目录没有配置签名身份或自动更新器。

将 `PKC.app` 放入 `~/Applications` 或 `/Applications`。`pkchome tray` 会依次查找并
打开应用；未安装时打印[发布页面](https://github.com/pandazki/pneuma-knowledge-compiler/releases)。

Tauri、CLI 与 Wry 运行时精确锁定 `3.0.0-alpha.1`；构建包、官方插件和 JS API
使用 `3.0.0-alpha.0`，两份锁文件一起提交。Builder 显式选择 Wry，不使用 CEF 或本地依赖分支。

macOS 使用 Accessory 激活策略及项目内的 `native_panel.rs` AppKit 适配。
已有窗口与 webview 始终由 Tauri 持有；适配层赋予其 NSPanel 行为，检查主线程访问，
处理键盘焦点与尺寸，不自行 retain/release 窗口，也不依赖 `tauri-nspanel`。
模板图标和独立彩色状态点保留。

`tray-icon 0.25.1` 已包含 macOS 27 点击事件修复：左键打开面板，右键使用依赖的原生菜单。
应用层临时菜单兼容代码已删除。开发者版明确采用锁定版本的 Tauri 3 alpha。

## 行为与验证限制

- Rust 轮询间隔为 5 秒，面板打开时为 2 秒；端点超时时，一轮受限探测可能更久。
  Docker 和详细状态请求在 2 秒后超时，TCP 探测在 350 毫秒后超时。仅时间变化不会发状态事件。
- 绿色表示 Docker、四项服务和所有引擎正常；琥珀色表示 Docker 可达，但服务、引擎或配置
  需要关注；红色表示 Docker 不可达；灰色表示 `config.yaml` 不存在。详细状态失败不改变图标。
- 快速召回向当前库租户的 `/v1/users/<tenant>/recall` 发送 `mode: fast`。
  canonical 路径通过公开 dataset 解析为控制台文档 ID。源链接保留源 ID 与块号；文档 ID
  不可用时，路径保留为纯文本，并显示其源引用。不导入框架源码。
- 密钥通过密码框输入，仅以 stdin 传给 `pkchome credentials set KEY --from-stdin`。
  Rust 检查命令范围。失败时，可关闭的提示框显示 stderr，并遮盖本次提交的密钥。
  密钥不持久化到前端存储，也不进入 argv。每次操作重新读取已安装 CLI 的路径；macOS
  启动时只解析一次登录 shell 的 PATH。
- Call the library 在默认浏览器中打开当前知识库控制台的 `#/steward?call=1`，而不在面板内
  打开：面板的内容安全策略只到 `ipc:`，本安装包未声明麦克风用途，失焦即隐藏的浮层也不是
  通话的地方。端口与租户在点击时从磁盘读取，并向引擎询问能否发起通话
  （`GET /v1/users/<tenant>/call`）。没有当前知识库、引擎已停止、部署缺少语音密钥，或引擎
  版本早于通话功能时，面板会打开在 Dashboard 并在消息行给出原因；该菜单项始终可点，因为
  置灰说不出究竟是哪一种。此处未对运行中的引擎与真实浏览器做验证。
- 等待重试与已暂停任务可用**立即继续**恢复，见下文；终止失败另行处理。
  可选全局快捷键尚未实现。固定的托盘锚定尺寸无需保存窗口偏好。
- 其他平台、登录启动和长期运行需单独验证。

## 继续任务与导入内容

面板区分三个操作：

- **立即继续（N）**：有等待重试或已暂停任务时显示。额度、登录或网络恢复后，
  解除等待并重新开始重试周期，保留任务 ID 和失败历史，不改动正在执行或已经结束的任务。
  如需 worker 自动执行代理编译，需开启无人值守编译。
- **导入新内容**：扫描监看目录中的新增会话和内容变更，不解除任务的重试等待。
- **重启服务**：重新启动所有知识库的引擎，保留任务的重试时间。

队列显示等待重试、已暂停的数量，以及本地时区的下次重试日期和时间。
继续操作调用当前知识库租户的 `POST /jobs/resume`，显式传入 `include_waiting: true`。
此功能需要同时更新 tray 和引擎；旧引擎会显示更新提示，不会忽略等待任务却报告成功。
API 和 CLI 默认仍只恢复已暂停任务，只有 API 显式指定时才同时恢复等待中的任务。

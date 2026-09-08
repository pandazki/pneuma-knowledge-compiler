# PKC 桌面应用

[English](README.md)

面向个人知识库 home 的 Tauri 2 菜单栏客户端。360 × 520 面板包含 Dashboard、Search、
Settings 三个页签。应用读取 `~/.pkc`（或 `PKC_HOME`），自行探测机器状态，再叠加各引擎
的 `/home/status` 响应。应用不写 home 文件：启动、停止、重启、选库、凭据和偏好设置
都交给 `pkchome`。开机启动通过 Tauri autostart 插件调用操作系统。

## 开发

使用 Node 22.13+（本次使用 Node 25）、pnpm 11.21.0、Rust 1.88+，并安装平台要求的
[Tauri 前置依赖](https://v2.tauri.app/start/prerequisites/)。在本目录运行：

```sh
pnpm install
pnpm tauri dev
```

点击菜单栏的书本图标打开面板。Esc、点击外部或关闭按钮会隐藏面板；退出托盘不会停止
知识库。右键菜单提供 Open PKC、Search、Quit。Linux 桌面若不提供托盘坐标，面板会
打开在当前显示器右上角。

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

`package.json` 与 `src-tauri/Cargo.toml` 精确固定直接依赖版本；`pnpm-lock.yaml` 固定
前端依赖图。原生 Tauri 为 2.11.5、Tauri build 为 2.6.3、shell 为 2.3.6、autostart 为 2.5.1、positioner 为 2.3.4；Rust 依赖在这些次版本内浮动，由 `Cargo.lock` 钉住。macOS 使用
[Tauri 2 分支的 tauri-nspanel 2.0.1](https://github.com/ahkohd/tauri-nspanel/tree/v2)、
Accessory 激活策略、真正的 NSPanel，以及模板图标加独立彩色状态点。
Tauri CLI 2.8.1 的开发版本检查会对 Cargo 的精确 `=version` 语法打印诊断；Cargo 本身
接受这些精确固定版本。

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
- 失败任务重试按要求禁用并提供提示。可选全局快捷键未实现。固定的托盘锚定尺寸无需保存窗口偏好。
- 实现环境中，前端构建、五项状态与路由测试、图标生成、CLI 启动与回退检查均通过。
  前端包从本地 pnpm 10 缓存恢复；构建与测试使用 pnpm 11。原生构建因 GitHub DNS
  不可用，在编译前停止；没有生成 `Cargo.lock`、应用包或安装器。因此，首次成功解析 Cargo
  依赖时仍需锁定 nspanel 分支提交。
- `pnpm tauri dev` 在 `listen EPERM 127.0.0.1:1420` 处停止。没有出现原生 GUI，因此
  托盘锚定、失焦隐藏、外观、开机启动和实际引擎 HTTP 流程仍需在不受限主机上冒烟。
  未切换普通窗口回退：依赖获取前无法判断 nspanel 的兼容性。

# 文档截图

[English](README.md) | **简体中文**

这些截图来自当前 `apps/web` 界面，使用 [docs_fixtures.mjs](../../scripts/dev/docs_fixtures.mjs) 中**完全虚构的数据**。港湾笔记及其来源、主张、历史和对话都是合成示例，不是真实知识库、已完成的 agent 执行记录或回答质量证据。

| 截图 | 展示内容 |
|---|---|
| `library-{en,zh}-{light,dark}.png` | 正本阅读器、主张锚点和来源引用 |
| `history-{en,zh}-{light,dark}.png` | 两次虚构提交及其逐条主张变化 |
| `steward-{en,zh}-{light,dark}.png` | Steward 页中的合成对话与语音入口；没有启动通话 |

## 复现

在仓库根目录运行，需要 Node、pnpm 和 Web 依赖：

```sh
cd apps/web && pnpm install && pnpm exec playwright install chromium
cd ../..
node scripts/dev/capture_docs.mjs
# 也可使用本机 Chrome，仍会创建全新的临时用户目录：
DOCS_BROWSER_CHANNEL=chrome node scripts/dev/capture_docs.mjs
```

脚本在 `127.0.0.1:4179` 启动独立 Vite 服务；可用 `DOCS_SCREENSHOT_PORT` 换端口。它创建全新浏览器上下文，只提供声明过的 fixture API 响应，拦截 Steward WebSocket，阻止应用访问外部网络，并拒绝未知 API 路由和写请求。它不打开个人 home，不读取知识库数据，不联系真实后端、agent 或模型；截图后也没有通过修图隐藏隐私。

脚本检查应用错误，并把视口和文件清单写入 `screenshots.json`。发布前逐张检查生成图片。原先展示已退役 Graph 导航的旧截图已被替换。

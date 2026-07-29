# Pneuma Knowledge Compiler · E2E 验收报告

验收时间：2026-07-29 19:43 CST

浏览器：Google Chrome

视口：1440 × 900

数据：84 天全合成 OPC 租户

## 结论

**通过。** 本轮针对数据与 History 改版涉及的 Sources、四类 source reader 和
History 完成真实浏览器复验：

- 32 条页面断言全部通过；
- 14 张 light/dark 截图全部刷新；
- console error、warning、pageerror 均为 0；
- 14 个页面级横向溢出检查全部通过；
- 前端 34 个测试通过，生产构建通过；
- Python 全套 620 个测试通过；
- 开源卫生 8 个测试通过；
- 28/28 语料组 acceptance 当前，全局 QA 为 `global_pass`、0 findings。

结构化运行日志见
[e2e-run-log.json](e2e/screenshots/e2e-run-log.json)。

## 真实数据覆盖

Sources 逐页查找真实分页数据，不依赖固定 source ID，并实际打开四类 reader：

| Source 类型 | 本轮选中的真实标题 | 截图 |
| --- | --- | --- |
| 会议 | 阶段复盘后的条件核对 | [light](e2e/screenshots/01-sources-v2-meeting-light.png) / [dark](e2e/screenshots/01-sources-v2-meeting-dark.png) |
| 文档库 | 未解项交接卡 | [light](e2e/screenshots/01-sources-v2-document-library-light.png) / [dark](e2e/screenshots/01-sources-v2-document-library-dark.png) |
| 即时消息 | 午后复盘卡片 | [light](e2e/screenshots/01-sources-v2-im-light.png) / [dark](e2e/screenshots/01-sources-v2-im-dark.png) |
| 电子邮件 | 今晚不看归档 | [light](e2e/screenshots/01-sources-v2-email-light.png) / [dark](e2e/screenshots/01-sources-v2-email-dark.png) |

来源热力图有 74 个活跃业务日：
[light](e2e/screenshots/01-sources-v2-heatmap-light.png) /
[dark](e2e/screenshots/01-sources-v2-heatmap-dark.png)。

History 只展示 185 个知识版本，不混入 job 或 snapshot。它们来自同一天的真实
批量编译，因此「版本编译密度」如实显示 1 个活跃日；该时间是系统编译时间，
不是 84 天语料的业务发生时间：
[heatmap light](e2e/screenshots/10-history-v2-heatmap-light.png) /
[heatmap dark](e2e/screenshots/10-history-v2-heatmap-dark.png) /
[timeline light](e2e/screenshots/10-history-v2-light.png) /
[timeline dark](e2e/screenshots/10-history-v2-dark.png)。

最终索引状态为：

- canonical documents：28；
- canonical / Postgres / Meilisearch / Qdrant claims：均为 1,262；
- 结构化引用覆盖：1,262 / 1,262；
- citation marker 残留：0。

## 复现

```bash
cd apps/web
E2E_BASE=http://127.0.0.1:5199 \
E2E_USER=u-opc-seamlog-v2-20260729T091206681661Z-3b4f957a6d98063e \
E2E_SCOPE=sources-v2 \
node e2e/screenshots.mjs
```

`sources-v2` 只运行 journey 01 和 10，可在命令末尾追加 `01` 或 `10` 单独
复验。任一缺失的 source family、空 reader、空热力图、页面横向溢出或浏览器
错误都会使脚本以非零状态退出。

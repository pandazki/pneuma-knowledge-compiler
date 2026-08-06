# RUN-LOG — LoCoMo-Refined 全量终局实验（严格·演进模式）

所有时间为 UTC。工作目录 `/data/qiwei/lcr-final/`（任务书原文写作 `~/lcr-final/`，本机 `$HOME=/data/qiwei`，故为同一位置）。

---

## 阶段 A：准备

| 时间 | 事件 |
|---|---|
| 08:53 | 框架检出。`pneuma-knowledge-compiler` 已在本机（`/data/qiwei/repos/pneuma-knowledge-compiler`），按用户指示不重新克隆；`git fetch origin` 后以 `git worktree add /data/qiwei/lcr-final/repo c132a270c985904528b87870f50bc8ef37757f58` 得到指定 commit 的独立工作树。`uv sync --all-packages` 完成。 |
| 08:53 | `git clone --depth 1 https://github.com/mem-eval-suite/LoCoMo_refined /data/qiwei/lcr-final/data`。仅读 `data/public/manifest.json`（10 conversations / 1382 questions / category 1-4）与 `conversations.jsonl` 的**结构字段**。`questions.jsonl`、`src/`、`scripts/`、`README.md` 一律未碰。 |
| 08:55 | 读 `REPO/scaffold/AGENT-GUIDE.zh-CN.md` 与 `REPO/docs/guides/compile-contract.zh-CN.md`。 |
| 08:56 | 写 `answers/app-01.toml`（`language="zh"`、`data.mode="none"`、`contract.mode="skeleton"`、`project_name="lcr-01"`，其余默认），生成 `app-01`。 |
| 08:56 | 写 `apply_env.py`：从本机凭据文件并入 `OPENROUTER_API_KEY` 与三项 `LANGFUSE_*`。凭据值全程不打印、不回显，仅以 `grep -c` 验证非空。任务书假定该脚本已备好；本机需自建，功能与约束一致。 |
| 08:58 | 写 `lf.py`（Langfuse 探针与成本聚合，凭据同样只加载不回显）。 |
| 08:59 | `app-01` 起栈 → `./app.py init` → 一次最小真实调用 `./app.py ask`（1231 tokens）。 |
| 08:59 | **Langfuse 留痕验证通过**：`lf.py probe app-01` 经 Langfuse API 查到该次调用的 trace（`name=recall.fast op=recall.fast user=u-app-owner`）。 |
| 09:02 | 生成 `app-02` … `app-10`（同一 answers 模板，仅 `project_name` 递增），逐个 `apply_env.py` 并入凭据，四项均验证非空。 |
| 09:03 | 每个 `.env` 追加 `PNEUMA_KNOWLEDGE_CHALLENGE_ENABLED=true` 与 `PNEUMA_KNOWLEDGE_CHALLENGE_MAX_ROUNDS=1`（用户裁定：质询 1 轮）。租户 `user_id` 一律用生成器默认值 `u-app-owner`，隔离由项目边界承担。 |
| 09:04 | 十个栈全部 `./app.py up` + `./app.py init`（30 个容器）。系统检测值 `Etc/UTC` / `en-US` / `US`——与英文语料一致，实验者确认，三项 `provenance` 改为 `profile`，`preferences.response_language` 显式写 `en-US`（题面与判官均为英文）。 |
| 09:05 | **预览十个 conversation 的第一个 session 全文 + 结构字段**（session 数、speaker 名、日期跨度、多模态计数）。此为协议允许的唯一会话原文阅读；此后本人不再读任何会话原文。 |
| 09:06 | 写十份契约（`write-contracts.py` 落地，内容由本人撰写）。共用骨架 + 每份对自己 conversation 主体族负责，全部 TODO 写掉，`skill_id: lcr-NN-knowledge`、`version: lcr-NN-v1`。契约与 profile 一并提交进各自的 `engine/` 仓库。 |
| 09:08 | 写 `to_material.py`（session → scaffold 对话材料）。渲染口径与数据集自身的多模态渲染一致（`Speaker: text` + 缩进的 `[images]`/`[caption]`/`[query]`）；核验环节从项目 `app.py` 中**逐字提取**框架真实的 `parse_conversation_turns` 与 `split_frontmatter`，逐条比对 (speaker, text)。 |
| 09:10 | 对全部 272 个 session 做往返核验演练：**272/272 通过，0 失败**。 |
| 09:11 | 单 session 标定跑（app-01 / session 1）：4 个 job（index → compile +9 claims → challenge → 补偿编译 +2 claims），48.1s，6 篇正本、11 条 claims、59,509 tokens。据此标定演进阈值。 |
| 09:12 | app-01 重置回白纸（`./app.py down --volumes` + `rm -rf data/ material/` + 重新 `up`/`init`），`sources=0 claims=0`。 |
| 09:13 | 写 `01-build.sh`。 |

（下续：01-build.sh 试跑验证 → 冻结 → 考纲阶段 → 02/03 → 阶段 B → 阶段 C）

| 09:14–09:25 | **01-build.sh 试跑验证**（app-01，前 6 个 session）。验证内容：并行入口、断点标记、progress/evolve 状态表、往返核验、compile 队列归零判定、演进阈值计算。09:24:30 首次演进按阈值触发（`session=5 new_claims=67 sessions_since=5 force=0`），框架跑了一次 evolve.propose（3,509 tokens）后返回 `no_change`——机制活的，此刻结构无需重组。 |
| 09:26 | 试跑终止并**彻底重置**：app-01 `down --volumes` + 删 `data/`、`material/`、`state/`、`logs/`。 |
| 09:26:56 | **第一次冻结**：十份契约 + `01-build.sh` + `to_material.py` + 三个辅助件，SHA-256 见 `FROZEN.md`。 |
| 09:27–09:34 | **考纲阶段**（冻结之后才开始）：通读官方 `README.md`、`src/llm_judge.py`、`src/evaluate.py`、`src/llm_judge_runtime.py`、`scripts/run_eval.sh`、`scripts/env.sh` 与提交模板。记入烧题清单两题（`conv-26#q0000`、`conv-26#q0001`，README 的预测格式示例直接给出了答案值）。验证 OpenRouter 上 `qwen/qwen3-14b` 可用且被官方脚本的 Qwen 校验接受，`enable_thinking=False` 被端点接受。 |
| 09:31 | 发现试跑的编译进程有残留、在重置后又写入了 app-01（sources=3 claims=29）。按 PID 精确终止，二次重置，十个库逐一核验 `sources=0 claims=0`。全程披露。 |
| 09:35:20 | **第二次冻结**：`02-answer.sh` + `answer_runner.py` + `03-score.sh`，含烧题清单。 |

---

## 阶段 B：执行（零人工干预）

| 时间 | 事件 |
|---|---|
| 09:35:54 | `01-build.sh` 起跑，pool=5，演进策略 `claims>=50 且 sessions>=4`。 |
| 09:36–12:02 | 十个 conversation 逐 session 构建。每 session：转换（往返核验）→ ingest → compile 至队列归零 →（命中阈值则）`evolve step --policy adopt-clean`。演进触发 68 轮，全部返回 `no draft produced`。质询触发 272 次，其中 252 次产出补偿编译。gate 拒绝 0 次。 |
| 12:02:24 | `01-build.sh` 结束，rc=0，10/10 对话完成。272/272 session，3,584 claims，423 篇正本。逐项目核验 `session.done` 数 = `sources` 数 = 真实 session 数，队列全部归零。 |
| 12:05:24 | `02-answer.sh` 起跑，pool=5，`--style concise`。执行前核验五个脚本哈希与冻结记录一致。 |
| 12:05–13:36 | 1,382 题按 `conversation_idx` 路由到各自项目作答。稳定期速率 17–20 题/分钟。 |
| 13:36:26 | `02-answer.sh` 结束，rc=0，1,382 条，逐路题数齐全，GIVE-UP 0。 |
| 13:36:38 | `03-score.sh` 起跑。预测装配核验：1,382 行、qa_id 与官方题库一一对齐、零空答案。 |
| 13:36–13:50 | 官方 scorer 原样运行：`--metrics llm f1 bleu --llm-judge refined --concurrency 64`，判官 `qwen/qwen3-14b`（OpenRouter，官方接受的别名）。中途一次 JSON 解析重试，由 scorer 自带的 tenacity 自愈。 |
| 13:50:09 | `03-score.sh` 结束，rc=0，1,382 条判分落地。**分数落地，防火墙解除。** |

**阶段 B 干预记录：零。** 三个脚本各自一次跑完，无崩溃、无修复、无重冻结、无手改。

---

## 阶段 C：分析与文书

| 时间 | 事件 |
|---|---|
| 13:50 起 | 读取判分结果，聚合双分数、分 conversation / 分 category / 分模态得分表、失分模式、族分布、演进与质询统计。 |
| 13:51 起 | 经 Langfuse API 聚合分环节 token 与金额（v1 `observations`，15 次/分限速下节流分页，共 10,773 条 observation）。 |
| — | 产出 `RUN-REPORT.md` 与本文件。 |

### 阶段 C 记录的一处观察偏差

执行期我用作旁观的监控通道（Monitor / 后台定时任务）两次给出与文件系统不符的信息：一次事件时间戳超前真实时钟约半小时，一次误报「答题完成 1382/1382」（实际 1031）。我据此向用户做过错误汇报，随后以文件系统核验更正。该通道从未参与实验本身——它不改脚本、不碰库、不影响任何模型调用——发现后即停用，改为直接读 `progress.csv` 与状态文件。报告中的所有数字均以文件系统与官方判分产物为准。

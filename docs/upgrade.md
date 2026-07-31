# 升级演练：策略升级不重建知识库（需求 6）

> 本文是需求 6 的成文承诺 + 机制台账。对应里程碑 M5、架构不变式 I2（canonical vs derived）。
> 一句话命题：**skill / 渲染 / 检索 / 投影策略升级时，git-canonical 权威层零改写，只有 derived（投影 / 索引）全量重建。**

## 1. 分类台账：什么可重建，什么不可

| 层 | 归属 | 性质 | 升级如何处理 |
|---|---|---|---|
| canonical 文档（claims + 锚） | per-user git repo | **不可重建**（唯一权威） | 永不因策略升级被改写；只随新 compile 前向追加 |
| 原始 content + 结构地图 | PG（append-only）+ payload | **不可重建**（权威输入） | 永不改写 |
| 词法索引（L1 claims / blocks） | Meilisearch（index per user） | derived，可重建 | 全量重建 |
| 语义索引（L2 chunk / L3 claim 层） | Qdrant（tenant filter） | derived，可重建 | 全量重建 |
| 投影 / 注记（canonical_claims） | PG | derived，可重建 | 全量重建 |

判据只有一条：**能否从 canonical + 原始 content 无损重算？** 能 → derived，随便重建；不能 → canonical，永不静默改写。

## 2. 三类升级各自的路径

### 路径 A —— 纯 derived 升级（渲染 / 检索 / 投影策略变，最常见）

渲染策略、检索融合、投影呈现变了，但 canonical 文档不变。

- **做法**：换新版投影 / 渲染逻辑（`ProjectionStrategy`）+ `rebuild_projection(user, strategy=…)`。
- **机制**：`rebuild_projection` 只 **读** canonical git HEAD，把每一条 claim 按新策略重新物化到 PG + Meili + Qdrant；不发生任何 commit。
- **验收**：canonical git HEAD sha 升级前后 **逐字节相同**；投影行内容按新策略变化；recall / briefing 立即用上新投影。
- **例（本仓库已实现）**：`ProjectionStrategy(fold_section_context=True)` 让投影把小节面包屑折进可检索的 claim 文本（`程野 是后端负责人` → `[CHENG-YE] 程野 是后端负责人`），使 claim 脱离文档后仍自洽可检索。canonical body 一个字节没动。

这是"升级不重建知识库"的**主证据**。

### 路径 B —— 新 compile 用新 skill（skill 建模策略变，前向增量）

skill 对"什么该记、怎么建模"的判断演进了（如 v1→v2）。

- **做法**：v2 上线后，**新来的 source 用 v2 编译**；旧 canonical 保持不动（forward-only，不追溯改写）。
- **机制**：`run_compile` 用传入的 `SkillVersion` 编译，并把 `Skill-Version` 写进 commit message trailer（git 白拿的审计）。老 commit 保留它当初的版本，新 commit 记新版本，同一 repo 两版本共存。
- **验收**：v2 compile 产生的新 commit trailer = `Skill-Version: v2`，旧 commit 仍是 `v1`；gate `anchor_continuity` 未破（v2 的新文档 / 新 claim 不删旧锚）。
- **锚连续性**：v2 只新增文档 / claim，旧锚原样留在 HEAD。gate 的 citation 校验只判 **本轮新引入** 的 citation，旧文档里指向"本轮未供给的老 source"的 citation 被 grandfather（它在自己那次 commit 时已校验过），因此前向 compile 不会被误拒。

### 路径 C —— 检索 / 投影参数微调（路径 A 的子集）

RRF 参数、cap、去重键、claim 层与 chunk 层的隔离策略等纯 derived 旋钮，一律走路径 A：改逻辑 + 重建，不碰 canonical。

## 3. 什么升级会 / 不会触发 canonical 重建

- **不触发（只重建 derived）**：渲染策略、投影策略、检索融合、索引 schema、embedding 模型换代、注记密度、cap / 去重。全部路径 A。
- **前向新增（不改旧 canonical）**：skill 建模策略演进 → 路径 B，只影响未来 compile。
- **需要一次显式 re-compile（超出 M5 范围）**：若某升级确需改 canonical 的**布局**本身（如把 `memory/people/{slug}.md` 改成另一套 path_template、或改锚格式），这不是静默迁移能做的——它会改写既有 canonical，违反 I2。此类升级记为"需要一次显式的、留痕的 re-compile / 迁移决策"，由项目主人拍板，**不做 Pneuma Compiler 风格的 migration patch**（那正是被本项目否决的反模式）。

## 4. 铁律

1. **永不静默改写 canonical。** 任何"升级"实现改写了既有 canonical git 内容即为失败——这正是本里程碑要证明的性质。derived 可以随时推倒重建；canonical 只能前向追加。
2. **skill 版本 immutable。** `SkillVersion` frozen，每个版本有独立且稳定的 `content_hash`（含 instructions + path_templates + contract_rules）。`render_system_contract(skill)` 对同一版本逐字节稳定（I5），不含时间戳。
3. **审计靠 git 白拿。** 用哪个 skill 版本编译了哪个快照，写在 canonical commit 的 `Skill-Version` trailer 里，`commit_trailer(user, ref, "Skill-Version")` 直接读回，无需另存 sidecar。
4. **path ownership 跨版本稳定。** v1 / v2 共用同一套 path_templates，skill 建模演进不得搬动文件布局而孤立旧锚。

## 5. 机制落点（代码索引）

- `pneuma_knowledge_core/skill/version.py` —— `SkillVersion`（immutable）+ `load_builtin_skill(version="v1"|"v2")`；`_CONTRACT_RULES` 按版本注入附加契约规则。
- `pneuma_knowledge_core/skill/contract.py` —— `render_system_contract`：写机制 + 本版本 contract_rules + skill instructions，逐字节稳定。
- `pneuma_knowledge_core/skill/assets/personal_knowledge_v{1,2}.md` —— 两个通用默认版本。
- `pneuma_knowledge_core/recall/projection.py` —— `ProjectionStrategy` / `PROJECTION_V1` / `PROJECTION_V2`；`project_snapshot_claims(docs, strategy)`。
- `pneuma_knowledge_service/projection.py` —— `rebuild_projection(ctx, user, snapshot_ref=None, *, strategy=…)`：derived 全量重建入口。
- `pneuma_knowledge_core/compile/runner.py` —— `_with_skill_trailer`：把 `Skill-Version` 盖进 commit trailer。
- `pneuma_knowledge_service/adapters/git_canonical.py` —— `commit_trailer`：用 git 自带 trailer 解析读回。
- `examples/walkthroughs/upgrade_e2e.py` —— 路径 A + 路径 B 串起来的可运行证据。

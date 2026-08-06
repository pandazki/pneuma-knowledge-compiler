"""The hand-authored engine stage map — the one place the lifecycle picture is drawn.

The engine directory (docs/design/engine-console.md) is a versioned unit holding everything
that IS this deployment's engine: strategy files, the compile contract, prompt overlays,
the owner profile. This module declares which stage each of those files belongs to, which
`Settings` field each key resolves into, and what the blast radius of changing it is.

Two things are deliberately NOT here:

* the knob defaults — they are read from `Settings` field metadata by `schema.py`, so a
  default can never drift between the framework and the picture the console draws;
* the arrows' truth — `EDGES` states which edges exist and which knob gates each one, but
  whether an edge is live is computed from resolved values, never asserted here.

`NON_ENGINE_SETTINGS` is the other half of the mechanism: every `Settings` field is either
mapped to a knob below or listed there with a reason. A new setting that is neither fails
`test_engine_schema.py` — which is how a strategy knob cannot be added without the console
(and the docs it feeds) learning about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Knob:
    """One editable key inside one engine file.

    `setting` is the `Settings` field this key resolves into ("" for the two knob kinds
    that are not settings: a document, and the prompt overlay map). `env` is the process
    environment variable that outranks the engine file ("" when there is none) — the
    precedence chain lives in `resolve.py`, this is only its declaration.
    """

    key: str
    type: str  # enum | bool | int | string | document | overlay_map
    apply: str  # hot | restart | future_compiles | derived_rebuild
    label_en: str
    label_zh: str
    description_en: str
    description_zh: str
    env: str = ""
    setting: str = ""
    enum: tuple[str, ...] = ()
    # "the allowed values are not a literal list, they come from somewhere in the code".
    # Only "prompt_catalog" exists: the overlay knob's allowed KEYS are the framework's
    # prompt-catalog keys, and hand-copying 300-odd of them into this file would be the
    # exact rot Ruling 3 forbids.
    enum_source: str = ""
    # Only for knobs with no `setting` to read a default from (document / overlay_map).
    literal_default: object = ""


@dataclass(frozen=True)
class Stage:
    """One lifecycle stage: a title, a doc deep link, one engine file, its knobs."""

    id: str
    title_en: str
    title_zh: str
    summary_en: str
    summary_zh: str
    doc: str  # repo-relative, optionally with a heading anchor
    file: str  # engine-relative
    knobs: tuple[Knob, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Edge:
    """A pipeline arrow. `condition` is a `<stage>.<key>` bool knob gating it ("" = always)."""

    source: str
    target: str
    label_en: str
    label_zh: str
    condition: str = ""


@dataclass(frozen=True)
class AccessRoute:
    """One of the four levels the same material is reachable at, drawn as a route.

    `EDGES` says what the pipeline DOES to material, stage by stage. It cannot say how the
    material is later reached, and a map that only shows `intake → compile → recall` teaches a
    newcomer that everything is answered out of the compile step — the single most consequential
    thing the console can get wrong about this architecture (architecture.md §3: four parallel
    views, not a degradation chain).

    `condition` is what gates the route, and the two kinds are spelled apart on purpose: a
    `<stage>.<key>` bool knob is a deployment switch, `intake_plan.<field>` is a PER-SOURCE
    decision the intake plan makes and no engine setting overrides. `""` is the honest value for
    L0 and L1 — invariant I3 makes them unconditional, and a console that drew them as toggleable
    would be offering to break the invariant.
    """

    id: str
    source: str
    target: str
    title_en: str
    title_zh: str
    summary_en: str
    summary_zh: str
    condition: str = ""


# The four apply semantics, in the order the console badges them. This tuple is the
# vocabulary: an `apply` value outside it fails the schema test.
APPLY_SEMANTICS = ("hot", "restart", "future_compiles", "derived_rebuild")

KNOB_TYPES = ("enum", "bool", "int", "string", "document", "overlay_map")


STAGES: tuple[Stage, ...] = (
    Stage(
        id="intake",
        title_en="Intake",
        title_zh="接收",
        summary_en=(
            "Material arrives verbatim (L0) and is cut into semantic units for the vector "
            "index (L2). Only the cutting is a choice — the text stays a verbatim slice."
        ),
        summary_zh=(
            "材料逐字入库（L0），并被切成语义单元供向量索引（L2）使用。可选的只有怎么切——"
            "切出来的文本始终是原文的逐字片段。"
        ),
        doc="docs/reference/configuration.md#l2-chunking",
        file="intake/intake.yaml",
        knobs=(
            Knob(
                key="chunk_strategy",
                type="enum",
                enum=("semantic", "sentence", "recursive"),
                apply="derived_rebuild",
                env="PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",
                setting="chunk_strategy",
                label_en="Chunk strategy",
                label_zh="切块策略",
                description_en=(
                    "semantic = the compile-role model detects topic/episode boundaries and "
                    "returns block indexes only; sentence / recursive = mechanical chonkie "
                    "chunkers with no model cost. Existing content keeps its recorded "
                    "boundaries until rebuild_derived runs."
                ),
                description_zh=(
                    "semantic = 由编译角色模型判断话题/情节边界，只返回块下标；"
                    "sentence / recursive = 机械切分，不花模型钱。已有内容会保留既有边界，"
                    "直到跑 rebuild_derived 才真正改变。"
                ),
            ),
        ),
    ),
    Stage(
        id="compile",
        title_en="Compile",
        title_zh="编译",
        summary_en=(
            "The model reads the material and writes canonical documents under this "
            "engine's contract. Every write passes the citation gate."
        ),
        summary_zh=(
            "模型在本引擎的契约之下阅读材料、写出正本文档。每一次写入都要过引用闸门。"
        ),
        doc="docs/guides/compile-contract.md",
        file="compile/contract.md",
        knobs=(
            Knob(
                key="contract",
                type="document",
                apply="future_compiles",
                label_en="Compile contract",
                label_zh="编译契约",
                description_en=(
                    "The constitution: what deserves long-term memory in this domain, and on "
                    "which page. A judgement document — never decomposed into toggles. "
                    "Rewriting it governs future compiles only; canonical is never rewritten."
                ),
                description_zh=(
                    "宪法：在这个领域里什么值得被长期记住、该记在哪一页。它是判断力文档——"
                    "永远不会被拆成开关。改写它只管未来的编译；正本永不被回溯重写。"
                ),
            ),
        ),
    ),
    Stage(
        id="challenge",
        title_en="Coverage challenge",
        title_zh="覆盖质询",
        summary_en=(
            "After a committed compile, blind questions are generated over the same "
            "material and the canon is probed for gaps; confirmed gaps can trigger one "
            "compensation compile."
        ),
        summary_zh=(
            "编译提交后，对同一份材料盲出问题、拿着问题查正本的缺口；确认的缺口可以触发"
            "一次补偿编译。"
        ),
        doc="docs/reference/configuration.md#post-compile-coverage-challenge",
        file="compile/challenge.yaml",
        knobs=(
            Knob(
                key="enabled",
                type="bool",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_CHALLENGE_ENABLED",
                setting="challenge_enabled",
                label_en="Audit after every compile",
                label_zh="每次编译后审计",
                description_en=(
                    "Off by default: the audit spends extra model calls per compile job. On, "
                    "it mechanizes the contract guide's \"ask real questions\" acceptance step."
                ),
                description_zh=(
                    "默认关：审计会为每个编译作业额外花模型调用。开启后，它把契约指南里"
                    "「拿真问题去问」这一步验收机械化。"
                ),
            ),
            Knob(
                key="max_rounds",
                type="int",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_CHALLENGE_MAX_ROUNDS",
                setting="challenge_max_rounds",
                label_en="Max rounds",
                label_zh="最多轮数",
                description_en=(
                    "Question/reflection rounds per audit. Either stage may end early by "
                    "declaring itself exhausted."
                ),
                description_zh="每次审计的出题/反思轮数。任一阶段都可以自称穷尽而提前结束。",
            ),
            Knob(
                key="max_questions",
                type="int",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_CHALLENGE_MAX_QUESTIONS",
                setting="challenge_max_questions",
                label_en="Questions per round",
                label_zh="每轮问题数",
                description_en="How many blind questions one round generates.",
                description_zh="一轮盲出多少个问题。",
            ),
            Knob(
                key="max_output_tokens",
                type="int",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_CHALLENGE_MAX_OUTPUT_TOKENS",
                setting="challenge_max_output_tokens",
                label_en="Output budget (tokens)",
                label_zh="输出预算（token）",
                description_en=(
                    "Completion cap for the audit's structured passes. A healthy reply is "
                    "small; without a cap a runaway generation runs to the provider ceiling "
                    "before failing to parse. 0 = provider default."
                ),
                description_zh=(
                    "审计结构化调用的完成上限。健康回复很小；不设上限时一次失控生成会"
                    "跑满供应商上限才解析失败。0 = 供应商默认。"
                ),
            ),
            Knob(
                key="compensate",
                type="bool",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_CHALLENGE_COMPENSATE",
                setting="challenge_compensate",
                label_en="Compensation compile",
                label_zh="补偿编译",
                description_en=(
                    "Confirmed gaps enqueue one extra compile over the same material; its "
                    "writes pass the ordinary citation gate like any other."
                ),
                description_zh=(
                    "确认的缺口会为同一份材料再排一次编译；它的写入和其他写入一样要过"
                    "普通的引用闸门。"
                ),
            ),
        ),
    ),
    Stage(
        id="evolve",
        title_en="Schema evolve",
        title_zh="模式演进",
        summary_en=(
            "Once enough new material has accrued, a strong model proposes reorganizing the "
            "library's structure on a branch and waits for a human to adopt or drop it."
        ),
        summary_zh=(
            "积累够多新材料后，强模型会在分支上提出重组知识库结构的方案，等人来采纳或丢弃。"
        ),
        doc="docs/guides/evolution.md",
        file="evolve/evolve.yaml",
        knobs=(
            Knob(
                key="auto_trigger",
                type="bool",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_EVOLVE_AUTO_TRIGGER",
                setting="evolve_auto_trigger",
                label_en="Passive trigger",
                label_zh="被动触发",
                description_en=(
                    "Whether compiles may fire an evolve round. Off leaves evolution entirely "
                    "manual; nothing is ever reorganized without a review either way."
                ),
                description_zh=(
                    "编译是否可以触发演进。关掉后演进全靠手动；无论开关如何，"
                    "没有评审就不会有任何重组落地。"
                ),
            ),
            Knob(
                key="trigger_topic_docs",
                type="int",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_EVOLVE_TRIGGER_TOPIC_DOCS",
                setting="evolve_trigger_topic_docs",
                label_en="New documents threshold",
                label_zh="新文档阈值",
                description_en=(
                    "New canonical documents since the last evolve needed to fire (AND-ed with "
                    "the claim threshold). Lower it for a slow-trickle library."
                ),
                description_zh=(
                    "距上次演进新增多少正本文档才触发（与断言阈值取与）。"
                    "材料细水长流的库可以调低。"
                ),
            ),
            Knob(
                key="trigger_new_claims",
                type="int",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_EVOLVE_TRIGGER_NEW_CLAIMS",
                setting="evolve_trigger_new_claims",
                label_en="New claims threshold",
                label_zh="新断言阈值",
                description_en="New anchors since the last evolve needed to fire.",
                description_zh="距上次演进新增多少锚点才触发。",
            ),
            Knob(
                key="draft_ttl_hours",
                type="int",
                apply="future_compiles",
                env="PNEUMA_KNOWLEDGE_EVOLVE_DRAFT_TTL_HOURS",
                setting="evolve_draft_ttl_hours",
                label_en="Draft lifetime (hours)",
                label_zh="草案存活时长（小时）",
                description_en=(
                    "A draft older than this is lazily expired the next time the list is read. "
                    "The setting accepts fractions; the console steps in whole hours."
                ),
                description_zh=(
                    "超过这个时长的草案会在下次读列表时被惰性过期。设置本身接受小数，"
                    "控制台按整小时步进。"
                ),
            ),
        ),
    ),
    Stage(
        id="recall",
        title_en="Recall",
        title_zh="召回",
        summary_en=(
            "The answering lanes: retrieval over claims and source windows, then an answer "
            "whose every conclusion carries a citation."
        ),
        summary_zh=(
            "回答车道：在断言与源窗口上检索，然后给出每条结论都带引用的回答。"
        ),
        doc="docs/architecture.md#7-retrieval",
        file="recall/recall.yaml",
        knobs=(
            Knob(
                key="answer_style",
                type="enum",
                enum=("concise", "conversational", "detailed"),
                apply="hot",
                env="PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE",
                setting="recall_answer_style",
                label_en="Answer style",
                label_zh="回答风格",
                description_en=(
                    "Shape only: concise = the bare exact value a grader or script expects; "
                    "conversational = a natural chat reply; detailed = a self-contained note. "
                    "Truth discipline is style-independent."
                ),
                description_zh=(
                    "只影响形状：concise = 评分器或脚本要的那个确切值；conversational = "
                    "自然的对话回复；detailed = 自成一体的书面笔记。真话纪律与风格无关。"
                ),
            ),
            Knob(
                key="claim_cap",
                type="int",
                apply="hot",
                env="PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP",
                setting="recall_claim_cap",
                label_en="Claim budget",
                label_zh="断言预算",
                description_en=(
                    "How many claims one fast ask may pull into the prompt. The default sits "
                    "inside the measured 40–80 sweet band."
                ),
                description_zh=(
                    "一次快速问答最多把多少断言放进提示词。默认值落在实测的 40–80 甜区内。"
                ),
            ),
            Knob(
                key="window_cap",
                type="int",
                apply="hot",
                env="PNEUMA_KNOWLEDGE_RECALL_WINDOW_CAP",
                setting="recall_window_cap",
                label_en="Source window budget",
                label_zh="源窗口预算",
                description_en="How many raw source windows one fast ask may pull in.",
                description_zh="一次快速问答最多把多少原始源窗口放进来。",
            ),
            Knob(
                key="plan_queries",
                type="int",
                apply="hot",
                env="PNEUMA_KNOWLEDGE_RECALL_PLAN_QUERIES",
                setting="recall_plan_queries",
                label_en="Planned extra queries",
                label_zh="规划的额外查询数",
                description_en=(
                    "0 = the single-query lane, byte-for-byte. N > 0: one small call derives up "
                    "to N extra retrieval queries, all pooled through one RRF fusion."
                ),
                description_zh=(
                    "0 = 单查询车道，逐字节不变。N > 0：一次小调用推导出最多 N 个额外检索"
                    "查询，全部经一次 RRF 融合汇总。"
                ),
            ),
            Knob(
                key="rerank_model",
                type="string",
                apply="hot",
                env="PNEUMA_KNOWLEDGE_RECALL_RERANK_MODEL",
                setting="recall_rerank_model",
                label_en="Claim reranker",
                label_zh="断言重排模型",
                description_en=(
                    "Empty = off (measured: no gain on claim-level retrieval). \"llm\" = LLM "
                    "reranker on the recall model; \"llm:<spec>\" picks the model; a bare model "
                    "name uses the OpenRouter /rerank endpoint."
                ),
                description_zh=(
                    "空 = 关（实测：断言级检索上没有增益）。\"llm\" = 用召回模型做 LLM 重排；"
                    "\"llm:<spec>\" 指定模型；裸模型名走 OpenRouter /rerank 端点。"
                ),
            ),
            Knob(
                key="rerank_candidates",
                type="int",
                apply="hot",
                env="PNEUMA_KNOWLEDGE_RECALL_RERANK_CANDIDATES",
                setting="recall_rerank_candidates",
                label_en="Rerank candidate depth",
                label_zh="重排候选深度",
                description_en=(
                    "Retrieval depth per query per face when reranking; the reranker then scores "
                    "the full deduped union."
                ),
                description_zh=(
                    "开启重排时每个查询、每个面的检索深度；重排器随后对整个去重并集打分。"
                ),
            ),
        ),
    ),
    Stage(
        id="models",
        title_en="Models",
        title_zh="模型",
        summary_en=(
            "The engine's four model roles. The compile model is the one real quality lever "
            "— a stronger model directly produces a better library."
        ),
        summary_zh=(
            "引擎的四个模型角色。编译模型是唯一真正的质量杠杆——更强的模型直接产出更好的库。"
        ),
        doc="docs/reference/configuration.md#models",
        file="engine.yaml",
        knobs=(
            Knob(
                key="compile",
                type="string",
                apply="restart",
                env="PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE",
                setting="llm_model_compile",
                label_en="Compile model",
                label_zh="编译模型",
                description_en=(
                    "Must support tool calling: the compile agent writes through tools. The "
                    "quality lever of the whole engine."
                ),
                description_zh=(
                    "必须支持工具调用：编译代理是通过工具写入的。整个引擎的质量杠杆。"
                ),
            ),
            Knob(
                key="recall",
                type="string",
                apply="restart",
                env="PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL",
                setting="llm_model_recall",
                label_en="Recall model",
                label_zh="召回模型",
                description_en="Fast recall and the briefing ask. Fast and cheap is fine.",
                description_zh="快速召回与简报问答。又快又便宜就够了。",
            ),
            Knob(
                key="deep",
                type="string",
                apply="restart",
                env="PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP",
                setting="llm_model_deep",
                label_en="Deep-recall model",
                label_zh="深度召回模型",
                description_en="The agentic search lane. Empty borrows the recall role.",
                description_zh="代理式搜索车道。留空则借用召回角色。",
            ),
            Knob(
                key="embedding",
                type="string",
                apply="restart",
                env="PNEUMA_KNOWLEDGE_EMBEDDING_MODEL",
                setting="embedding_model",
                label_en="Embedding model",
                label_zh="向量模型",
                description_en=(
                    "fake:<dim> is deterministic and keyless. A vector collection's dimension "
                    "is fixed at creation, so switching real models means a new collection."
                ),
                description_zh=(
                    "fake:<dim> 确定且无需密钥。向量集合的维度在创建时就固定了，"
                    "所以换真实模型意味着换一个新集合。"
                ),
            ),
        ),
    ),
    Stage(
        id="persona",
        title_en="Owner profile",
        title_zh="主人档案",
        summary_en=(
            "Whose viewpoint the material is written from. Compiles read it to know how to "
            "address the owner and which calendar day a timestamp falls on — facts stay in "
            "the material."
        ),
        summary_zh=(
            "材料是从谁的视角写的。编译读它来知道该怎么称呼主人、时间戳算在哪一个日历日上"
            "——事实本身仍然只住在材料里。"
        ),
        doc="docs/architecture.md#6-the-compile-contract-skill",
        file="persona/profile.yaml",
        knobs=(
            Knob(
                key="profile",
                type="document",
                apply="future_compiles",
                label_en="Profile document",
                label_zh="档案文档",
                description_en=(
                    "The owner's own file: name, occupation, locale, and the provenance of each "
                    "detected value. A detected value is never presented as the owner's own "
                    "setting until its provenance says so."
                ),
                description_zh=(
                    "主人自己的文件：称呼、职业、地区设置，以及每个探测值的来源标记。"
                    "探测出来的值在来源标记改写之前，永远不会被当成主人自己的设定。"
                ),
            ),
        ),
    ),
    Stage(
        id="prompts",
        title_en="Prompt overlays",
        title_zh="提示词覆盖",
        summary_en=(
            "The framework's extension point for model-visible wording: pick the language the "
            "framework's own clauses arrive in, and replace any catalog key's clause wholesale, "
            "without forking the framework."
        ),
        summary_zh=(
            "框架为「模型可见文案」留的扩展点：选定框架自身文案的语言，并整段替换目录里任一键的"
            "措辞，不必分叉框架。"
        ),
        doc="docs/architecture.md#11-the-engine-directory",
        file="prompts/overlays.yaml",
        knobs=(
            # Declared BEFORE the overlay map because that is the order it is applied in: the
            # language pack becomes the framework text, and an overlay is an override on top
            # of it. A console that listed them the other way round would suggest the pack
            # takes an author's clause back.
            Knob(
                key="language",
                type="enum",
                enum=("en", "zh"),
                apply="restart",
                env="PNEUMA_KNOWLEDGE_PROMPT_LANGUAGE",
                setting="prompt_language",
                label_en="Prompt language",
                label_zh="提示词语言",
                description_en=(
                    "The language of the FRAMEWORK's own clauses — the layer your overrides "
                    "sit on. en = the English catalog, the baseline every measurement in this "
                    "repository was taken on; zh = core's Chinese language pack, for "
                    "readability and Chinese material, with scoring equivalence unverified. "
                    "It does not decide what language a knowledge base is written in: that "
                    "follows the subject's own declared language."
                ),
                description_zh=(
                    "**框架自身**文案的语言——也就是你的覆盖所叠在的那一层。en = 英文目录，本仓库"
                    "所有跑分的基线；zh = 核心自带的中文语言包，面向可读性与中文材料，跑分等价性"
                    "未经验证。它不决定文库用什么语言写：那取决于知识主体自己声明的语言。"
                ),
            ),
            Knob(
                key="overlays",
                type="overlay_map",
                apply="restart",
                literal_default={},
                enum_source="prompt_catalog",
                label_en="Catalog overrides",
                label_zh="目录覆盖",
                description_en=(
                    "Catalog key → replacement clause, applied at startup via override_prompts. "
                    "Whole-clause replacement only: there is no templating seam, because a "
                    "half-replaced prompt is a prompt nobody can audit."
                ),
                description_zh=(
                    "目录键 → 替换文案，启动时经 override_prompts 生效。只支持整段替换："
                    "这里没有模板拼接的缝，因为半替换的提示词是没人审得清的提示词。"
                ),
            ),
        ),
    ),
)


EDGES: tuple[Edge, ...] = (
    Edge(
        source="intake",
        target="compile",
        label_en="verbatim blocks",
        label_zh="逐字块",
    ),
    Edge(
        source="compile",
        target="challenge",
        condition="challenge.enabled",
        label_en="audit the committed compile",
        label_zh="审计已提交的编译",
    ),
    Edge(
        source="challenge",
        target="compile",
        condition="challenge.compensate",
        label_en="compensation compile",
        label_zh="补偿编译",
    ),
    Edge(
        source="compile",
        target="evolve",
        condition="evolve.auto_trigger",
        label_en="enough new material accrued",
        label_zh="新材料积累够了",
    ),
    Edge(
        source="compile",
        target="recall",
        label_en="canonical claims answer questions",
        label_zh="正本断言回答问题",
    ),
)


# The four levels the same material stays reachable at, and where each of them is answered
# from. Hand-authored next to EDGES and under the same discipline: the schema is regenerated
# and pinned, so a level that changed its gate cannot keep the old picture.
ACCESS_ROUTES: tuple[AccessRoute, ...] = (
    AccessRoute(
        id="l0",
        source="intake",
        target="recall",
        title_en="L0 · verbatim",
        title_zh="L0 · 逐字原文",
        summary_en=(
            "The original text with block addressing, stored once and never rewritten. Every "
            "citation anywhere in the system ends here, so recall can always fetch the exact "
            "blocks a claim points at. Authoritative; nothing regenerates it."
        ),
        summary_zh=(
            "带块寻址的原文，只存一次，永不改写。系统里任何一处引用最终都落到这里，"
            "所以召回随时能取回某条断言指向的那几块原文。它是权威层；没有任何东西能重建它。"
        ),
    ),
    AccessRoute(
        id="l1",
        source="intake",
        target="recall",
        title_en="L1 · full-text",
        title_zh="L1 · 全文检索",
        summary_en=(
            "A lexical index over every source, built for all of them without exception "
            "(invariant I3) — which is what lets compile leave a detail in the original: one "
            "word still pulls it back. Derived, and rebuildable from L0 at any time."
        ),
        summary_zh=(
            "覆盖每一份来源的词法索引，无一例外地都建（不变量 I3）——"
            "正是它让编译可以把细节留在原文里：一个词就能把它调回来。派生层，随时可从 L0 重建。"
        ),
    ),
    AccessRoute(
        id="l2",
        source="intake",
        target="recall",
        title_en="L2 · semantic",
        title_zh="L2 · 语义检索",
        summary_en=(
            "Vector search over chunks cut at topic boundaries — the route for a question that "
            "does not share the material's wording. Per source: the intake plan decides whether "
            "this source is indexed at all, so unlike L1 it can be absent for some. Derived, and "
            "rebuilt from the recorded boundaries byte-identically."
        ),
        summary_zh=(
            "在按话题边界切出的片段上做向量检索——问题和材料用词不同时走的就是这条路。"
            "它是按来源的：某份来源到底建不建，由接收方案决定，所以和 L1 不同，"
            "它对某些来源可能根本不存在。派生层，可依据已记录的边界逐字节重建。"
        ),
        condition="intake_plan.semantic_indexing",
    ),
    AccessRoute(
        id="l3",
        source="compile",
        target="recall",
        title_en="L3 · canonical",
        title_zh="L3 · 正本",
        summary_en=(
            "The only level a model writes: threads and relations between subjects, each claim "
            "carrying a citation back to L0. It exists for the two things retrieval cannot do — "
            "follow a thread when direct search misses, and survey the whole base cheaply. Per "
            "source: the intake plan decides how much of it enters canonical, or none. "
            "Authoritative, and nothing can regenerate it."
        ),
        summary_zh=(
            "唯一由模型写入的层：主体之间的脉络与关系，每条断言都带一条回到 L0 的引用。"
            "它的存在是为了检索做不到的那两件事——直取失败时把线索接下去，以及廉价地通览全局。"
            "它是按来源的：某份来源有多少东西进正本、甚至一点都不进，由接收方案决定。"
            "它是权威层；没有任何东西能重建它。"
        ),
        condition="intake_plan.canonical_treatment",
    ),
)


# Every `Settings` field that is NOT an engine knob, with the reason it is not. The pin
# test asserts this set plus the mapped fields covers `Settings` exactly, so adding a
# field forces a classification decision instead of letting a strategy knob slip in
# unnoticed.
NON_ENGINE_SETTINGS: frozenset[str] = frozenset(
    {
        # The engine directory pointer itself. It cannot live in the engine directory
        # (nothing would know where to look), and it is deployment wiring, not strategy.
        "engine_dir",
        # Infrastructure: connection targets and the canonical root. These belong to the
        # deployment and are explicitly NOT versioned with the engine (Ruling 1).
        "pg_dsn",
        "qdrant_url",
        "qdrant_collection",
        "meili_url",
        "meili_key",
        "canonical_root",
        "cors_allow_origin_regex",
        # Secrets. They never enter the versioned unit, by construction.
        "openrouter_api_key",
        "langfuse_secret_key",
        "langfuse_public_key",
        "langfuse_base_url",
        # Provider plumbing: routing pins and call guardrails, not judgement about
        # knowledge. One timeout and one retry budget is a guardrail; a per-role matrix
        # would be a knob nobody can reason about.
        "openrouter_provider_order",
        "openrouter_allow_fallbacks",
        "llm_timeout",
        "llm_max_retries",
        # The base model spec and the single-hop role fallbacks. `engine.yaml` states the
        # four roles a person actually chooses; these exist so a role can be split off by
        # a deployment (or a benchmark harness) without inventing an engine file for it.
        "llm_model",
        "llm_model_skill",
        "llm_model_evolve",
        "llm_model_live_context",
        "llm_model_challenge",
        # Chunk sizing: the mechanical sub-splitter's token budget. `chunk_strategy` is the
        # judgement; these two are its implementation detail and are tuned by measurement.
        "chunk_size",
        "chunk_overlap",
        # The deployment's own declarations, not editable strategy: the timezone this
        # installation counts days in for a subject who states none, and the contract
        # version app.py registers from `compile/contract.md` frontmatter.
        "default_timezone",
        "user_schema_base_version",
        "user_schema_packs",
        "user_schema_matrix_path",
        # First-party preprocessing switches for context_stream sources and the briefing
        # citation aliaser: framework-internal rendering mechanics with no domain
        # judgement in them.
        "context_stream_render_roles",
        "context_stream_compile_guidance",
        "briefing_citation_alias",
        # Document rollover is mechanical maintenance, like log rotation — size-triggered,
        # meaning-preserving. Orthogonal to every knob above, which is why it is not one.
        "rollover_threshold_chars",
        "rollover_keep_recent_chars",
    }
)


def coerce_value(knob: Knob, value: object) -> object:
    """Normalize a resolved value to its declared knob type.

    Only one case does anything: an `int` knob whose backing setting is a float
    (`evolve_draft_ttl_hours`). The frozen knob-type vocabulary has no float, and a
    fractional draft TTL has no use, so the schema and the state report whole hours instead
    of leaking `24.0` into a stepper.
    """
    if knob.type == "int" and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def stage_by_id(stage_id: str) -> Stage | None:
    for stage in STAGES:
        if stage.id == stage_id:
            return stage
    return None


def stage_by_file(path: str) -> Stage | None:
    for stage in STAGES:
        if stage.file == path:
            return stage
    return None


def knob_settings() -> dict[str, str]:
    """`Settings` field name → `<stage>.<key>`, for every knob backed by a setting."""
    out: dict[str, str] = {}
    for stage in STAGES:
        for knob in stage.knobs:
            if knob.setting:
                out[knob.setting] = f"{stage.id}.{knob.key}"
    return out


def iter_knobs():
    """(stage, knob) for every knob in declaration order."""
    for stage in STAGES:
        for knob in stage.knobs:
            yield stage, knob

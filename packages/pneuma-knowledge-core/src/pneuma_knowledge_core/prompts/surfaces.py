"""The prompt SURFACE registry: what the model actually receives, key by key.

WHY THIS EXISTS
---------------
`catalog.py` is the auditable inventory of model-visible prose, addressed by key. That is
the right unit to OVERRIDE and the wrong unit to UNDERSTAND: a person looking at
`recall.cite.source_level` cannot tell which prompt it lands in, what stands before and
after it, or whether rewriting it also changes the deep lane. So the override unit stays
the catalog key and the *understanding* unit becomes the **surface** — one assembled,
model-visible prompt (the fast-recall System contract, the compile SystemMessage, the
coverage audit's question pass …) composed from ordered catalog segments.

TWO KINDS OF SURFACE
--------------------
Not every group of keys is a prose prompt. `source.preamble.*` is 28 CONDITIONAL
ALTERNATIVES and word fillers — at runtime one lead sentence is chosen and a few fillers
substituted into it — so concatenating them produced "the ownera conversationThis is…",
a sentence no model has ever received. A map that renders that is worse than no map: it
teaches a newcomer something false. So a surface declares its `kind`:

* `assembled` — a real composition function produces exactly these bytes in exactly this
  order. Every one of them is byte-pinned against that function (see below), which is why
  `kind` cannot be claimed: `pinned` and `kind == "assembled"` are the same set, enforced.
* `fragments` — a family of INDEPENDENT clauses that reach the model one at a time: the
  alternative preambles, a tool face, the sections of a human turn, a gate's rejection
  lines. There is no assembled text, so the registry refuses to render one, the payload
  carries empty strings, and every fragment states IN WORDS when it is used.

`Segment.context_*` is that statement — "this clause is emitted when …", bilingual. It is
required (mechanically) of every fragment and of every `VARIANT` segment, because those
are precisely the clauses whose position in a prompt does not explain them.

This module is a mechanism, not documentation, because four tests keep it from being a
second-hand description of the code:

* **byte pin** — for every surface of kind `assembled`, the registry's own render and the
  real composition function (`selector_contract()`, `render_system_contract()`, …) must be
  byte-for-byte equal. A contract that grows a section, loses a clause, or reorders two of
  them fails until the map says the same thing.
* **kind pin** — the pinned set and the `assembled` set are identical, so a family nobody
  can pin is a family the studio shows as fragments rather than as prose.
* **context pin** — no fragment and no variant without its bilingual "when is this used".
* **coverage pin** — every catalog key belongs to at least one surface. A new key with no
  surface is a piece of prose nobody can find in the studio, so it fails the test on the
  commit that introduces it rather than on the day somebody goes looking for it.
* **note pin** — an assembly whose byte pin had to SUPPLY runtime fields, or that offers a
  clause the deployment picks between, is an assembly template rather than a finished
  message. Those must carry `note_*`, so the console cannot present a template as "what the
  model received". The pin reads the same field table the byte pin uses, which is why the
  note cannot be forgotten on the surface that most needed it.

COMPOSITION MODEL
-----------------
An `assembled` surface is an ordered list of `Segment`s, each naming one catalog key, in
one of three roles:

* `BLOCK` — concatenated into the assembled text, in order, with its literal `prefix` /
  `suffix` glue (the `"\\n\\n"` between the contract and the skill header, and so on).
* `SLOT` — not concatenated: substituted into a named placeholder of a sibling segment
  (`recall.spine`'s `{cite}` and `{close}`). Fillers nest, so a slot's filler may itself
  declare slots.
* `VARIANT` — listed but not rendered: the two answer styles this assembly did not pick,
  the owner-profile section that only appears when a profile was supplied, the per-version
  contract clauses. They belong to the surface (that is where a person edits them) without
  claiming to be in this particular rendering of it.

A `fragments` surface uses none of that: its segments are a flat list, in the order a
person is best served reading them, each carrying its own context sentence.

Placeholders the framework fills from RUNTIME data (a skill's path templates, the round's
material, the owner's own fields) are deliberately left unsubstituted by default: the
studio renders them as visible chips, and `render_surface(..., fields=…)` is what the byte
pin uses to supply them. Nothing here awaits anything, so nothing here is a coroutine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Iterator

from . import prompt, substitute, template_fields
from .catalog import DEFAULTS

__all__ = [
    "ASSEMBLED",
    "BLOCK",
    "FRAGMENTS",
    "SLOT",
    "VARIANT",
    "GROUPS",
    "SURFACES",
    "Segment",
    "Slot",
    "Surface",
    "group_titles",
    "render_surface",
    "segment_context",
    "segment_label",
    "segments_missing_context",
    "shared_with",
    "surface_by_id",
    "surface_keys",
    "surface_note",
    "surfaces_missing_note",
    "variant_keys",
]

BLOCK = "block"
SLOT = "slot"
VARIANT = "variant"

# The two kinds of surface. `assembled` is prose the model receives in this exact order;
# `fragments` is a family of clauses it receives one at a time.
ASSEMBLED = "assembled"
FRAGMENTS = "fragments"


@dataclass(frozen=True)
class Slot:
    """One named placeholder of a segment, filled from other catalog keys.

    `keys` is a list rather than a single key because a real assembly sometimes joins
    several clauses into one placeholder (the subject-environment section's three declared
    fields), and `join` is the separator that assembly uses.
    """

    name: str
    keys: tuple[str, ...]
    join: str = ""


@dataclass(frozen=True)
class Segment:
    """One catalog key inside one surface, with the role it plays in the assembly.

    `context_en/zh` answers "when does the model actually receive this clause". An
    assembled surface answers that by position, so its blocks leave it empty; a fragment
    and a variant have no position to speak for them, so they must fill it in.
    """

    key: str
    role: str = BLOCK
    slots: tuple[Slot, ...] = ()
    # Literal glue emitted around this segment's text. May itself carry runtime
    # placeholders (the compile contract's trailing `{instructions}`), substituted from
    # the same `fields` mapping.
    prefix: str = ""
    suffix: str = ""
    context_en: str = ""
    context_zh: str = ""


@dataclass(frozen=True)
class Surface:
    """One model-visible prompt (or one family of clauses): group, titles, segments.

    `kind == ASSEMBLED` means a real composition function produces exactly these bytes in
    exactly this order, and `pinned` says a test proves it — the two are the same set, so
    the only way a surface earns the assembled reading is to be checked against the code.

    `kind == FRAGMENTS` means the clauses reach the model independently (alternative
    preambles, a tool face, gate rejections, the sections of a human turn). There is no
    assembled text for those, so `render_surface` refuses to invent one.

    `note_en/zh` is the honesty banner: an assembled surface is an assembly TEMPLATE, and
    for most of them the bytes shown are not the finished message of any one call. What the
    framework substitutes per call (the active contract's instructions, the owner profile,
    the round's dates), which alternative a knob selects, and what arrives separately in the
    HumanMessage all belong in it. A surface with no note is one whose rendered bytes really
    are what the model receives, and the console may say so.
    """

    id: str
    group: str
    title_en: str
    title_zh: str
    summary_en: str
    summary_zh: str
    segments: tuple[Segment, ...] = field(default_factory=tuple)
    kind: str = FRAGMENTS
    pinned: bool = False
    note_en: str = ""
    note_zh: str = ""


# ─────────────────────────────────────────────────────────────────── lifecycle groups

GROUPS: tuple[tuple[str, str, str], ...] = (
    ("intake", "Intake", "接收"),
    ("compile", "Compile", "编译"),
    ("challenge", "Coverage audit", "覆盖质询"),
    ("evolve", "Schema evolve", "模式演进"),
    ("recall", "Recall", "召回"),
    ("persona", "Owner profile", "主人档案"),
    ("skill", "Skill", "领域契约"),
    ("feedback", "Rejection wording", "反馈文案"),
    ("eval", "Evaluation", "评测"),
)


def group_titles() -> dict[str, dict[str, str]]:
    """group id → bilingual title, in the order the console lists them."""
    return {gid: {"en": en, "zh": zh} for gid, en, zh in GROUPS}


# ────────────────────────────────────────────────────────────────────── segment labels
#
# 338 hand-written bilingual labels would be 338 chances to rot. Instead: one bilingual
# name per key-prefix family (longest prefix wins), plus the humanized key tail — so a key
# added tomorrow already reads as "Compile gate · anchor coverage" / "编译闸门 · anchor
# coverage". `_LABELS` then refines the surfaces a person actually opens and edits.

_LABEL_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("compile.owner_env.", "Subject environment", "主体环境"),
    ("compile.owner_field.", "Subject profile line", "主体档案行"),
    ("compile.task.", "Compile task", "编译任务"),
    ("compile.tool.", "Compile tool", "编译工具"),
    ("compile.anchor.", "Claim write rejection", "断言写入拒绝"),
    ("compile.overview.", "Overview write rejection", "总览写入拒绝"),
    ("compile.patch.", "Document write rejection", "文档写入拒绝"),
    ("compile.treatment.", "Source treatment", "源处理档位"),
    ("compile.groom.", "Rollover", "归档轮换"),
    ("compile.challenge.", "Coverage audit", "覆盖审计"),
    ("compile.brief.", "Compile brief", "编译简报"),
    ("compile.worker.", "Compile retrieval reply", "编译检索回复"),
    ("compile.", "Compile contract", "编译契约"),
    ("contract.rule.", "Version contract clause", "版本契约条款"),
    ("gate.groom.", "Rollover gate", "归档闸门"),
    ("gate.evolve.", "Evolve gate", "演进闸门"),
    ("gate.", "Compile gate", "编译闸门"),
    ("source.preamble.", "Source preamble", "源引言"),
    ("source.context_stream.", "Context-stream notes", "上下文流说明"),
    ("source.", "Source guidance", "源指引"),
    ("ingest.semantic.", "Semantic segmentation", "语义切分"),
    ("ingest.email.", "Email rendering", "邮件渲染"),
    ("ingest.", "Transcript rendering", "转写渲染"),
    ("recall.fast.evidence_select.", "Evidence composition", "证据编排"),
    ("recall.fast.select.", "Full-document selection", "整篇选取"),
    ("recall.fast.plan.", "Retrieval planning", "检索规划"),
    ("recall.fast.window_note.", "Window annotation", "窗口批注"),
    ("recall.fast.timeline.", "Subject timeline", "主题时间线"),
    ("recall.fast.", "Fast recall", "快速召回"),
    ("recall.deep.tool.", "Deep tool", "深度工具"),
    ("recall.deep.", "Deep recall", "深度召回"),
    ("recall.briefing.tool.", "Briefing tool", "简报工具"),
    ("recall.briefing.", "Briefing", "简报"),
    ("recall.suggestion.focus.", "Attention scope", "注意范围"),
    ("recall.suggestion.", "Live context", "实时上下文"),
    ("recall.section.", "Evidence section", "证据分节"),
    ("recall.glance.", "Library glance", "知识库一览"),
    ("recall.profile.", "Owner profile line", "主人档案行"),
    ("recall.snapshot.", "Snapshot scope", "快照范围"),
    ("recall.style.", "Answer style", "回答风格"),
    ("recall.cite.", "Citation granularity", "引用粒度"),
    ("recall.close.", "Closing clause", "收尾条款"),
    ("recall.rerank.", "Claim reranker", "断言重排"),
    ("recall.agentic.", "Agentic budget", "代理预算"),
    ("recall.", "Recall", "召回"),
    ("evolve.propose.", "Evolve proposal", "演进提案"),
    ("evolve.tool.", "Evolve tool", "演进工具"),
    ("evolve.task.", "Evolve task", "演进任务"),
    ("evolve.service.", "Evolve retrieval reply", "演进检索回复"),
    ("evolve.", "Evolve", "演进"),
    ("skill.claim_label.", "Claim strength label", "断言强度标签"),
    ("skill.derive.", "Skill derivation", "契约推导"),
    ("skill.", "Skill", "领域契约"),
    ("persona.", "Owner profile", "主人档案"),
    ("eval.qa.", "Answer judge", "回答评判"),
    ("eval.truth_judge.", "Claim judge", "断言评判"),
    ("eval.", "Evaluation", "评测"),
)

# The refinements: the segments somebody actually opens, reads and rewrites. Everything
# else derives (see above) — a label is a wayfinding aid, and the key is always shown too.
_LABELS: dict[str, tuple[str, str]] = {
    "compile.write_contract": ("The write contract", "写入契约"),
    "compile.owner_section": ("§2 the knowledge subject", "§2 知识主体"),
    "compile.owner_unknown": ("§2 no profile supplied", "§2 未提供档案"),
    "compile.owner_env.section": ("§2 declared environment", "§2 环境声明"),
    "compile.owner_env.write_language": ("Write in the subject's language", "用主体的语言书写"),
    "compile.owner_env.day_grouping": ("Which zone days are counted in", "日历日按哪个时区计"),
    "compile.rules_header": ("Extra presentation rules header", "额外呈现规则标题"),
    "compile.skill_header": ("§5 domain judgment header", "§5 领域判断标题"),
    "compile.skill_lede": ("§5 lede", "§5 引言"),
    "compile.treatment.full": ("treatment=full", "档位 full"),
    "compile.treatment.distill": ("treatment=distill", "档位 distill"),
    "compile.treatment.card": ("treatment=card", "档位 card"),
    "compile.groom.contract": ("The history-card contract", "历史卡片契约"),
    "compile.challenge.questions_system": ("Blind question generation", "盲出问题"),
    "compile.challenge.reflect_system": ("Gap judgement", "缺口判定"),
    "compile.challenge.compensation_preamble": ("Compensation preamble", "补偿编译前言"),
    "compile.brief.system": ("Narration contract", "叙述契约"),
    "compile.brief.task": ("The record to narrate", "待叙述的记录"),
    "recall.spine": ("The shared answer spine", "共享回答脊柱"),
    "recall.cite.source_level": ("Cite to the source", "引到源级"),
    "recall.cite.precise": ("Cite to the block span", "引到块区间"),
    "recall.cite.structured": ("Return citations separately", "单独返回引用"),
    "recall.close.answer_honestly": ("Close: answer honestly", "收尾：诚实作答"),
    "recall.close.suggestion": ("Close: an unsolicited card", "收尾：不请自来的卡片"),
    "recall.style.concise": ("Style: concise", "风格：精确简短"),
    "recall.style.conversational": ("Style: conversational", "风格：自然对话"),
    "recall.style.detailed": ("Style: detailed", "风格：详尽书面"),
    "recall.fast.contract_head": ("Fast lane head", "快速车道开头"),
    "recall.deep.contract_head": ("Deep lane head", "深度车道开头"),
    "recall.briefing.contract_head": ("Briefing session head", "简报会话开头"),
    "recall.suggestion.contract_head": ("Live-context head", "实时上下文开头"),
    "recall.suggestion.detail_contract": ("Card expansion contract", "卡片展开契约"),
    "recall.suggestion.focus.general": ("Scope: the whole stream", "范围：整条流"),
    "recall.suggestion.focus.owner": ("Scope: the owner only", "范围：只看主人"),
    "recall.suggestion.focus.other": ("Scope: participants only", "范围：只看参与者"),
    "evolve.phase1_contract": ("Phase 1 — schema draft", "第一阶段 — 结构草案"),
    "evolve.phase2_contract": ("Phase 2 — reorganization", "第二阶段 — 全库重组"),
    "skill.derive_contract": ("Skill derivation contract", "契约推导合约"),
    "persona.profile_instruction": ("Profile expansion", "档案扩写"),
    "source.guidance_header": ("First-party data notes", "第一方数据说明"),
    "ingest.semantic.rubric": ("Segmentation rubric", "切分准则"),
    "ingest.semantic.human": ("Segmentation request", "切分请求"),
    "ingest.semantic.rubric_overlap": (
        "Segmentation rubric — overlapping",
        "切分准则 — 允许重叠",
    ),
    "ingest.semantic.human_overlap": (
        "Segmentation request — overlapping",
        "切分请求 — 允许重叠",
    ),
    "gate.feedback_header": ("Gate rejection header", "闸门拒绝标题"),
    "gate.evolve.feedback_header": ("Evolve gate rejection header", "演进闸门拒绝标题"),
}


def _humanize(tail: str) -> str:
    words = tail.replace("_", " ").replace(".", " ").strip()
    return words[:1].upper() + words[1:] if words else tail


def segment_label(key: str) -> dict[str, str]:
    """The bilingual label of one catalog key: refined if it has one, else derived."""
    refined = _LABELS.get(key)
    if refined is not None:
        return {"en": refined[0], "zh": refined[1]}
    for prefix, en, zh in sorted(_LABEL_FAMILIES, key=lambda f: -len(f[0])):
        if key.startswith(prefix):
            tail = _humanize(key[len(prefix) :])
            return {"en": f"{en} · {tail}", "zh": f"{zh} · {tail}"}
    return {"en": _humanize(key), "zh": _humanize(key)}


# ═══════════════════════════════════════════════════════════════════ the registry

# Shorthands so the declarations below read as composition rather than as constructor
# noise. `b` = block, `s` = slot filler, `v` = variant, `f` = one clause of a fragment
# family. `v` and `f` take their context sentence positionally, because a variant or a
# fragment without one is the defect this registry exists to prevent.
def b(key: str, *, slots: tuple[Slot, ...] = (), prefix: str = "", suffix: str = "") -> Segment:
    return Segment(key=key, role=BLOCK, slots=slots, prefix=prefix, suffix=suffix)


def s(key: str, *, slots: tuple[Slot, ...] = ()) -> Segment:
    return Segment(key=key, role=SLOT, slots=slots)


def v(key: str, en: str, zh: str) -> Segment:
    return Segment(key=key, role=VARIANT, context_en=en, context_zh=zh)


def f(key: str, en: str, zh: str) -> Segment:
    return Segment(key=key, role=BLOCK, context_en=en, context_zh=zh)


# ── the shared recall spine, as three segments. `spine(cite, close)` is one function with
# two injected clauses, so every mode that uses it repeats these three lines with its own
# pair. The repetition is the map: `shared_with` then tells a person editing the spine that
# four surfaces move at once.
def _spine(cite: str, close: str) -> tuple[Segment, ...]:
    return (
        b(
            "recall.spine",
            slots=(Slot("cite", (cite,)), Slot("close", (close,))),
        ),
        s(cite),
        s(close),
    )


# The three answer styles are a knob: one is appended to the contract, the other two are
# the branches this deployment did not pick. Which one is rendered follows the deployment's
# `answer_style` setting, so the variants say that rather than repeating the style itself.
_ANSWER_STYLE = (
    b("recall.style.conversational"),
    v(
        "recall.style.concise",
        "Appended instead of the style above when this deployment's answer style is "
        "`concise`.",
        "当本部署的回答风格设为 `concise` 时，取代上面那一段风格附在契约末尾。",
    ),
    v(
        "recall.style.detailed",
        "Appended instead of the style above when this deployment's answer style is "
        "`detailed`.",
        "当本部署的回答风格设为 `detailed` 时，取代上面那一段风格附在契约末尾。",
    ),
)


SURFACES: tuple[Surface, ...] = (
    # ─────────────────────────────────────────────────────────────────────── intake
    Surface(
        id="intake.semantic",
        group="intake",
        title_en="Semantic segmentation",
        title_zh="语义切分",
        summary_en=(
            "How the compile-role model is asked to cut a source into topic units. It "
            "returns each boundary together with a derived episode title/description; "
            "the citable chunk text stays a verbatim slice. Two output contracts share "
            "one boundary philosophy; `semantic_overlap` picks."
        ),
        summary_zh=(
            "编译角色模型被如何要求把一份材料切成话题单元，并为每个边界同时返回"
            "派生 episode 标题/描述；可引用 chunk 始终是原文的逐字片段。两套输出契约"
            "共用同一份边界哲学，"
            "由 `semantic_overlap` 决定用哪一套。"
        ),
        segments=(
            f(
                "ingest.semantic.rubric",
                "The SystemMessage of every segmentation call: the standard for where one "
                "topic ends and the next begins.",
                "每次切分调用的系统消息：一个话题在哪里结束、下一个从哪里开始的判准。",
            ),
            f(
                "ingest.semantic.human",
                "The HumanMessage of the same call, once per window of blocks: the numbered "
                "lines plus each episode's retrieval representation and start number.",
                "同一次调用的人类消息，每个块窗口一次：带编号的行，以及每个 episode 的检索表示和起始编号。",
            ),
            f(
                "ingest.semantic.source_context",
                "The optional source title/date metadata placed in the HumanMessage.",
                "放入人类消息的可选来源标题/日期元数据。",
            ),
            f(
                "ingest.semantic.rubric_overlap",
                "The SystemMessage instead of the one above when `semantic_overlap` is "
                "`smart`: the same boundary philosophy, but segments come back as closed "
                "intervals that may share a hinge block with their neighbour.",
                "当 `semantic_overlap` 为 `smart` 时，取代上面那条系统消息："
                "边界哲学不变，但段以前闭后闭区间返回，相邻两段可以共享转折块。",
            ),
            f(
                "ingest.semantic.human_overlap",
                "The HumanMessage that rides with the overlapping rubric, once per window "
                "of blocks: the same numbered lines, asking for episode representations "
                "and start/end coordinates.",
                "与「允许重叠」准则同行的人类消息，每个块窗口一次："
                "同样带编号的行，但要求返回 episode 表示和起止编号。",
            ),
            f(
                "ingest.semantic.describe_rubric",
                "The one-time legacy-manifest contract: describe fixed spans without "
                "changing their coordinates.",
                "旧 manifest 的一次性契约：为固定区间补描述，不改变坐标。",
            ),
            f(
                "ingest.semantic.describe_human",
                "The fixed spans and numbered source blocks for that migration call.",
                "该迁移调用中的固定区间与带编号来源块。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="intake.source_guidance",
        group="intake",
        title_en="First-party data notes",
        title_zh="第一方数据说明",
        summary_en=(
            "The per-source-type preface that rides the compile human turn: what the "
            "data's fields mean, and what the stream is for."
        ),
        summary_zh=(
            "随编译人类回合出现的按源类型前言：数据的字段是什么意思，这条流是干什么用的。"
        ),
        segments=(
            b(
                "source.guidance_header",
                slots=(
                    Slot("data_context", ("source.context_stream.data_context",)),
                    Slot("app_context", ("source.context_stream.app_context",)),
                ),
            ),
            s("source.context_stream.data_context"),
            s("source.context_stream.app_context"),
        ),
        kind=ASSEMBLED,
        pinned=True,
    ),
    Surface(
        id="intake.source_preamble",
        group="intake",
        title_en="Source provenance preambles",
        title_zh="源出处引言",
        summary_en=(
            "One sentence in front of every source in the compile task, stating who wrote "
            "it, when, and whether its judgements belong to the subject. Which sentence is "
            "chosen depends on what the material actually supplies."
        ),
        summary_zh=(
            "编译任务里每份源材料前面的一句话：谁写的、什么时候、里面的判断算不算主体自己的。"
            "选哪一句取决于材料真正提供了什么。"
        ),
        segments=(
            # Two fillers every branch below can use.
            f(
                "source.preamble.owner_default",
                "Substituted for the subject's name in every sentence below, whenever the "
                "caller does not know their display name.",
                "在下面每一句里代替主体的名字——当调用方不知道主体的显示名时使用。",
            ),
            f(
                "source.preamble.title_quoted",
                "Fills `{title}` of the external-material, unattributed-document and "
                "everything-else sentences when the material has a title; empty when it "
                "has none.",
                "材料有标题时，填「外部材料」「无署名文档」「其余材料」这几句的 `{title}`；"
                "没有标题就为空。",
            ),
            # ── a diarized stream (chat, meeting, call): stream_tail is the sentence.
            f(
                "source.preamble.stream_tail",
                "The finished sentence for a diarized stream: the lead, then the subject's "
                "role in it.",
                "一条带发言人的流最终成句的形状：先是开头，再是主体在其中的角色。",
            ),
            f(
                "source.preamble.stream_lead",
                "Fills `{lead}` above — who, when, in what scene, how many messages.",
                "填上面的 `{lead}`：谁、什么时候、在什么场景、多少条消息。",
            ),
            f(
                "source.preamble.stream_scene_default",
                "Fills `{scene}` of the lead when the ingest side supplied no scene phrase — "
                "core never guesses the medium.",
                "当接收侧没有给出场景说法时，填开头的 `{scene}`——core 从不猜测媒介。",
            ),
            f(
                "source.preamble.stream_part",
                "Appended to the lead only when that day's stream was split into several "
                "parts.",
                "只有当那一天的流被切成多个部分时，才追加到开头里。",
            ),
            f(
                "source.preamble.stream_role_spoke",
                "Fills `{role}` when the subject spoke at least once in this part.",
                "当主体在这一部分里至少发言一次时，填 `{role}`。",
            ),
            f(
                "source.preamble.stream_role_silent",
                "The alternative `{role}` when the subject was present but said nothing.",
                "主体在场却没有发言时，`{role}` 换成这一句。",
            ),
            f(
                "source.preamble.stream_mentions",
                "Appended to the role clause when the subject was @-mentioned at least once.",
                "当主体被 @ 提及至少一次时，追加到角色小句后面。",
            ),
            f(
                "source.preamble.stream_replies",
                "Appended to the role clause when at least one message replies to the subject.",
                "当至少有一条消息是在回复主体时，追加到角色小句后面。",
            ),
            # ── a document that states authorship or a timestamp.
            f(
                "source.preamble.document_lead",
                "The sentence for a document whose metadata states an author, a creation "
                "time, or that the subject wrote it.",
                "当文档元数据说明了作者、创建时间、或「主体自己写的」时，用这一句。",
            ),
            f(
                "source.preamble.document_kind_default",
                "Fills `{kind}` above when the metadata declares no document kind.",
                "元数据没有声明文档类型时，填上面的 `{kind}`。",
            ),
            f(
                "source.preamble.document_other_author",
                "Fills `{who}` when the document is not the subject's and the author's name "
                "is not supplied.",
                "当文档不属于主体、而且没有给出作者名字时，填 `{who}`。",
            ),
            f(
                "source.preamble.document_title",
                "Fills `{title}` of the document sentence when the source has a title.",
                "材料有标题时，填文档那一句的 `{title}`。",
            ),
            f(
                "source.preamble.document_parent",
                "Fills `{parent}` when the metadata names the document this one is filed "
                "under.",
                "当元数据说明了这份文档挂在哪份父文档下时，填 `{parent}`。",
            ),
            f(
                "source.preamble.document_created",
                "The time clause when the metadata carries a creation timestamp.",
                "元数据带有创建时间时，时间小句用这一条。",
            ),
            f(
                "source.preamble.document_updated",
                "Added when the last-updated day differs from the creation day — an edited "
                "document is a different fact from a written one.",
                "当最后更新日与创建日不是同一天时追加——「改过的文档」和「写下的文档」是两件事。",
            ),
            f(
                "source.preamble.document_created_and_updated",
                "Joins the two clauses above when the document carries both timestamps.",
                "当两个时间戳都有时，把上面两条小句连起来。",
            ),
            f(
                "source.preamble.document_occurred",
                "The time clause when the document states no timestamp of its own but the "
                "framework holds its occurrence day.",
                "文档自己没有时间戳、但框架握有它的发生日时，时间小句用这一条。",
            ),
            f(
                "source.preamble.document_when",
                "Wraps whichever time clause was built, into `{when}` of the document "
                "sentence; empty when the document has no date at all.",
                "把上面选中的时间小句包进文档那一句的 `{when}`；文档完全没有日期时为空。",
            ),
            f(
                "source.preamble.document_stance_owner",
                "Closes the document sentence when the subject is the author: its judgements "
                "count as theirs.",
                "当主体就是作者时，用它收束文档那一句：里面的判断算主体自己的。",
            ),
            f(
                "source.preamble.document_stance_other",
                "The alternative close when somebody else wrote it — the clause that keeps "
                "another person's decisions out of the subject's record.",
                "文档由别人所写时的另一种收束——正是这一句拦住「把别人的决定记成主体的」。",
            ),
            # ── external material supplied for the subject to read.
            f(
                "source.preamble.reference",
                "Replaces the whole sentence for `source_class=reference` with no authorship "
                "metadata and no date.",
                "当 `source_class=reference` 且既无署名元数据也无日期时，整句换成这一条。",
            ),
            f(
                "source.preamble.reference_dated",
                "The same external-material sentence when the framework does hold its date.",
                "同样是外部材料，但框架握有它的日期时用这一条。",
            ),
            # ── a document with no authorship metadata at all.
            f(
                "source.preamble.document_unknown",
                "A document whose material supplies neither author nor authoring time.",
                "材料既没有作者、也没有写作时间的文档。",
            ),
            f(
                "source.preamble.document_unknown_dated",
                "The same case with an occurrence day the framework holds — relative time in "
                "it resolves against that day.",
                "同样的情况，但框架握有发生日——材料里的相对时间以那一天为基准解析。",
            ),
            # ── everything that is not a document.
            f(
                "source.preamble.fallback",
                "Every non-document source (conversation, im, email, structured, library) "
                "carrying no date: attribution and time both stay pending.",
                "所有非文档材料（对话、IM、邮件、结构化、文档库）且没有日期时：署名与时间都悬置。",
            ),
            f(
                "source.preamble.fallback_dated",
                "The same, dated — the ordinary path, since ingest stamps every non-document "
                "source with its occurrence day.",
                "同样的情况但有日期——这是常规路径，因为接收时每份非文档材料都被打上了发生日。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="intake.rendering",
        group="intake",
        title_en="Transcript and email rendering",
        title_zh="转写与邮件渲染",
        summary_en=(
            "The labels a normalized source is rendered with before any model reads it: "
            "who is the owner, how a participant is numbered, how a turn line is written."
        ),
        summary_zh=(
            "任何模型读到之前，规范化材料被渲染成的标签：谁是主人、参与者怎么编号、"
            "一轮发言怎么写成一行。"
        ),
        segments=(
            f(
                "ingest.owner_label",
                "The name the subject's own turns are labelled with, in every transcript and "
                "in the live-context stream.",
                "主体自己的发言在每份转写、以及实时上下文流里被标成的名字。",
            ),
            f(
                "ingest.other_label",
                "How anybody who is not the subject is labelled: numbered in first-appearance "
                "order, so no real name has to be invented.",
                "非主体的人被标成什么：按首次出现顺序编号，从而不必编造任何真实姓名。",
            ),
            f(
                "ingest.speaker_alias",
                "Appended to a participant's label when the material carries a stable speaker "
                "id, so the same person stays the same person across parts.",
                "当材料带有稳定的说话人 id 时，追加到参与者标签后面，让同一个人跨部分保持同一个人。",
            ),
            f(
                "ingest.owner_wrapped",
                "Used instead when the material already names the subject: their own name is "
                "kept and marked as the subject's.",
                "当材料本身已经给出主体的名字时改用这一条：保留原名，并标明这是主体。",
            ),
            f(
                "ingest.turn_line",
                "One line of a rendered transcript — every turn of every stream goes through "
                "this shape before any model reads it.",
                "转写中的一行——任何模型读到之前，每条流的每一轮发言都先过这个形状。",
            ),
            f(
                "ingest.email.subject",
                "The first line of a rendered email, before its body.",
                "渲染一封邮件时正文之前的第一行。",
            ),
            f(
                "ingest.email.attachments",
                "Added to a rendered email only when it carries attachments, followed by their "
                "filenames.",
                "只有当邮件带附件时才追加，后面接附件文件名。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    # ────────────────────────────────────────────────────────────────────── compile
    Surface(
        id="compile.system",
        group="compile",
        title_en="The compile SystemMessage",
        title_zh="编译系统消息",
        summary_en=(
            "The whole constitution the compile agent reads before it writes anything: "
            "what knowledge compilation is, who the subject is, the one criterion, the "
            "four mechanisms, and this engine's own domain section. Byte-stable per "
            "(skill, subject, overlay) — invariant I5."
        ),
        summary_zh=(
            "编译代理写下任何东西之前读到的整部宪法：什么是知识编译、主体是谁、唯一判准、"
            "四组机制，以及本引擎自己的领域段。按 (契约, 主体, 覆盖) 三元组逐字节稳定"
            "——不变量 I5。"
        ),
        segments=(
            b(
                "compile.write_contract",
                slots=(Slot("owner", ("compile.owner_unknown",)),),
                suffix="\n",
            ),
            s(
                "compile.owner_unknown",
                slots=(Slot("environment", ("compile.owner_env.section",)),),
            ),
            s(
                "compile.owner_env.section",
                slots=(
                    Slot(
                        "lines",
                        (
                            "compile.owner_env.region_unknown",
                            "compile.owner_env.timezone_unknown",
                            "compile.owner_env.language_unknown",
                        ),
                        join="\n",
                    ),
                    Slot(
                        "policy",
                        (
                            "compile.owner_env.write_language",
                            "compile.owner_env.day_grouping",
                        ),
                        join="\n",
                    ),
                ),
            ),
            s("compile.owner_env.region_unknown"),
            s("compile.owner_env.timezone_unknown"),
            s("compile.owner_env.language_unknown"),
            s("compile.owner_env.write_language"),
            s("compile.owner_env.day_grouping"),
            b("compile.skill_header", suffix="\n\n"),
            b("compile.skill_lede", suffix="\n\n{instructions}\n"),
            # Rendered instead of the "no profile" section as soon as a subject profile is
            # supplied, with its identity lines built from the field templates below.
            v(
                "compile.owner_section",
                "Replaces §2 above as soon as a subject profile is supplied; its identity "
                "lines come from the field templates below.",
                "一旦提供了主体档案，就整段替换上面的 §2；里面的身份行由下面那些字段模板拼出。",
            ),
            v(
                "compile.owner_field.name",
                "One identity line of §2, when the profile states a name.",
                "§2 的一行身份信息，当档案里有名字时出现。",
            ),
            v(
                "compile.owner_field.occupation",
                "One identity line of §2, when the profile states an occupation.",
                "§2 的一行身份信息，当档案里有职业时出现。",
            ),
            v(
                "compile.owner_field.industry_role",
                "One identity line of §2, when the profile states an industry and a role.",
                "§2 的一行身份信息，当档案里有行业与角色时出现。",
            ),
            v(
                "compile.owner_field.working_style",
                "One identity line of §2, when the profile states how the subject works.",
                "§2 的一行身份信息，当档案说明了主体的工作方式时出现。",
            ),
            v(
                "compile.owner_field.collab_mode",
                "Folded into the way-of-working line when the profile also states a "
                "collaboration mode.",
                "当档案还说明了协作模式时，并进「工作方式」那一行。",
            ),
            v(
                "compile.owner_field.background",
                "One identity line of §2, when the profile carries a background note.",
                "§2 的一行身份信息，当档案带有背景说明时出现。",
            ),
            v(
                "compile.owner_field.interests",
                "One identity line of §2, when the profile lists long-standing interests.",
                "§2 的一行身份信息，当档案列出了长期兴趣时出现。",
            ),
            v(
                "compile.owner_field.unspecified",
                "Stands in for a field the profile leaves blank — §2 says "
                "\"not provided\" rather than dropping the line silently.",
                "代替档案里留空的字段——§2 会明说「未提供」，而不是静默地少一行。",
            ),
            v(
                "compile.owner_field.unlabeled",
                "Stands in for a labelled sub-field whose label is missing, so a half-filled "
                "profile still reads as a sentence.",
                "代替缺了标签的子字段，让填了一半的档案仍然读得通。",
            ),
            v(
                "compile.owner_field.list_separator",
                "Joins the items of a list-valued profile field (interests, for instance).",
                "连接列表型档案字段的各项（例如兴趣）。",
            ),
            v(
                "compile.owner_field.detail_separator",
                "Joins the several details inside one identity line.",
                "连接同一行身份信息里的多个细节。",
            ),
            # The declared-environment lines for the states a profile DOES supply.
            v(
                "compile.owner_env.region",
                "The declared-environment line when the profile does state a region.",
                "档案确实写明了地区时，环境声明里的那一行。",
            ),
            v(
                "compile.owner_env.timezone_provider",
                "The timezone line when this deployment resolved the zone for the material "
                "itself.",
                "当本部署为这批材料自己解析出时区时，用这一行。",
            ),
            v(
                "compile.owner_env.timezone_profile",
                "The timezone line when the zone is on record in the subject's profile.",
                "当时区记录在主体档案里时，用这一行。",
            ),
            v(
                "compile.owner_env.timezone_default",
                "The timezone line when nothing is on record and the deployment's default is "
                "in use — it says so, because dates are still counted in it.",
                "当没有任何记录、只能用部署默认时区时的那一行——它会明说，因为日期仍按该时区计。",
            ),
            v(
                "compile.owner_env.timezone_unstated",
                "The bare timezone line, for a caller that supplies a zone with no account of "
                "where it came from.",
                "最简的时区行：调用方给了时区，但没有说明它从何而来。",
            ),
            v(
                "compile.owner_env.language",
                "The declared-environment line when the profile does state a language.",
                "档案确实写明了语言时，环境声明里的那一行。",
            ),
            # Emitted only by a skill version that declares extra contract clauses.
            v(
                "compile.rules_header",
                "Opens an extra section, only for a skill version that declares presentation "
                "rules of its own.",
                "只有当某个契约版本自己声明了呈现规则时，才开出这一节。",
            ),
            v(
                "contract.rule.citation_granularity",
                "One such rule, emitted only by a skill version that declares it.",
                "其中一条规则，只有声明了它的契约版本才发出。",
            ),
            v(
                "contract.rule.citation_shape",
                "One such rule, emitted only by a skill version that declares it.",
                "其中一条规则，只有声明了它的契约版本才发出。",
            ),
            v(
                "contract.rule.strength_labels",
                "One such rule, emitted only by a skill version that declares it — it is what "
                "puts the three strength labels in force.",
                "其中一条规则，只有声明了它的契约版本才发出——正是它让三档强度标签生效。",
            ),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "What you are reading is the ASSEMBLY TEMPLATE, not the finished message of any "
            "one compile. Four values are substituted per call from the compile contract in "
            "force: `{skill_id}`, `{version}`, `{templates}` (its path families) and "
            "`{instructions}` (its whole domain section). §2 is the owner section: it reads "
            "\"no profile supplied\" here, and is replaced wholesale by the profile section "
            "— built from the field and environment clauses listed below — as soon as the "
            "engine directory holds one. `{slug}` is the one brace that is NOT an injection "
            "point: it is part of a path template the model is meant to read literally. This "
            "round's material, time frame and existing outline are not here at all; they "
            "arrive in the HumanMessage (see 编译回合), which is what keeps this message "
            "byte-stable — invariant I5."
        ),
        note_zh=(
            "你读到的是**装配模板**，不是某一次编译的最终消息。每次调用会从当时生效的编译契约代入"
            "四个值：`{skill_id}`、`{version}`、`{templates}`（它的路径家族）与 `{instructions}`"
            "（它完整的领域段）。§2 是主体档案段：这里显示的是「本轮没有提供主体档案」，一旦引擎"
            "目录里有档案，它就会被整段换成由下面那些字段与环境子句拼出的档案段。`{slug}` 是唯一"
            "不属于注入点的花括号——它是路径模板的一部分，本来就要让模型逐字读到。本轮材料、时间"
            "框与既有提纲根本不在这里，它们随人类消息到达（见「编译回合」）；正是这一点让这条消息"
            "逐字节稳定——不变量 I5。"
        ),
    ),
    Surface(
        id="compile.task",
        group="compile",
        title_en="The compile round (human turn)",
        title_zh="编译回合（人类消息）",
        summary_en=(
            "Everything that changes round to round: the time frame, the treatments in "
            "use, this round's material, the outline of existing canonical, and the "
            "auto-recalled claims to align against."
        ),
        summary_zh=(
            "每一轮都会变的东西：时间框架、这一轮用到的处理档位、本轮材料、"
            "既有正本的大纲，以及用来对齐的自动召回断言。"
        ),
        segments=(
            f(
                "compile.task.guidance_header",
                "Opens the source-type notes, when this round's material has any.",
                "当本轮材料带有按源类型的说明时，开出那一节。",
            ),
            f(
                "compile.task.treatment_header",
                "Opens the treatment section, listing only the treatments this round actually "
                "uses.",
                "开出处理档位那一节，只列出本轮真正用到的档位。",
            ),
            f(
                "compile.treatment.full",
                "Explains `treatment=full`, when at least one source this round is set to it.",
                "当本轮至少有一份材料是 `treatment=full` 时，解释这个档位。",
            ),
            f(
                "compile.treatment.distill",
                "Explains `treatment=distill`, when at least one source this round is set to it.",
                "当本轮至少有一份材料是 `treatment=distill` 时，解释这个档位。",
            ),
            f(
                "compile.treatment.card",
                "Explains `treatment=card`, when at least one source this round is set to it.",
                "当本轮至少有一份材料是 `treatment=card` 时，解释这个档位。",
            ),
            f(
                "compile.task.time_header",
                "Opens the time frame — always present, because every date the agent writes is "
                "resolved against it.",
                "开出时间框架那一节——始终出现，因为代理写下的每个日期都以它为基准解析。",
            ),
            f(
                "compile.task.time_now",
                "The compile date and the subject's own zone: always stated.",
                "编译日期与主体自己的时区：总是说明。",
            ),
            f(
                "compile.task.time_zone_changed",
                "Added only when the subject's timezone changed, so already-normalized dates "
                "are not re-read under the new zone.",
                "只有当主体的时区变更过时才追加，避免已归一化的日期被按新时区重读。",
            ),
            f(
                "compile.task.time_window",
                "Added when the round's material has a known occurrence span.",
                "当本轮材料有已知的发生时间跨度时追加。",
            ),
            f(
                "compile.task.time_multi_day",
                "Added when one round bundles sources from several calendar days.",
                "当一轮里打包了跨多个日历日的材料时追加。",
            ),
            f(
                "compile.task.time_relative_rule",
                "The rule for turning \"yesterday\" into a date: present whenever the material "
                "has a date to resolve against.",
                "把「昨天」换算成具体日期的规则：只要材料有可用的基准日期就出现。",
            ),
            f(
                "compile.task.time_unknown",
                "Replaces the dated lines when the material carries no occurrence time at all "
                "— then no absolute date may be inferred.",
                "当材料完全没有发生时间时，取代上面那些带日期的行——此时不得推断任何绝对日期。",
            ),
            f(
                "compile.task.sources_header",
                "Opens this round's material.",
                "开出本轮材料那一节。",
            ),
            f(
                "compile.task.source_heading",
                "The heading of each source — this is where the `source_id` a citation must "
                "name is shown.",
                "每份材料的标题行——引用要写的 `source_id` 就在这里出现。",
            ),
            f(
                "compile.task.treatment_tag",
                "Marks one source's treatment under its heading.",
                "在某份材料的标题行下标出它的处理档位。",
            ),
            f(
                "compile.task.block_line",
                "One numbered block of source text, once per block — the `¶` numbers a "
                "citation's span refers to.",
                "材料原文的一个编号块，每块一次——引用区间指的就是这些 `¶` 编号。",
            ),
            f(
                "compile.task.image_derived",
                "A labelled caption or OCR representation aligned to the preceding block.",
                "与上一编号块对齐、并明确标注的 caption 或 OCR 表示。",
            ),
            f(
                "compile.task.image_without_derived",
                "States that an image exists even when no textual representation was supplied.",
                "即使没有文本表示，也明确说明该编号块带有图片。",
            ),
            f(
                "compile.task.native_images_header",
                "Opens the native image content-block section when native delivery is active.",
                "启用原生图片传递时，开出图片内容块一节。",
            ),
            f(
                "compile.task.native_image_locator",
                "Binds each following native image block to its exact citable source block.",
                "把紧随其后的原生图片块绑定到可引用的确切来源块。",
            ),
            f(
                "compile.task.outline_header",
                "Opens the outline of everything already in canonical.",
                "开出「既有正本全貌」那一节。",
            ),
            f(
                "compile.task.outline_note",
                "The instruction that goes with the outline: update an existing subject in "
                "place instead of opening a second document about it.",
                "跟着大纲的那条指令：既有主题就地更新，不要再开第二份文档写同一件事。",
            ),
            f(
                "compile.task.outline_empty",
                "Replaces the outline when the knowledge base is still empty.",
                "知识库还是空的时候，取代大纲本身。",
            ),
            f(
                "compile.task.outline_entry",
                "One line of the outline, once per existing document.",
                "大纲里的一行，每份既有文档一次。",
            ),
            f(
                "compile.task.outline_entry_tail",
                "Appended to an outline line to list that document's section headings.",
                "追加到大纲行后面，列出那份文档的小节标题。",
            ),
            f(
                "compile.task.outline_entry_definition",
                "One line under a document that has an overview: its definition — the one "
                "sentence saying what the subject is.",
                "带总览的文档下面的一行：它的 definition——说明这个主体是什么的那一句。",
            ),
            f(
                "compile.task.outline_entry_ledger",
                "One line under a document that has NO overview definition: the head of its "
                "own current ledger, in the ledger's own words.",
                "没有总览 definition 的文档下面的一行：它自己当前账本的开头，用账本原话。",
            ),
            f(
                "compile.task.outline_entry_component",
                'One extra line an enabled index component adds under a document of its family (an identity, an alias).',
                '已启用的索引组件在其族的文档下追加的一行（身份、别名）。',
            ),
            f(
                "compile.task.outline_entry_volume",
                "The outline line of a frozen archive volume instead — read-only, citable, "
                "never written to.",
                "换成冻结归档卷的大纲行：只读、可引用、永不写入。",
            ),
            f(
                "compile.task.retrieved_header",
                "Opens the auto-recalled existing claims, when the retrieval found any.",
                "当自动召回有命中时，开出「既有相关断言」那一节。",
            ),
            f(
                "compile.task.retrieved_note",
                "The clause that keeps those claims from being mistaken for evidence: they are "
                "there to be updated, not to be cited.",
                "拦住「把这些断言当成本轮证据」的那一句：它们是待更新的对象，不是引用来源。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="compile.tools",
        group="compile",
        title_en="Compile tool face",
        title_zh="编译工具面",
        summary_en=(
            "The tool descriptions the compile agent chooses from, and the replies it "
            "reads back. A reply is as model-visible as a description: the agent decides "
            "its next call from it."
        ),
        summary_zh=(
            "编译代理据以选择的工具描述，以及它读回的结果。结果和描述一样是模型可见的："
            "代理正是据此决定下一次调用。"
        ),
        segments=(
            f(
                "compile.tool.list_documents",
                "The description of `list_documents` in the tool list, every round.",
                "工具清单里 `list_documents` 的描述，每轮都在。",
            ),
            f(
                "compile.tool.read_document",
                "The description of `read_document` in the tool list, every round.",
                "工具清单里 `read_document` 的描述，每轮都在。",
            ),
            f(
                "compile.tool.read_document_frozen_notice",
                "Prefixed to a `read_document` reply when the path read is a frozen archive "
                "volume: cite it, never edit it.",
                "当读到的路径是冻结归档卷时，加在 `read_document` 回复前面：可引用，不可编辑。",
            ),
            f(
                "compile.tool.create_document",
                "The description of `create_document` — it also states that the system, not "
                "the model, assigns every id and derives the title.",
                "`create_document` 的描述——它同时说明 id 全部由系统而非模型分配、title 由系统"
                "派生。",
            ),
            f(
                "compile.tool.edit_claim",
                "The description of `edit_claim`: rewrite one claim in place, anchor preserved.",
                "`edit_claim` 的描述：就地重写一条断言，锚点保持不变。",
            ),
            f(
                "compile.tool.append_block",
                "The description of `append_block`: add one claim, anchor assigned by the "
                "system.",
                "`append_block` 的描述：新增一条断言，锚点由系统分配。",
            ),
            f(
                "compile.tool.supersede_claim",
                'The `supersede_claim` description: the world changed — the new claim is the current state, the old one stays as frozen history.',
                '`supersede_claim` 的描述：世界变了——新断言是当前状态，旧断言保留为冻结历史。',
            ),
            f(
                "compile.tool.rewrite_overview",
                "The `rewrite_overview` description: the document's current picture in four "
                "slots, replaced whole when this round changed it.",
                "`rewrite_overview` 的描述：文档当前画像的四个槽位，本轮改变了它就整体替换。",
            ),
            f(
                "compile.tool.set_fields",
                "The `set_fields` description: frontmatter fields, minus the ones the system "
                "and the index components own.",
                "`set_fields` 的描述：前置字段，除掉系统和索引组件各自持有的那些。",
            ),
            f(
                "compile.tool.finish_compile",
                "The description of `finish_compile` — the call that submits the round to the "
                "citation gate.",
                "`finish_compile` 的描述——正是这次调用把本轮提交给引用闸门。",
            ),
            f(
                "compile.tool.search_knowledge",
                "The description of `search_knowledge`, present only when an L3 retrieval port "
                "is wired.",
                "`search_knowledge` 的描述，只有接上了 L3 检索端口时才出现。",
            ),
            f(
                "compile.tool.search_source",
                "The description of `search_source`, present only when an L1/L2 retrieval port "
                "is wired.",
                "`search_source` 的描述，只有接上了 L1/L2 检索端口时才出现。",
            ),
            f(
                "compile.tool.search_knowledge_unavailable",
                "Takes that description's place when no L3 port is wired — the agent is told "
                "what it may do instead.",
                "没有接 L3 端口时取代上面那条描述——并告诉代理改用什么。",
            ),
            f(
                "compile.tool.search_source_unavailable",
                "Takes the L1/L2 description's place when no such port is wired.",
                "没有接 L1/L2 端口时，取代那条描述。",
            ),
            f(
                "compile.tool.list_documents_empty",
                "The `list_documents` reply when the knowledge base holds no documents yet.",
                "知识库里还没有文档时，`list_documents` 的回复。",
            ),
            f(
                "compile.tool.create_document_result",
                "The `create_document` reply: the path, and the anchors the system just "
                "assigned.",
                "`create_document` 的回复：路径，以及系统刚分配的锚点。",
            ),
            f(
                "compile.tool.edit_claim_result",
                "The `edit_claim` reply, confirming the anchor survived the rewrite.",
                "`edit_claim` 的回复，确认重写后锚点仍然保留。",
            ),
            f(
                "compile.tool.append_block_result",
                "The `append_block` reply, naming the anchor the system assigned.",
                "`append_block` 的回复，点明系统分配的锚点。",
            ),
            f(
                "compile.tool.supersede_claim_result",
                'The `supersede_claim` reply, naming the successor anchor the system assigned.',
                '`supersede_claim` 的回复，点明系统分配的后继锚点。',
            ),
            f(
                "compile.tool.rewrite_overview_result",
                "The `rewrite_overview` reply: which slots were written, and the anchors the "
                "system assigned to them.",
                "`rewrite_overview` 的回复：写了哪些槽位，以及系统给它们分配的锚点。",
            ),
            f(
                "compile.tool.overview_removed",
                "Stands in for the slot list when a `rewrite_overview` with nothing in it "
                "removed the region instead of writing one.",
                "当空的 `rewrite_overview` 删掉了总览区域而不是写入时，用它代替槽位清单。",
            ),
            f(
                "compile.tool.set_fields_result",
                "The `set_fields` reply, naming the fields that were written.",
                "`set_fields` 的回复，点明写入了哪些字段。",
            ),
            f(
                "compile.tool.finish_compile_result",
                "The `finish_compile` reply, once the gate accepted the round.",
                "闸门接受本轮后，`finish_compile` 的回复。",
            ),
            f(
                "compile.tool.unknown_tool",
                "The reply to a call naming a tool that does not exist.",
                "当调用了一个并不存在的工具时的回复。",
            ),
            f(
                "compile.budget.notice",
                "Arrives once per round, after the batch that dropped the remaining "
                "tool-call budget to its low-water mark: how many calls are left, and what "
                "the same predicates the gate will run already find owed on the draft.",
                "在使本轮剩余工具调用预算跌到低水位的那批调用之后，每轮出现一次：还剩多少次调用，"
                "以及闸门稍后要跑的同一批判定在当前草稿上已经认定欠下了什么。",
            ),
            f(
                "compile.budget.owed_none",
                "Stands in for the owed list in that notice when those predicates find "
                "nothing outstanding.",
                "当那些判定没有查出任何欠项时，在该提示里代替欠项清单。",
            ),
            f(
                "compile.budget.call_refused",
                "The reply to a call in the same batch that the exhausted budget did not "
                "reach — every call still gets an answer, so the transcript stays a legal "
                "tool-call/result exchange.",
                "同一批里预算已经用尽、没能执行到的那些调用得到的回复——每次调用都拿到答复，"
                "对话因此仍是一次合法的工具调用/结果往返。",
            ),
            f(
                "compile.tool.round_ended",
                "The same answer for a call the batch's own `finish_compile` got in front "
                "of: the round was over before this call's turn came.",
                "同一批里被自己的 `finish_compile` 抢在前面的调用得到的同类答复：轮到它时，"
                "这一轮已经结束了。",
            ),
            f(
                "compile.tool.invalid_call",
                "The answer to a call whose arguments did not arrive as valid JSON — the "
                "provider still counts it as a call, so it gets a result like any other "
                "and is charged to the round's budget like a refused one.",
                "当一次调用的参数不是合法 JSON 时给它的答复——供应商仍把它算作一次调用，"
                "所以它和别的调用一样拿到结果，也和被拒调用一样计入本轮预算。",
            ),
            f(
                "compile.tool.call_failed",
                "The reply when a tool call raised — the agent reads the error and decides its "
                "next call from it.",
                "工具调用抛错时的回复——代理读到这段错误，并据此决定下一步。",
            ),
            f(
                "compile.anchor.none",
                "Stands in for an empty anchor list inside those replies.",
                "在上面那些回复里，代替空的锚点列表。",
            ),
            f(
                "compile.worker.search_failed",
                "Returned in place of results when the retrieval call itself failed.",
                "检索调用本身失败时，取代结果返回。",
            ),
            f(
                "compile.worker.knowledge_empty",
                "Returned when a `search_knowledge` query matched no existing claim.",
                "`search_knowledge` 查询没有命中任何既有断言时返回。",
            ),
            f(
                "compile.worker.source_empty",
                "Returned when a `search_source` query matched no raw material.",
                "`search_source` 查询没有命中任何原始材料时返回。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="compile.groom_contract",
        group="compile",
        title_en="Rollover — the history card",
        title_zh="归档轮换 — 历史卡片",
        summary_en=(
            "The one model call inside document rollover: a document grew too large, its "
            "oldest entries moved verbatim into a frozen volume, and this writes the card "
            "that stands where they were."
        ),
        summary_zh=(
            "文档归档轮换里唯一的模型调用：一份文档太大了，最早的条目被逐字搬进冻结卷，"
            "这次调用写的是站在它们原处的那张卡片。"
        ),
        segments=(b("compile.groom.contract"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The SystemMessage only, and nothing is substituted into it. What changes per rollover "
            "arrives in the HumanMessage: which document, the card being replaced, and the "
            "entries moving into the frozen volume (see 归档轮换 — 任务与卡片渲染)."
        ),
        note_zh=(
            "这里只有系统消息，而且没有任何东西被代入其中。每次归档会变的东西随人类消息到达："
            "哪份文档、正在被替换的卡片、以及要搬进冻结卷的那些条目（见「归档轮换 — 任务与卡片渲染」）。"
        ),
    ),
    Surface(
        id="compile.groom_task",
        group="compile",
        title_en="Rollover — task and card rendering",
        title_zh="归档轮换 — 任务与卡片渲染",
        summary_en=(
            "What the rollover call is shown (the document, the previous card, the "
            "entries being archived) and the three strings its answer is rendered into — "
            "which land in canonical, so they are prose a deployment owns."
        ),
        summary_zh=(
            "归档调用看到的东西（文档、上一张卡片、正在被归档的条目），"
            "以及它的回答被渲染成的那几个字符串——它们会落进正本，所以属于部署方自己的文案。"
        ),
        segments=(
            f(
                "compile.groom.task_header",
                "Opens the rollover request: which document, how many entries, which volume "
                "they move into.",
                "开出归档请求：哪份文档、多少条目、搬进哪一卷。",
            ),
            f(
                "compile.groom.previous_header",
                "Introduces the card being replaced, when this document has been rolled over "
                "before.",
                "当这份文档以前归档过时，引出正在被替换的那张卡片。",
            ),
            f(
                "compile.groom.previous_empty",
                "Takes its place on a document's first rollover.",
                "文档第一次归档时取代上一条。",
            ),
            f(
                "compile.groom.archived_header",
                "Introduces the entries being archived, with the ids the card must reference.",
                "引出正在被归档的条目，附上卡片必须引用的那些 id。",
            ),
            f(
                "compile.groom.archived_truncated",
                "Added when the archive is too long to show whole — the oldest lines are "
                "omitted, and the model is told so.",
                "当归档太长无法整体展示时追加——最早的行被省略，并明确告知模型。",
            ),
            f(
                "compile.groom.overview_heading",
                "Not read by the model but WRITTEN INTO canonical: the heading the card lands "
                "under in the document.",
                "不是给模型读的，而是写进正本：卡片在文档里落在哪个标题下。",
            ),
            f(
                "compile.groom.overview_point",
                "Also written into canonical: one point of the card, with the archived entries "
                "it stands for.",
                "同样写进正本：卡片里的一个要点，附上它所代表的归档条目。",
            ),
            f(
                "compile.groom.volumes_heading",
                "Written into canonical: the heading of the volume index left behind in the "
                "active document.",
                "写进正本：留在活动文档里的卷索引的标题。",
            ),
            f(
                "compile.groom.volume_entry",
                "Written into canonical: one line of that index, the link a reader follows into "
                "the frozen volume.",
                "写进正本：卷索引里的一行，读者顺着它进入冻结卷。",
            ),
            f(
                "compile.groom.commit_message",
                "The git commit message of a successful rollover — canonical's own history, so "
                "a deployment owns this wording too.",
                "一次成功归档的 git 提交信息——这是正本自己的历史，所以这段文案也归部署方所有。",
            ),
            f(
                "compile.groom.heal_commit_message",
                "The commit message of a link heal: the follow-up pass that re-renders links "
                "the move invalidated.",
                "链接修复的提交信息：那一趟后续修复重新渲染了被搬迁弄失效的链接。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="compile.overview",
        group="compile",
        title_en="The document overview — rendered region",
        title_zh="文档总览 — 区域渲染",
        summary_en=(
            "The overview is the bounded head a compile may rewrite whole: definition, "
            "summary, introduction, connections. These strings are not read by the model — "
            "they are WRITTEN INTO canonical as the region's headings and its connection "
            "lines, so they are prose a deployment owns. The region and its slots are "
            "delimited by system-written HTML comments, never by these headings, so "
            "translating one can never make an already-written document unreadable."
        ),
        summary_zh=(
            "总览是编译可以整体重写的那段有界头部：定义、现状、背景、关联。这些字符串不是给模型"
            "读的——它们作为区域的小标题和关联行**写进正本**，所以属于部署方自己的文案。区域和"
            "槽位由系统写的 HTML 注释界定，从不依赖这些标题，因此翻译其中一条永远不会让已经写好"
            "的文档变得读不出来。"
        ),
        segments=(
            f(
                "overview.heading.definition",
                "Written into canonical: the heading of the one sentence saying what or who "
                "this is.",
                "写进正本：那句「这是什么／是谁」所在的小标题。",
            ),
            f(
                "overview.heading.summary",
                "Written into canonical: the heading of the subject's state now.",
                "写进正本：主体当前状态那一节的小标题。",
            ),
            f(
                "overview.heading.introduction",
                "Written into canonical: the heading of background, origin and why it matters.",
                "写进正本：背景、由来与为什么重要那一节的小标题。",
            ),
            f(
                "overview.heading.connections",
                "Written into canonical: the heading of the links to other subject pages.",
                "写进正本：指向其他主体页面那一节的小标题。",
            ),
            f(
                "overview.connection_line",
                "Written into canonical: one connection — the link, and the relation in one "
                "line.",
                "写进正本：一条关联——链接，加上一行写清的关系。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    # ──────────────────────────────────────────────────────────────────── challenge
    Surface(
        id="challenge.questions",
        group="challenge",
        title_en="Blind question generation",
        title_zh="盲出问题",
        summary_en=(
            "The audit's first pass: it sees the raw material and the compile contract, "
            "deliberately NOT the compiled result, and asks what this material's future "
            "uses would need answered."
        ),
        summary_zh=(
            "审计的第一趟：它看到原始材料和编译契约，刻意看不到编译结果，"
            "然后问出这份材料未来的用途需要被回答的问题。"
        ),
        segments=(b("compile.challenge.questions_system"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "An assembly template: `{contract}` is where the deployment's own compile "
            "contract is substituted at call time, so the audit asks its questions under the "
            "same domain rules the compile ran under. The material itself arrives in the "
            "HumanMessage — and the compiled result deliberately never does."
        ),
        note_zh=(
            "这是装配模板：`{contract}` 处在调用时代入本部署自己的编译契约，"
            "使质询与编译在同一套领域规则下出题。材料随人类消息到达——"
            "而编译结果刻意永不到达。"
        ),
    ),
    Surface(
        id="challenge.reflect",
        group="challenge",
        title_en="Gap judgement",
        title_zh="缺口判定",
        summary_en=(
            "The audit's second pass: per question, the closest recorded claims against "
            "the material as ground truth. A gap exists only when the material supports "
            "an answer the claims do not carry."
        ),
        summary_zh=(
            "审计的第二趟：每个问题配上最接近的已记录断言，以材料为真值。"
            "只有当材料支持某个答案、而断言没有承载它时，才算缺口。"
        ),
        segments=(b("compile.challenge.reflect_system"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The SystemMessage only, and nothing is substituted into it. One question at a "
            "time, the closest recorded claims and the material "
            "they are judged against all arrive in the HumanMessage."
        ),
        note_zh=(
            "这里只有系统消息，而且没有任何东西被代入其中。"
            "每次一个问题、最接近的已记录断言、以及作为真值的材料，都随人类消息到达。"
        ),
    ),
    Surface(
        id="challenge.compensation",
        group="challenge",
        title_en="Compensation preamble",
        title_zh="补偿编译前言",
        summary_en=(
            "Confirmed gaps, handed to one extra compile over the same material. Its "
            "writes pass the ordinary citation gate like any other."
        ),
        summary_zh=(
            "确认的缺口，交给对同一份材料的一次额外编译。它的写入和其他写入一样要过"
            "普通的引用闸门。"
        ),
        segments=(b("compile.challenge.compensation_preamble"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "An assembly template, and only a preamble: `{gaps}` is where this audit's "
            "confirmed gaps are substituted, and the text then rides an ordinary compile "
            "round. So the model's actual message is the compile SystemMessage plus the "
            "compile human turn with this preamble in it — never this text on its own."
        ),
        note_zh=(
            "这是装配模板，而且只是一段前言：`{gaps}` 处代入本次质询确认的缺口，"
            "然后这段文字随一次普通编译回合发出。所以模型真正收到的是"
            "「编译系统消息 + 带这段前言的编译人类消息」，而不是这段文字本身。"
        ),
    ),
    Surface(
        id="compile.brief",
        group="compile",
        title_en="Post-compile brief",
        title_zh="编译简报",
        summary_en=(
            "One optional call after a committed compile narrates the mechanical claim "
            "events into a short brief for the History timeline. Its input is the record "
            "alone — never the compile conversation — and its output is labelled derived "
            "display copy, not knowledge."
        ),
        summary_zh=(
            "编译提交后可选的一次调用，把机械推导的断言事件叙述成一段简报，"
            "显示在 History 时间线上。它的输入只有这份记录——从不含编译对话——"
            "输出是标注为派生的展示文案，不是知识。"
        ),
        segments=(
            Segment(
                key="compile.brief.system",
                context_en=(
                    "The SystemMessage of the narration call, byte-stable: what the "
                    "brief may say and in which register."
                ),
                context_zh="叙述调用的系统消息，字节稳定：简报可以说什么、用什么口吻。",
            ),
            Segment(
                key="compile.brief.task",
                context_en=(
                    "The HumanMessage template: `{record}` is filled with the "
                    "mechanically rendered claim events and source provenance lines."
                ),
                context_zh=(
                    "人类消息模板：`{record}` 处代入机械渲染的断言事件与来源出处行。"
                ),
            ),
        ),
        kind=FRAGMENTS,
    ),
    # ─────────────────────────────────────────────────────────────────────── evolve
    Surface(
        id="evolve.phase1",
        group="evolve",
        title_en="Phase 1 — the schema draft",
        title_zh="第一阶段 — 结构草案",
        summary_en=(
            "A strong model proposes how the library's structure should change, on a "
            "branch, for a human to adopt or drop. Ships as a packaged asset; the key "
            "makes it replaceable through the same seam as everything else."
        ),
        summary_zh=(
            "强模型在分支上提出知识库结构该怎么变，等人来采纳或丢弃。"
            "它以打包资产的形式发布；这个键让它能走和其他文案一样的替换缝。"
        ),
        segments=(b("evolve.phase1_contract"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The SystemMessage as the model receives it — but not the library it reasons "
            "over. The full document list, the current path families and the basis for this "
            "evolve arrive in the HumanMessage (see 演进回合). `{slug}` here is not an "
            "injection point: it is part of a path template the model is meant to read "
            "literally."
        ),
        note_zh=(
            "这是模型收到的系统消息——但它据以推理的知识库不在这里。"
            "完整文档清单、当前路径家族与本次演进的依据随人类消息到达（见「演进回合」）。"
            "这里的 `{slug}` 不是注入点：它是路径模板的一部分，本来就要让模型逐字读到。"
        ),
    ),
    Surface(
        id="evolve.phase2",
        group="evolve",
        title_en="Phase 2 — whole-library reorganization",
        title_zh="第二阶段 — 全库重组",
        summary_en=(
            "The adopted draft executed claim by claim: claims move verbatim with their "
            "anchors, and the evolve gate refuses anything else."
        ),
        summary_zh=(
            "被采纳的草案被逐条断言执行：断言带着锚点原样搬迁，其余一切由演进闸门拒绝。"
        ),
        segments=(b("evolve.phase2_contract"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The SystemMessage as the model receives it. The adopted draft, every existing "
            "document and the newly added families are not in it — they arrive per round in "
            "the HumanMessage (see 演进回合)."
        ),
        note_zh=(
            "这是模型收到的系统消息。被采纳的草案、全部既有文档与新增家族都不在其中——"
            "它们每轮随人类消息到达（见「演进回合」）。"
        ),
    ),
    Surface(
        id="evolve.task",
        group="evolve",
        title_en="The evolve round (human turn)",
        title_zh="演进回合（人类消息）",
        summary_en=(
            "What one reorganization round is shown: every existing document, the basis "
            "for this evolve, and the newly added template families to file into."
        ),
        summary_zh=(
            "一次重组回合看到的东西：全部既有文档、本次演进的依据，以及新增的模板家族。"
        ),
        segments=(
            f(
                "evolve.task_header",
                "Opens the reorganization round.",
                "开出重组回合。",
            ),
            f(
                "evolve.task.docs_header",
                "Introduces the full document list — evolve sees all of canonical, not a "
                "retrieved slice of it.",
                "引出完整文档清单——演进看到的是全部正本，而不是检索出来的一部分。",
            ),
            f(
                "evolve.task.docs_empty",
                "Takes its place when there is nothing to reorganize yet.",
                "还没有任何东西可重组时取代上一条。",
            ),
            f(
                "evolve.task.rationale_header",
                "Introduces the adopted proposal: the basis this round is executing.",
                "引出被采纳的提案：本轮据以执行的依据。",
            ),
            f(
                "evolve.task.families_header",
                "Introduces the newly added path families, which is where moved meaning is "
                "meant to land.",
                "引出新增的路径家族——被搬迁的内容应该落到那里。",
            ),
            f(
                "evolve.task.families_empty",
                "Takes its place when the proposal added no new family.",
                "提案没有新增家族时取代上一条。",
            ),
            f(
                "evolve.recovery_heading",
                "Written INTO canonical, not read: the section a recovered claim is filed "
                "under when its original home is gone.",
                "写进正本而非被读取：当某条断言原本的归处已不存在时，它被安置在这个小节下。",
            ),
            f(
                "evolve.commit_message",
                "The git commit message of a completed evolve — canonical's own history.",
                "一次完成的演进的 git 提交信息——这是正本自己的历史。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="evolve.tools",
        group="evolve",
        title_en="Evolve tool face",
        title_zh="演进工具面",
        summary_en=(
            "The reorganization tools and their replies — including the one channel that "
            "exists nowhere else, `delete_claim`, and only for merging equivalent "
            "redundancy."
        ),
        summary_zh=(
            "重组用的工具及其回复——包括系统中别处都没有的那一条通道 `delete_claim`，"
            "而且只用于合并等价冗余。"
        ),
        segments=(
            f(
                "evolve.tool.list_documents",
                "The description of `list_documents` in the tool list, every round.",
                "工具清单里 `list_documents` 的描述，每轮都在。",
            ),
            f(
                "evolve.tool.read_document",
                "The description of `read_document` in the tool list, every round.",
                "工具清单里 `read_document` 的描述，每轮都在。",
            ),
            f(
                "evolve.tool.create_document",
                "The description of `create_document` — the new homes a reorganization files "
                "into have to be created first, and the system derives their title.",
                "`create_document` 的描述——重组要归入的新归处必须先被创建出来，它们的 title "
                "由系统派生。",
            ),
            f(
                "evolve.tool.move_claim",
                "The description of `move_claim`, the tool this whole lane exists for: the "
                "claim moves verbatim, anchor unchanged.",
                "`move_claim` 的描述，整条车道正是为它而存在：断言原样搬迁，锚点不变。",
            ),
            f(
                "evolve.tool.edit_claim",
                "The description of `edit_claim`: rewrite one claim in place, anchor preserved.",
                "`edit_claim` 的描述：就地重写一条断言，锚点保持不变。",
            ),
            f(
                "evolve.tool.append_block",
                "The description of `append_block`: add one claim, anchor assigned by the "
                "system.",
                "`append_block` 的描述：新增一条断言，锚点由系统分配。",
            ),
            f(
                "evolve.tool.delete_claim",
                "The description of `delete_claim` — the only deletion channel in the system, "
                "and it says out loud that it is for merging equivalents only.",
                "`delete_claim` 的描述——系统中唯一的删除通道，而且它明说只用于合并等价内容。",
            ),
            f(
                "evolve.tool.search_knowledge",
                "The description of `search_knowledge`, present only when a retrieval port is "
                "wired.",
                "`search_knowledge` 的描述，只有接上了检索端口时才出现。",
            ),
            f(
                "evolve.tool.fetch_source",
                "The description of `fetch_source`: the L0 route for checking a citation "
                "before moving the claim that carries it.",
                "`fetch_source` 的描述：搬迁一条断言之前，用来核对它的引用的 L0 通道。",
            ),
            f(
                "evolve.tool.finish_evolve",
                "The description of `finish_evolve` — the call that submits the round to the "
                "evolve gate.",
                "`finish_evolve` 的描述——正是这次调用把本轮提交给演进闸门。",
            ),
            f(
                "evolve.tool.search_unavailable",
                "Takes the search description's place when no retrieval port is wired.",
                "没有接检索端口时，取代检索工具的描述。",
            ),
            f(
                "evolve.tool.fetch_unavailable",
                "Takes the fetch description's place when no source-text port is wired.",
                "没有接原文端口时，取代取原文工具的描述。",
            ),
            f(
                "evolve.tool.list_documents_empty",
                "The `list_documents` reply when there are no documents.",
                "没有任何文档时，`list_documents` 的回复。",
            ),
            f(
                "evolve.tool.create_document_result",
                "The `create_document` reply: the path, and the system-assigned anchors.",
                "`create_document` 的回复：路径，以及系统分配的锚点。",
            ),
            f(
                "evolve.tool.move_claim_result",
                "The `move_claim` reply, confirming the anchor moved verbatim with the claim.",
                "`move_claim` 的回复，确认锚点随断言原样搬走。",
            ),
            f(
                "evolve.tool.edit_claim_result",
                "The `edit_claim` reply, confirming the anchor survived the rewrite.",
                "`edit_claim` 的回复，确认重写后锚点仍然保留。",
            ),
            f(
                "evolve.tool.append_block_result",
                "The `append_block` reply, naming the anchor the system assigned.",
                "`append_block` 的回复，点明系统分配的锚点。",
            ),
            f(
                "evolve.tool.delete_claim_result",
                "The `delete_claim` reply — it states that the anchor enters the dropped list, "
                "so the deletion stays traceable.",
                "`delete_claim` 的回复——它说明锚点会进入「消失锚点清单」，让这次删除仍然可追溯。",
            ),
            f(
                "evolve.tool.finish_evolve_result",
                "The `finish_evolve` reply, once the evolve gate accepted the round.",
                "演进闸门接受本轮后，`finish_evolve` 的回复。",
            ),
            f(
                "evolve.tool.anchors_none",
                "Stands in for an empty anchor list inside those replies.",
                "在上面那些回复里，代替空的锚点列表。",
            ),
            f(
                "evolve.tool.unknown_tool",
                "The reply to a call naming a tool that does not exist.",
                "当调用了一个并不存在的工具时的回复。",
            ),
            f(
                "evolve.tool.call_failed",
                "The reply when a tool call raised.",
                "工具调用抛错时的回复。",
            ),
            f(
                "evolve.service.fetch_failed",
                "Returned in place of source text when the L0 fetch itself failed.",
                "L0 取原文本身失败时，取代原文返回。",
            ),
            f(
                "evolve.service.search_empty",
                "Returned when a query matched no raw fragment.",
                "查询没有命中任何原始片段时返回。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="evolve.propose",
        group="evolve",
        title_en="Evolve proposal input",
        title_zh="演进提案输入",
        summary_en=(
            "What the proposal pass reads: the current composed contract, the path "
            "families, the compile events since the last evolve, and the document list."
        ),
        summary_zh=(
            "提案那一趟读到的东西：当前组合出的契约、路径家族、"
            "距上次演进以来的编译事件，以及文档清单。"
        ),
        segments=(
            f(
                "evolve.propose.skill_header",
                "Introduces the contract as it currently composes — a proposal has to start "
                "from the structure actually in force.",
                "引出当前组合出的契约——提案必须从真正生效的结构出发。",
            ),
            f(
                "evolve.propose.templates_header",
                "Introduces the path families in force, the ownership rules a new structure "
                "has to respect.",
                "引出当前生效的路径家族：新结构必须遵守的归属规则。",
            ),
            f(
                "evolve.propose.events_header",
                "Introduces what compiling has been doing since the last evolve — where the "
                "pressure to reorganize comes from.",
                "引出上次演进以来编译都做了什么——重组的压力正是从这里来的。",
            ),
            f(
                "evolve.propose.events_empty",
                "Takes its place when nothing has been compiled since the last evolve.",
                "上次演进以来没有任何编译时取代上一条。",
            ),
            f(
                "evolve.propose.event_line",
                "One line of that record, once per document touched.",
                "那份记录里的一行，每份被改动过的文档一次。",
            ),
            f(
                "evolve.propose.unknown_path",
                "Stands in on such a line when the event carries no resolvable path.",
                "当某个事件没有可解析的路径时，在那一行里代替路径。",
            ),
            f(
                "evolve.propose.docs_header",
                "Introduces the current document list.",
                "引出当前的文档清单。",
            ),
            f(
                "evolve.propose.docs_empty",
                "Takes its place when the knowledge base holds no documents.",
                "知识库里没有文档时取代上一条。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    # ─────────────────────────────────────────────────────────────────────── recall
    Surface(
        id="recall.fast",
        group="recall",
        title_en="Fast recall contract",
        title_zh="快速召回契约",
        summary_en=(
            "The everyday answering lane's System contract: head + the shared spine (with "
            "source-level citation and the honest close) + the deployment's answer style."
        ),
        summary_zh=(
            "日常回答车道的系统契约：开头 + 共享脊柱（源级引用 + 诚实收尾）+ 部署选定的回答风格。"
        ),
        segments=(
            b("recall.fast.contract_head"),
            *_spine("recall.cite.source_level", "recall.close.answer_honestly"),
            *_ANSWER_STYLE,
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of a template, not the whole call. The style clause at the end is "
            "chosen by this deployment's `answer_style` — `conversational` is rendered here, "
            "and the two alternatives below take its place instead; exactly one is ever "
            "appended. The question, the `as_of` date, the owner profile and the retrieved "
            "evidence are not part of the contract at all: they arrive in the HumanMessage "
            "(see 证据分节), which is what keeps this message byte-stable — invariant I5."
        ),
        note_zh=(
            "这是模板的一次取值，不是一整次调用。末尾的风格段由本部署的 `answer_style` 选定"
            "——这里渲染的是 `conversational`，下面两条替代项会取代它；每次只会附上其中一条。"
            "问题、`as_of` 日期、主人档案与召回到的证据都不属于契约：它们随人类消息到达"
            "（见「证据分节」）；正是这一点让这条消息逐字节稳定——不变量 I5。"
        ),
    ),
    Surface(
        id="recall.fast_structured",
        group="recall",
        title_en="Structured fast answer contract",
        title_zh="结构化快速回答契约",
        summary_en=(
            "The fast answer contract when answer text, answer kind and citations travel "
            "as separate schema fields, allowing exact evidence-span validation."
        ),
        summary_zh=(
            "回答正文、回答类型和引用分别通过 schema 字段传递时使用的快速回答契约，"
            "使精确证据区间可以被机械验证。"
        ),
        segments=(
            b("recall.fast.contract_head"),
            *_spine("recall.cite.structured", "recall.close.answer_honestly"),
            *_ANSWER_STYLE,
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of the structured-answer template. Exactly one answer-style "
            "clause is appended. Question, clock and evidence still arrive in the HumanMessage; "
            "only the response wire and citation clause differ from Fast recall contract."
        ),
        note_zh=(
            "这是结构化回答模板的一次取值，每次只附上一条回答风格。问题、时钟与证据仍随"
            "人类消息到达；与「快速召回契约」不同的只有响应线格式和引用条款。"
        ),
    ),
    Surface(
        id="recall.fast_deliberated",
        group="recall",
        title_en="Deliberated fast answer contract",
        title_zh="带思考的快速回答契约",
        summary_en=(
            "The structured contract plus one clause, used by the `all` evidence strategy: "
            "its schema opens with a deliberation field, so the contract asks for the "
            "evidence review that no selection call performed."
        ),
        summary_zh=(
            "结构化契约再加一段，供 `all` 证据编排使用：它的 schema 以一个 deliberation "
            "字段开头，因此契约要求模型给出那次没有选择调用来做的证据审视。"
        ),
        segments=(
            b("recall.fast.contract_head"),
            *_spine("recall.cite.structured", "recall.close.answer_honestly"),
            *_ANSWER_STYLE,
            b("recall.fast.deliberation"),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of the same structured template, with the deliberation clause "
            "appended last. Exactly one answer-style clause is appended before it, and the "
            "question, clock and evidence still arrive in the HumanMessage — the review the "
            "clause asks for is model output, never part of this message."
        ),
        note_zh=(
            "同一个结构化模板的一次取值，末尾多附一段思考条款。它前面仍然只附一条回答风格，"
            "问题、时钟与证据也仍随人类消息到达——条款所要的那段审视是模型的输出，"
            "从不属于这条消息。"
        ),
    ),
    Surface(
        id="recall.deep",
        group="recall",
        title_en="Deep verification contract",
        title_zh="深度校验契约",
        summary_en=(
            "The agentic lane's System contract: the same spine, but citing down to the "
            "block span, because deep can and must check a conclusion against the original."
        ),
        summary_zh=(
            "代理式车道的系统契约：同一条脊柱，但要求引到块区间——"
            "因为深度召回能够、也必须拿结论去比对原文。"
        ),
        segments=(
            b("recall.deep.contract_head"),
            *_spine("recall.cite.precise", "recall.close.answer_honestly"),
            *_ANSWER_STYLE,
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of a template, not the whole call. The style clause at the end "
            "follows this deployment's `answer_style` (`conversational` rendered here; "
            "exactly one of the three is ever appended). The question and the starting "
            "evidence arrive in the HumanMessage, and the three search tools reach the model "
            "as tool schemas rather than as prose in this contract (see 深度召回工具面)."
        ),
        note_zh=(
            "这是模板的一次取值，不是一整次调用。末尾的风格段跟随本部署的 `answer_style`"
            "（这里渲染的是 `conversational`；三条里每次只附上一条）。问题与起始证据随人类消息"
            "到达；三个检索工具是以工具 schema 的形式到达模型的，而不是作为这份契约里的文字"
            "（见「深度召回工具面」）。"
        ),
    ),
    Surface(
        id="recall.briefing",
        group="recall",
        title_en="Briefing session contract",
        title_zh="简报会话契约",
        summary_en=(
            "A continuous session built around one fixed knowledge pack, with two routes "
            "out of it: search within the pack's range, and verbatim L0 fetch."
        ),
        summary_zh=(
            "围绕一个固定知识包构建的持续会话，并留了两条出口："
            "在包的范围内再检索，以及 L0 逐字取原文。"
        ),
        segments=(
            b("recall.briefing.contract_head"),
            *_spine("recall.cite.precise", "recall.close.answer_honestly"),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The FIXED half of the session's SystemMessage — this is the part that is "
            "byte-stable. At session build time the knowledge pack is appended after it, and "
            "the pack changes with the scope and the snapshot; each ask's question then "
            "arrives in the HumanMessage. So a real briefing call is this text plus a pack "
            "that is not shown here (see 简报知识包与工具)."
        ),
        note_zh=(
            "这是会话系统消息里**固定的那一半**——逐字节稳定的部分就是它。"
            "会话构建时，知识包会被接在它后面，而包会随范围与快照变化；"
            "每次提问的问题再随人类消息到达。所以一次真实的简报调用是"
            "「这段文字 + 这里没有展示的知识包」（见「简报知识包与工具」）。"
        ),
    ),
    Surface(
        id="recall.suggestion",
        group="recall",
        title_en="Live-context contract",
        title_zh="实时上下文契约",
        summary_en=(
            "The listening mode: nobody asked a question, so the spine's closing clause "
            "is the one that says an empty list is this interface's normal return value."
        ),
        summary_zh=(
            "旁听模式：没有人在提问，所以脊柱的收尾条款换成了"
            "「空列表就是这个接口的正常返回值」的那一条。"
        ),
        segments=(
            b(
                "recall.suggestion.contract_head",
                slots=(Slot("focus", ("recall.suggestion.focus.general",)),),
            ),
            s("recall.suggestion.focus.general"),
            v(
                "recall.suggestion.focus.owner",
                "Fills the focus slot instead when the caller scopes this round to the owner's "
                "own contributions.",
                "当调用方把这一轮的注意范围限定为主人自己的输入时，改由它填注意范围插槽。",
            ),
            v(
                "recall.suggestion.focus.other",
                "Fills the focus slot instead when the caller scopes this round to the other "
                "participants.",
                "当调用方把这一轮的注意范围限定为其他参与者时，改由它填注意范围插槽。",
            ),
            *_spine("recall.cite.precise", "recall.close.suggestion"),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of a template. The head's focus slot is filled per call: the "
            "general phrasing is rendered here, and the two alternatives below take its place "
            "when the round is scoped to the owner's own turns or to the other participants. "
            "The live transcript window arrives in the HumanMessage."
        ),
        note_zh=(
            "这是模板的一次取值。开头的注意范围插槽按调用填充：这里渲染的是通用说法，"
            "当这一轮被限定为主人自己的发言、或其他参与者时，下面两条替代项会取代它。"
            "实时转写窗口随人类消息到达。"
        ),
    ),
    Surface(
        id="recall.live_discover",
        group="recall",
        title_en="Live-context discover contract",
        title_zh="实时上下文·发现契约",
        summary_en=(
            "The first of the full-scope lane's two calls, and the one that decides whether "
            "anything is retrieved at all. Its whole job is ONE SENTENCE: the question most "
            "worth asking on the room's behalf right now. Everything else follows from that "
            "— the `intent` field IS that question (phrased askable, because the owner reads "
            "it as the reason a card appeared), the plan is how you would go and answer it, "
            "the worth is what the answer would be worth, and a skip is simply the case "
            "where no question worth asking can be written. The clause set that grew case by "
            "case over the lane's first days — unnamed roles, first-mention nouns, "
            "find-a-person asks, the common-ground rule — collapsed into examples of that "
            "one principle, which is why this surface is SHORTER than the accretion it "
            "replaces. One steer survives as a rule and not an example: a question about WHO "
            "is aimed at the people AROUND the subject, never at a definition of it, because "
            "the conversation asking who could present X is otherwise answered with what X "
            "is."
        ),
        summary_zh=(
            "全量车道两次调用中的第一次，也是决定「到底要不要检索」的那一次。"
            "它整件事就是**一句话**：此刻替这屋里的人问出来、最值得问的那一个问题。"
            "其余一切都由它推出来——`intent` 字段**就是**那个问题（照能亲口问出的样子写，"
            "因为主体把这一行读作「卡片为什么出现」），计划是「你会怎么去答它」，"
            "价值分是「这个答案值多少」，而跳过不过是「写不出一个值得问的问题」这种情形。"
            "车道头几天里一条一条长出来的判例——没点名的角色、第一次出现的名词、找人类需求、"
            "共识规则——都收成了这一条原则的例子，这也正是这份表面比它取代的那堆累积**更短**"
            "的原因。只有一条转向仍是规则而非例子：问「谁」的问题瞄的是主题**周围的人**，"
            "而不是主题的定义——否则一句「谁能来讲 X」换回来的会是「X 是什么」。"
        ),
        segments=(
            b(
                "recall.live.discover.contract",
                slots=(
                    Slot("kinds", ("recall.live.discover.semantic_offer",)),
                    Slot("mining", ("recall.live.discover.mining.balanced",)),
                    Slot("focus", ("recall.suggestion.focus.general",)),
                ),
            ),
            s("recall.live.discover.semantic_offer"),
            s("recall.live.discover.mining.balanced"),
            s("recall.suggestion.focus.general"),
            v(
                "recall.live.discover.mining.eager",
                "Fills the latency slot instead on the EAGER density: the question may be "
                "one the room does not yet realise it should ask — an unfamiliar term nobody "
                "stopped to explain, a role standing in for a person nobody named. It widens "
                "first-mention curiosity only; the already-mined rule above it is untouched.",
                "在**积极**密度下改由它填「问题可以有多隐」插槽：可以隐到屋里的人自己还没意识到"
                "该问——没人停下来解释的说法、替代无名者的角色。它只放宽首次提及时的好奇心，"
                "上面的 already_mined 一条不动。",
            ),
            v(
                "recall.live.discover.mining.quiet",
                "…and on the QUIET density: the question may not be latent at all — only one "
                "somebody actually asked aloud, or an explicit request for information.",
                "在**安静**密度下则改由它填：那个问题一点都不能是隐的——只有有人真的问出口的"
                "问题，或明确的要资料。",
            ),
            v(
                "recall.live.discover.path_offer",
                "One line per component retrieval path this deployment enables, rendered into "
                "the plan-kinds slot ABOVE the semantic one. With no component registered the "
                "slot holds the semantic line alone, which is what is shown here.",
                "本部署每启用一条组件查询路，就在计划种类插槽里、语义那条之上多渲染一行。"
                "没有注册任何组件时，插槽里就只有语义那一条——这里展示的正是这种情况。",
            ),
            v(
                "recall.suggestion.focus.owner",
                "Fills the attention slot instead when the round is scoped to the owner's own "
                "contributions.",
                "当这一轮的注意范围被限定为主人自己的输入时，改由它填注意范围插槽。",
            ),
            v(
                "recall.suggestion.focus.other",
                "Fills the attention slot instead when the round is scoped to the other "
                "participants.",
                "当这一轮的注意范围被限定为其他参与者时，改由它填注意范围插槽。",
            ),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of a template, for a deployment with no index component enabled. "
            "The pending transcript, the cards already surfaced this conversation and the "
            "subject ledger's digest all arrive in the HumanMessage (see 实时上下文流水线输入)."
        ),
        note_zh=(
            "这是模板的一次取值，取的是「没有启用任何索引组件、且没有开启互联网搜索」的部署。"
            "待处理的转写、本场已推送过的卡片、以及主体台账的摘要，都随人类消息到达"
            "（见「实时上下文流水线输入」）。开启互联网搜索后，模型收到的是下面那一份。"
        ),
    ),
    Surface(
        id="recall.live_discover_web",
        group="recall",
        title_en="Live-context discover contract · with internet search",
        title_zh="实时上下文·发现契约（含互联网搜索）",
        summary_en=(
            "The same contract, assembled for a deployment that allows a supplementary "
            "internet search AND a connection that turned it on. Both conditions, not "
            "either: the offer costs the small model attention, so a lookup kind nothing "
            "could serve is never advertised. One line longer than the variant above — that "
            "line is the entire difference, and both are byte-pinned so it stays so. The "
            "line also says where the query goes when an ask mixes an internal need with an "
            "outside subject (who could present X, X being a public product): to X itself, "
            "while the library lookups take the person half."
        ),
        summary_zh=(
            "同一份契约，装配给「部署允许互联网搜索、且这条连接也打开了它」的情形。"
            "两个条件缺一不可：这个提议要花掉小模型的注意力，所以没人能服务的查询种类"
            "绝不advertise。它只比上面那一份多一行——那一行就是全部差异，"
            "两份都做了逐字节钉死，好让它一直只是那一行。"
        ),
        segments=(
            b(
                "recall.live.discover.contract",
                slots=(
                    Slot(
                        "kinds",
                        (
                            "recall.live.discover.semantic_offer",
                            "recall.live.discover.web_offer",
                        ),
                        join="\n",
                    ),
                    Slot("mining", ("recall.live.discover.mining.balanced",)),
                    Slot("focus", ("recall.suggestion.focus.general",)),
                ),
            ),
            s("recall.live.discover.semantic_offer"),
            s("recall.live.discover.web_offer"),
            s("recall.live.discover.mining.balanced"),
            s("recall.suggestion.focus.general"),
            v(
                "recall.live.discover.path_offer",
                "One line per component retrieval path this deployment enables, rendered into "
                "the plan-kinds slot ABOVE the semantic and web lines. With no component "
                "registered the slot holds those two alone, which is what is shown here.",
                "本部署每启用一条组件查询路，就在计划种类插槽里、语义与互联网那两行之上多渲染"
                "一行。没有注册任何组件时，插槽里就只有那两行——这里展示的正是这种情况。",
            ),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of a template, for a deployment with no index component enabled "
            "and the supplementary internet search allowed. Compare it against the variant "
            "above: the `web` line is the only thing that moves, and the toggle that adds it "
            "never reaches the HumanMessage — which is what keeps I5 true across both."
        ),
        note_zh=(
            "这是模板的一次取值，取的是「没有启用任何索引组件、但允许互联网搜索」的部署。"
            "与上面那一份对照着看：动的只有 `web` 那一行，而打开它的开关从不进入人类消息"
            "——这正是 I5 在两份之间都成立的原因。"
        ),
    ),
    Surface(
        id="recall.live_discover_eager",
        group="recall",
        title_en="Live-context discover contract · eager",
        title_zh="实时上下文·发现契约（积极）",
        summary_en=(
            "The same contract on the EAGER density. One clause differs — HOW LATENT the "
            "question may be — and it is the clause the presets could never reach by moving "
            "numbers: the question may be one the room has not yet realised it should ask, so a "
            "role standing in for an unnamed person, or a business noun on its first mention, is "
            "enough to write one."
        ),
        summary_zh=(
            "同一份契约，取**积极**密度。差别只有一处——那个问题可以有多**隐**——而这恰恰是靠调数字"
            "永远够不到的那一处：问题可以隐到屋里的人自己还没意识到该问，于是替代无名者的角色、"
            "第一次出现的业务名词，都足以让它写出一个问题来。"
        ),
        segments=(
            b(
                "recall.live.discover.contract",
                slots=(
                    Slot("kinds", ("recall.live.discover.semantic_offer",)),
                    Slot("mining", ("recall.live.discover.mining.eager",)),
                    Slot("focus", ("recall.suggestion.focus.general",)),
                ),
            ),
            s("recall.live.discover.semantic_offer"),
            s("recall.live.discover.mining.eager"),
            s("recall.suggestion.focus.general"),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of a template, on the eager density with no index component and no "
            "internet search. Pinned beside the balanced and quiet ones because the three are one "
            "contract in three wordings, and a pin on only the middle one would let the other two "
            "drift into contracts of their own."
        ),
        note_zh=(
            "这是模板的一次取值：积极密度，没有索引组件，没有互联网搜索。它与均衡、安静那两份并排"
            "钉死，因为三者是一份契约的三种说法；只钉中间那一份，另外两份就会各自漂成独立的契约。"
        ),
    ),
    Surface(
        id="recall.live_discover_quiet",
        group="recall",
        title_en="Live-context discover contract · quiet",
        title_zh="实时上下文·发现契约（安静）",
        summary_en=(
            "The same contract on the QUIET density: the question may not be latent at all — only "
            "one somebody actually asked aloud, or an explicit request for information. A gap "
            "nobody named is not a question, and neither is one only the person in the room "
            "could answer."
        ),
        summary_zh=(
            "同一份契约，取**安静**密度：那个问题一点都不能是隐的——只有有人真的问出口的问题、"
            "或明确的要资料。没人点破的缺口不算一个问题；只有当事人自己才答得了的，也不算。"
        ),
        segments=(
            b(
                "recall.live.discover.contract",
                slots=(
                    Slot("kinds", ("recall.live.discover.semantic_offer",)),
                    Slot("mining", ("recall.live.discover.mining.quiet",)),
                    Slot("focus", ("recall.suggestion.focus.general",)),
                ),
            ),
            s("recall.live.discover.semantic_offer"),
            s("recall.live.discover.mining.quiet"),
            s("recall.suggestion.focus.general"),
        ),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "One resolution of a template, on the quiet density with no index component and no "
            "internet search."
        ),
        note_zh=(
            "这是模板的一次取值：安静密度，没有索引组件，没有互联网搜索。"
        ),
    ),
    Surface(
        id="recall.live_pick",
        group="recall",
        title_en="Live-context pick contract",
        title_zh="实时上下文·挑选契约",
        summary_en=(
            "The second call, and it has exactly ONE criterion: does this candidate's own "
            "text ANSWER the question discover wrote? Choose the candidate that does, or 0. "
            "Everything else on this surface is that criterion applied — the lede answers "
            "the question in the room's language, never extends past the text, and stays on "
            "the candidate's OWN subject as its title and `about:` line state it, "
            "`confidence` scores how directly the text answers it (not the candidate's "
            "quality), and four consequences are spelled out because each one was a live "
            "failure: text that says it CANNOT answer answers nothing and loses to 0; "
            "adjacency — sharing a word, being the closest internal project — is not an "
            "answer; a nearest-fit recommendation IS an answer to a who-could question "
            "provided the inference is marked; and which pool a candidate came out of is not "
            "a ranking. Naming the one criterion is what let the four collapse from rules "
            "into consequences, which is why this surface is shorter than the version that "
            "accumulated them."
        ),
        summary_zh=(
            "第二次调用，而它只有**一条**标准：这张候选自己的文本，回答了发现阶段写下的那个"
            "问题吗？回答了的就选它，一张都没有就填 0。这份表面上的其余一切都是这条标准的推论"
            "——引言用屋里自己的话回答那个问题、绝不越出文本一步、也不离开候选自己的主体"
            "（以它的标题与「出自」那一行为准），`confidence` 打的是那段文本"
            "有多直接地回答了它（不是候选的质量），而四条推论逐条写明，因为每一条都曾是线上"
            "真实翻车：文本自己说「答不上来」就什么都没回答，宁可填 0；沾边——共用一个词、"
            "只是库里最近的那个内部项目——不是回答；面对「谁能做这件事」，标明了推断的近邻推荐"
            "**是**回答；候选出自哪个池子不构成优先级。正因为把那条唯一标准点了出来，这四条才"
            "能从并列的规则收成推论——这也是这份表面比累积出它的那一版更短的原因。"
        ),
        segments=(b("recall.live.pick.contract"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The SystemMessage only, with nothing substituted into it. The numbered candidates "
            "and the live conversation are the HumanMessage."
        ),
        note_zh="这里只有系统消息，且没有任何东西被代入。编好号的候选与当前对话构成人类消息。",
    ),
    Surface(
        id="recall.live_pipeline_input",
        group="recall",
        title_en="Live-context pipeline input",
        title_zh="实时上下文流水线输入",
        summary_en=(
            "The two Human turns of the full-scope lane, section by section. Everything "
            "volatile lives here — the pending window, what has already been surfaced, the "
            "subject ledger, the candidates — so both SystemMessages stay byte-stable (I5)."
        ),
        summary_zh=(
            "全量车道两次调用的人类消息，逐节列出。所有易变的东西都在这里——待处理窗口、"
            "已推送过的内容、主体台账、候选卡片——好让两份系统消息都保持逐字节稳定（I5）。"
        ),
        segments=(
            f(
                "recall.live.section.mined_header",
                "Introduces the cards already surfaced this conversation, so the discover "
                "stage can answer `already_mined` on evidence rather than on memory.",
                "引出本场已经推送过的卡片，好让发现阶段的 `already_mined` 有据可依，"
                "而不是凭记忆。",
            ),
            f(
                "recall.live.section.digest_header",
                "Introduces the subject ledger's digest: what this conversation keeps "
                "returning to, how often, and whether anyone ever asked about it.",
                "引出主体台账的摘要：本场反复回到什么、回到多少次、以及有没有人真的追问过。",
            ),
            f(
                "recall.live.digest.line",
                "One ledger subject. `{state}` and `{asked}` are filled by the four words "
                "below.",
                "台账里的一个主体。`{state}` 与 `{asked}` 由下面四个词填充。",
            ),
            f(
                "recall.live.digest.introduced",
                "Fills `{state}` when a card about this subject has already been delivered.",
                "当这个主体已经推送过卡片时，填入 `{state}`。",
            ),
            f(
                "recall.live.digest.new",
                "Fills `{state}` when no card about this subject has been delivered yet.",
                "当这个主体还没有推送过卡片时，填入 `{state}`。",
            ),
            f(
                "recall.live.digest.asked",
                "Fills `{asked}` when the pending window that touched this subject was "
                "question-shaped.",
                "当触及这个主体的待处理窗口带有疑问句形态时，填入 `{asked}`。",
            ),
            f(
                "recall.live.digest.unasked",
                "Fills `{asked}` otherwise — the common-ground case the contract asks the "
                "model to skip on.",
                "否则填入 `{asked}`——也就是契约要求模型据以跳过的「共识」那一种情形。",
            ),
            f(
                "recall.live.section.context_header",
                "Introduces the READ-ONLY tail of already-processed turns, above the new "
                "content. It is what the new content refers back to — a pronoun, a product "
                "named three turns ago — and the contract forbids mining it.",
                "在新内容上方引出**只读**的已处理轮次尾巴。新内容里的指代——代词，或者三轮前"
                "提到的那个产品——要靠它才读得懂；契约明令不得去挖这一段。",
            ),
            f(
                "recall.live.section.pending_header",
                "Introduces the pending transcript window, always LAST in the discover turn.",
                "引出待处理的转写窗口，它在发现那一轮里永远排在最后。",
            ),
            f(
                "recall.live.section.pending_overflow",
                "Appended to that header when the pending run was longer than the window "
                "bound, stating how many earlier turns did not fit.",
                "当待处理的轮次超过窗口上限时接在该标题后，说明有多少更早的轮次没能放下。",
            ),
            f(
                "recall.live.section.candidates_header",
                "Introduces the numbered candidates in the pick turn.",
                "在挑选那一轮里引出编好号的候选。",
            ),
            f(
                "recall.live.candidate.block",
                "One candidate, rendered mechanically: number, kind, title, verbatim evidence, "
                "and its own citation list.",
                "一张候选，机械渲染：编号、类型、标题、逐字证据，以及它自带的引用清单。",
            ),
            f(
                "recall.live.candidate.citation",
                "One numbered citation inside a candidate — the index the pick stage copies "
                "from when it prunes.",
                "候选内部编好号的一条引用——挑选阶段裁剪时照抄的就是这个编号。",
            ),
            f(
                "recall.live.candidate.provenance_library",
                "Fills a candidate's `source` line for every card built out of the owner's "
                "own material. The pick contract's source-blind rule — where a candidate "
                "came from is not a ranking, the match is — needs the pool stated rather "
                "than guessed at, and this is where it is stated.",
                "凡是用知识主体自己的材料装配出来的候选，都用它填「来源」那一行。"
                "挑选契约里那条「来源不是优先级，匹配度才是」的规则，前提是把池子写明、"
                "而不是让模型去猜——写明它的地方就是这里。",
            ),
            f(
                "recall.live.candidate.provenance_web",
                "Fills the same line for a card built out of a live internet search.",
                "同一行，填给用互联网实时搜索装配出来的候选。",
            ),
            f(
                "recall.live.candidate.web_citation",
                "Takes that list's place inside a `web` candidate — a page title and its URL "
                "rather than a source id and a block span, numbered the same way so the pick "
                "stage prunes by index exactly as it does for a library card.",
                "在 `web` 候选内部取代那份清单——给的是页面标题与网址，而不是来源 id 与块区间；"
                "编号方式相同，好让挑选阶段像裁剪知识库卡片那样按编号裁剪。",
            ),
            f(
                "recall.live.candidate.no_citations",
                "Takes that list's place for a candidate carrying no citation at all.",
                "当一张候选完全没有引用时，取代那份清单。",
            ),
            f(
                "recall.live.candidate.excerpt",
                "One raw excerpt line inside a candidate's evidence.",
                "候选证据里的一行原文摘录。",
            ),
            f(
                "recall.identity.volume_title",
                "Names a candidate built out of a FROZEN ROLLOVER VOLUME after the active "
                "document the volume is history of, with the volume itself noted. A volume's "
                "own filename is `a02` and its body carries no title, so without this the "
                "pick stage is shown a card whose subject is unknowable from anything on it.",
                "凡是用**冻结的归档卷**装配出来的候选，都用它来命名：取那一卷所归属的活动文档的"
                "标题，并注明是哪一卷。归档卷自己的文件名就是 `a02`、正文里也没有标题，"
                "少了这一步，挑选阶段拿到的就是一张从任何字面都看不出主体的卡。",
            ),
            f(
                "recall.identity.volume_origin",
                "Opens that candidate's orientation line: the parent document's title and "
                "the path it is filed at, so the identity is followable and not merely "
                "asserted.",
                "起头那张候选的定位行：父文档的标题与它归档的路径——好让这个身份是可追的，"
                "而不只是被声称的。",
            ),
            f(
                "recall.identity.joined",
                "Joins that head to what the page says it is — its overview definition, or "
                "the head of its own ledger when it has no definition.",
                "把那个开头与这一页对自己的说法接起来——概览里的 definition，"
                "没有 definition 时则是它自己账本的头几条。",
            ),
            f(
                "recall.live.card.about",
                "The same orientation line, carried into the DELIVERED card's evidence "
                "block: a reader expanding the card sees whose material it is before "
                "reading a word of it.",
                "同一行定位，带进**已交付卡片**的证据区：读者展开卡片时，"
                "先看到这是谁的材料，再读它的内容。",
            ),
            f(
                "recall.live.section.intent",
                "Carries the discover stage's own intent sentence into the pick turn.",
                "把发现阶段自己那句意图带进挑选那一轮。",
            ),
            f(
                "recall.live.section.conversation_header",
                "Introduces the live conversation in the pick turn — last, in the "
                "attention-hot tail.",
                "在挑选那一轮里引出当前对话——排在最后，落在注意力最热的尾部。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.live_web_search",
        group="recall",
        title_en="Live-context supplementary web search",
        title_zh="实时上下文·补充互联网搜索",
        summary_en=(
            "The one sentence the supplementary search provider is given, when a deployment "
            "allows the internet as a supplement AND a connection turned it on. It goes to "
            "a THIRD model — not the discover call and not the pick call — and what comes "
            "back becomes one candidate in the same numbered pool as the library's, cited "
            "to the pages it read."
        ),
        summary_zh=(
            "当部署允许把互联网作为补充、且这条连接也打开了它时，交给搜索服务商的那一句话。"
            "它发给的是**第三个**模型——既不是发现调用，也不是挑选调用——回来的东西会成为"
            "候选池里的一张候选，与知识库的候选同池编号，并引用它读过的网页。"
        ),
        segments=(
            f(
                "recall.live.web.instruction",
                "The whole input of one supplementary search. `{question}` is the query the "
                "discover stage planned, or — on the fallback tier — the intent itself, "
                "after the library came back with no candidate at all.",
                "一次补充搜索的全部输入。`{question}` 是发现阶段规划的那条查询；"
                "若走的是兜底那一档，则是意图本身——那是在知识库一张候选都没给出之后。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.suggestion_detail",
        group="recall",
        title_en="Card expansion contract",
        title_zh="卡片展开契约",
        summary_en=(
            "The owner tapped one card. Deliberately NOT built on the spine: there is no "
            "wide recall here, only the card and the verbatim source text it cites."
        ),
        summary_zh=(
            "主人点开了一张卡片。刻意不建立在脊柱之上：这里没有宽召回，"
            "只有这张卡片和它引用的逐字原文。"
        ),
        segments=(b("recall.suggestion.detail_contract"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The SystemMessage only, and nothing is substituted into it. The card being expanded and "
            "the verbatim source text it cites are the HumanMessage, assembled per call (see "
            "卡片展开输入) — including the branch for a card whose citation cannot be fetched."
        ),
        note_zh=(
            "这里只有系统消息，而且没有任何东西被代入其中。正在被展开的卡片、以及它引用的逐字原文"
            "构成人类消息，按次装配（见「卡片展开输入」）——包括「卡片的引用取不回来」那个分支。"
        ),
    ),
    Surface(
        id="recall.evidence",
        group="recall",
        title_en="Evidence sections (human turn)",
        title_zh="证据分节（人类消息）",
        summary_en=(
            "How the retrieved evidence is laid out for the answering model: the owner "
            "profile block, claim notes, raw excerpts, subject timelines, the input itself."
        ),
        summary_zh=(
            "召回到的证据以什么形式摆到回答模型面前：主人档案块、断言笔记、原文摘录、"
            "主题时间线，以及输入本身。"
        ),
        segments=(
            f(
                "recall.section.profile_header",
                "Opens the owner-profile block, when the deployment supplies a profile.",
                "当部署提供了档案时，开出主人档案那一块。",
            ),
            f(
                "recall.profile.name",
                "One line of that block, when the profile states a name.",
                "档案里有名字时，那一块里的一行。",
            ),
            f(
                "recall.profile.industry_role",
                "One line of that block, when the profile states an industry and role.",
                "档案里有行业与角色时，那一块里的一行。",
            ),
            f(
                "recall.profile.occupation",
                "One line of that block, when the profile states an occupation.",
                "档案里有职业时，那一块里的一行。",
            ),
            f(
                "recall.profile.location",
                "One line of that block, when the profile states where the owner is based.",
                "档案里有常驻地时，那一块里的一行。",
            ),
            f(
                "recall.profile.response_language",
                "One line of that block, when the profile states a reply language — the input "
                "itself can still override it.",
                "档案里有回复语言时，那一块里的一行——但这次输入本身仍可覆盖它。",
            ),
            f(
                "recall.section.claims_header",
                "Opens the compiled claim notes retrieved for this question.",
                "开出为这个问题召回的断言笔记。",
            ),
            f(
                "recall.section.claims_empty",
                "Takes its place when the claim retrieval returned nothing — an honest empty, "
                "not a silent omission.",
                "断言检索什么都没找到时取代上一条——诚实地说空，而不是悄悄省掉这一节。",
            ),
            f(
                "recall.section.windows_header",
                "Opens the raw excerpts (L2 chunks) in the fast lane's evidence.",
                "在快速车道的证据里，开出原文摘录（L2 片段）那一节。",
            ),
            f(
                "recall.section.component_header",
                'Header of the component face: what routed component lookups returned.',
                '组件面的标题：路由到的组件查询返回了什么。',
            ),
            f(
                "recall.fast.component.path_header",
                "One chosen path's block header — its name and the arguments the router passed.",
                '一条被选中的路的块标题——名字和路由传入的参数。',
            ),
            f(
                "recall.fast.component.path_degraded",
                'When a chosen path timed out or failed: stated, never silently omitted.',
                '被选中的路超时或失败时：明示，绝不静默省略。',
            ),
            f(
                "recall.fast.component.path_empty",
                'When a chosen path ran and found nothing.',
                '被选中的路跑了但没有结果。',
            ),
            f(
                "recall.fast.component.path_dropped",
                "How many of a path's results fell beyond its declared cap, when they cannot "
                "be grouped into a described summary.",
                '一条路的结果超出其声明上限的条数——在无法归组描述时使用。',
            ),
            f(
                "recall.fast.component.path_dropped_detail",
                "What a path did NOT show, described per section (or per day): the recoverable "
                "form of a truncation.",
                '一条路没有展示什么，按章节（或按日期）逐项说明：可追回的截断。',
            ),
            f(
                "recall.fast.component.path_already_shown",
                "How many of a path's results the ranked faces already carry, hidden here "
                "instead of shown twice.",
                '一条路的结果里有多少已经在排序面上，于是在这里隐去而不是展示两遍。',
            ),
            f(
                "recall.fast.component.path_covered",
                "How many claims of this path were folded into a raw excerpt of the same "
                "block that already contains their evidence.",
                '这条路有多少断言被折叠进同一块里已包含其证据的原文摘录。',
            ),
            f(
                "recall.fast.component.window_truncated",
                "The block range a budget-cut excerpt did not show — stated on the excerpt "
                "itself, so the cut is addressable.",
                '一段因预算被裁掉的摘录没有展示的块区间——就写在摘录上，于是这次裁剪是可寻址的。',
            ),
            f(
                "recall.section.images_header",
                "Opens images aligned to the raw excerpts selected for this question.",
                "开出与本次问题所选原文摘录对齐的图片。",
            ),
            f(
                "recall.fast.image_locator",
                "Binds one recalled image to its exact citable source block.",
                "把一张召回图片绑定到可引用的确切来源块。",
            ),
            f(
                "recall.section.passages_header",
                "The same excerpts under a nested heading, where they hang under a source "
                "rather than standing alone.",
                "同样的摘录，但挂在某份材料下面而不是独立成节时用的嵌套标题。",
            ),
            f(
                "recall.passage_truncated",
                "Marks an excerpt cut at the budget, and names the tool that can pull the rest.",
                "标出被预算截断的摘录，并点明可以用哪个工具取回其余部分。",
            ),
            f(
                "recall.section.timelines_header",
                "Opens the subject timelines, when whole documents were selected to be read in "
                "document order.",
                "当有整篇文档被选中、按文档顺序阅读时，开出主题时间线那一节。",
            ),
            f(
                "recall.fast.timeline.document",
                "The heading of one such timeline, once per selected document.",
                "其中一条时间线的标题，每份被选中的文档一次。",
            ),
            f(
                "recall.fast.window_note.header",
                "Introduces the claims compiled FROM the excerpt just above — the seam between "
                "raw material and recorded knowledge.",
                "引出「由上面这段原文编译出来的断言」——原始材料与已记录知识之间的接缝。",
            ),
            f(
                "recall.fast.window_note.line",
                "One such claim, with its anchor and the document it lives in.",
                "其中一条断言，带上它的锚点和所在文档。",
            ),
            f(
                "recall.fast.window_note.line_labeled",
                "The same line when the claim opens with a strength label, which is then shown.",
                "同一行，但断言带有强度标签时把标签一起显示出来。",
            ),
            f(
                "recall.section.transcript_header",
                "Opens the recent turns of the live stream — live-context mode only.",
                "开出实时流最近几轮发言——只在实时上下文模式下出现。",
            ),
            f(
                "recall.section.already_shown_header",
                "Lists the cards already surfaced in this conversation, so the same card is not "
                "offered twice.",
                "列出本次对话里已经推过的卡片，避免同一张卡片重复出现。",
            ),
            f(
                "recall.section.input",
                "Labels the owner's own input at the end of the evidence — invariant I5: the "
                "question travels in the human turn, never in the System contract.",
                "在证据末尾标出主人自己的输入——不变量 I5：问题走人类消息，绝不进系统契约。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.glance",
        group="recall",
        title_en="Knowledge base at a glance",
        title_zh="知识库一览",
        summary_en=(
            "The library's SHAPE, present for every question: which filing families "
            "exist, what is filed under each, how developed each document is."
        ),
        summary_zh=(
            "每个问题都会带上的知识库形状：有哪些归档家族、每个家族下面放了什么、"
            "每份文档发育到什么程度。"
        ),
        segments=(
            f(
                "recall.glance.header",
                "Opens the glance, which every question carries.",
                "开出一览——每个问题都会带上它。",
            ),
            f(
                "recall.glance.note",
                "Says what the glance is and is not: the shape of the base, not its contents.",
                "说明一览是什么、不是什么：它是知识库的形状，不是内容。",
            ),
            f(
                "recall.glance.empty",
                "Takes the document list's place when nothing has been filed yet — the families "
                "are still shown, as the places material will go.",
                "还没有归档任何东西时取代文档清单——家族仍然列出，作为材料将来的归处。",
            ),
            f(
                "recall.glance.family_heading",
                "The heading of one filing family, once per family the contract declares.",
                "一个归档家族的标题，契约声明的每个家族一次。",
            ),
            f(
                "recall.glance.family_blurb",
                "Added under that heading when the family declares a description of its own.",
                "当某个家族自己声明了说明文字时，加在它的标题下面。",
            ),
            f(
                "recall.glance.family_empty",
                "Added under a family that has no documents filed under it yet.",
                "某个家族下面还没有文档时，加在它下面。",
            ),
            f(
                "recall.glance.entry",
                "One document of the glance, once per document.",
                "一览里的一份文档，每份文档一次。",
            ),
            f(
                "recall.glance.entry_definition",
                "One line under a glance entry that has an overview: its definition.",
                "带总览的鸟瞰条目下面的一行：它的 definition。",
            ),
            f(
                "recall.glance.entry_ledger",
                "One line under a glance entry that has no overview definition: the head of "
                "its own current ledger.",
                "没有总览 definition 的鸟瞰条目下面的一行：它自己当前账本的开头。",
            ),
            f(
                "recall.glance.entry_tail_updated",
                "Appended to that line when the document carries a last-updated day.",
                "当文档带有最后更新日时，追加到那一行后面。",
            ),
            f(
                "recall.glance.entry_tail_archived",
                "Appended when the document has frozen archive volumes behind it.",
                "当文档背后有冻结归档卷时追加。",
            ),
            f(
                "recall.glance.family_more",
                "Closes a family whose documents exceed the per-family display cap.",
                "当某个家族的文档数超过单家族展示上限时，用它收束。",
            ),
            f(
                "recall.glance.unfiled_heading",
                "Heads the documents that fall outside every declared family — the glance shows "
                "them rather than hiding a filing gap.",
                "为落在所有已声明家族之外的文档立一个标题——一览把归档缺口显示出来而不是藏起来。",
            ),
            f(
                "recall.glance.flat_heading",
                "Used instead of family headings when the contract declares no families at all.",
                "当契约完全没有声明家族时，用它代替家族标题。",
            ),
            f(
                "recall.glance.truncated",
                "Closes the glance when it hit its overall line budget.",
                "当一览撞到总行数预算时，用它收束。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.snapshot",
        group="recall",
        title_en="Snapshot-scoped answering",
        title_zh="快照范围内作答",
        summary_en=(
            "Rendered only when a question is pinned to a frozen snapshot. It inverts the "
            "usual frame: a gap in the evidence is the honest state of the base at that "
            "moment, not a retrieval failure to work around."
        ),
        summary_zh=(
            "只有当提问被钉在冻结快照上时才渲染。它把平时的框架反了过来："
            "证据里的空白是知识库在那一刻的诚实状态，而不是需要绕开的检索失败。"
        ),
        segments=(
            f(
                "recall.snapshot.declaration",
                "Prefixed to the evidence whenever the question is pinned to a snapshot; absent "
                "entirely otherwise.",
                "只要提问被钉在某个快照上，就加在证据前面；否则完全不出现。",
            ),
            f(
                "recall.snapshot.moment",
                "Names the snapshot inside that declaration, when the snapshot carries a freeze "
                "time.",
                "在那段声明里点名快照——当快照带有冻结时间时。",
            ),
            f(
                "recall.snapshot.moment_undated",
                "Names it without a time, when the snapshot carries none.",
                "快照没有时间时，只点名不带时间。",
            ),
            f(
                "recall.snapshot.source_absent",
                "Returned by a verbatim fetch for a source the snapshot does not contain — the "
                "absence is the answer, not a retrieval failure.",
                "当逐字取原文的目标不在快照里时返回——这份缺失本身就是答案，不是检索失败。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.deep_tools",
        group="recall",
        title_en="Deep recall tool face",
        title_zh="深度召回工具面",
        summary_en=(
            "The agentic search tools and their replies: `search_claims`, `search_content`, "
            "`fetch_verbatim`. Their own names — the compile face reads and writes, so it has "
            "its own — but the same addressing vocabulary, source id plus block span, which "
            "is what lets a result found here be checked against the original."
        ),
        summary_zh=(
            "代理式检索的工具及其回复：`search_claims`、`search_content`、`fetch_verbatim`。"
            "名字是它自己的一套——编译面既读也写，所以那边另有一套——但寻址词汇是同一套："
            "来源 id 加块区间，正是它让这里查到的结果能拿回原文核对。"
        ),
        segments=(
            f(
                "recall.deep.tool.search_claims",
                "The one-line description of `search_claims` in the tool list.",
                "工具清单里 `search_claims` 的一行描述。",
            ),
            f(
                "recall.deep.tool.search_claims_doc",
                "The fuller docstring of the same tool — both reach the model, in the tool "
                "schema the agent reads before choosing.",
                "同一个工具更完整的文档串——两者都会到达模型，在代理选择前读到的工具 schema 里。",
            ),
            f(
                "recall.deep.tool.search_claims_empty",
                "The reply when that search matched no claim, and it points at the other face "
                "to try.",
                "这次检索没有命中断言时的回复，并指向另一个可以试的面。",
            ),
            f(
                "recall.deep.tool.search_content",
                "The one-line description of `search_content` in the tool list.",
                "工具清单里 `search_content` 的一行描述。",
            ),
            f(
                "recall.deep.tool.search_content_doc",
                "The fuller docstring of the same tool.",
                "同一个工具更完整的文档串。",
            ),
            f(
                "recall.deep.tool.search_content_empty",
                "The reply when no raw fragment matched.",
                "没有命中任何原始片段时的回复。",
            ),
            f(
                "recall.deep.tool.fetch_verbatim",
                "The one-line description of `fetch_verbatim` — the L0 route that makes deep "
                "verification possible at all.",
                "`fetch_verbatim` 的一行描述——正是这条 L0 通道让深度校验成为可能。",
            ),
            f(
                "recall.deep.tool.fetch_verbatim_doc",
                "Its fuller docstring, including the shape of a locator.",
                "它更完整的文档串，包含定位符的形状。",
            ),
            f(
                "recall.deep.tool.fetch_verbatim_failed",
                "The reply to a malformed or unresolvable fetch — it teaches the locator shape "
                "instead of only refusing.",
                "定位符写错或无法解析时的回复——它顺手教会定位符的形状，而不只是拒绝。",
            ),
            f(
                "recall.deep.tool.fetch_verbatim_empty",
                "The reply when a well-formed locator addressed nothing.",
                "定位符格式正确但没有对应内容时的回复。",
            ),
            f(
                "recall.deep.tool.list_documents",
                "The one-line description of `list_documents` in the tool list.",
                "工具清单里 `list_documents` 的一行描述。",
            ),
            f(
                "recall.deep.tool.list_documents_doc",
                "Its fuller docstring, which names when to use it: a truncated glance, or an "
                "exact path spelling.",
                "它更完整的文档串，点明什么时候该用它：一览被截断，或需要路径的准确写法。",
            ),
            f(
                "recall.deep.tool.list_documents_empty",
                "The reply when the knowledge base holds no documents.",
                "知识库里没有文档时的回复。",
            ),
            f(
                "recall.deep.tool.read_document",
                "The one-line description of `read_document` in the tool list.",
                "工具清单里 `read_document` 的一行描述。",
            ),
            f(
                "recall.deep.tool.read_document_doc",
                "Its fuller docstring — including that a document's links can be followed by "
                "reading their targets.",
                "它更完整的文档串——包括「文档里的链接可以顺着读它的目标」这一点。",
            ),
            f(
                "recall.deep.tool.read_document_not_found",
                "The reply when no document sits at the requested path.",
                "请求的路径上没有文档时的回复。",
            ),
            f(
                "recall.agentic.budget_notice",
                "Injected once the retrieval budget is spent: the loop ends by answering from "
                "what it already has, not by stopping mid-air.",
                "检索预算用尽时注入：循环以「用已有证据作答」收束，而不是半空中停住。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.briefing_pack",
        group="recall",
        title_en="Briefing pack and tools",
        title_zh="简报知识包与工具",
        summary_en=(
            "How the fixed knowledge pack is laid out for a briefing session, and the two "
            "tools that reach past the SAMPLE it laid out — one searching the session's own "
            "source range again, one fetching any source verbatim by id."
        ),
        summary_zh=(
            "固定知识包在简报会话里怎么摆开，以及那两个能越过「已摊开的样本」的工具——"
            "一个在本次会话自己的来源范围内再检索，一个按 id 逐字取回任意来源。"
        ),
        segments=(
            f(
                "recall.briefing.query_section_header",
                "Opens the query half of the pack, when the session was scoped by a query.",
                "当会话是按查询划定范围时，开出知识包里「按查询」那一半。",
            ),
            f(
                "recall.briefing.query_claims_header",
                "Introduces the claims that query retrieved.",
                "引出那次查询召回的断言。",
            ),
            f(
                "recall.briefing.query_excerpts_header",
                "Introduces the raw excerpts that query retrieved.",
                "引出那次查询召回的原文摘录。",
            ),
            f(
                "recall.briefing.source_section_header",
                "Opens the source half of the pack, when the session was scoped to named "
                "sources.",
                "当会话是按指定材料划定范围时，开出知识包里「按材料」那一半。",
            ),
            f(
                "recall.briefing.source_heading",
                "The heading of one such source, once per source in scope.",
                "其中一份材料的标题，范围内每份材料一次。",
            ),
            f(
                "recall.briefing.material_cards_header",
                "Introduces that source's material cards, when it has any.",
                "当那份材料有材料卡片时，引出它们。",
            ),
            f(
                "recall.briefing.citing_claims_header",
                "Introduces the claims that cite that source — the compiled reading of it.",
                "引出引用了那份材料的断言——也就是它被编译后的读法。",
            ),
            f(
                "recall.briefing.outline_header",
                "Introduces that source's section outline, for a source that has structure.",
                "对有结构的材料，引出它的小节大纲。",
            ),
            f(
                "recall.briefing.outline_more",
                "Closes an outline cut at its display cap.",
                "当大纲撞到展示上限被截断时收束它。",
            ),
            f(
                "recall.briefing.excerpts_header",
                "Introduces the verbatim excerpts of that source.",
                "引出那份材料的逐字摘录。",
            ),
            f(
                "recall.briefing.provenance_suffix",
                "Appended to a claim in the pack, naming the sources it cites, so a citation "
                "can be followed from inside the session.",
                "追加在知识包里的断言后面，点明它引用了哪些材料，让引用能在会话内被追下去。",
            ),
            f(
                "recall.briefing.budget_truncated",
                "Marks the point where the pack hit its token budget.",
                "标出知识包撞到 token 预算的位置。",
            ),
            f(
                "recall.briefing.tool.search_knowledge",
                "The one-line description of the in-pack search tool.",
                "包内检索工具的一行描述。",
            ),
            f(
                "recall.briefing.tool.search_knowledge_doc",
                "Its fuller docstring — both reach the model through the tool schema.",
                "它更完整的文档串——两者都通过工具 schema 到达模型。",
            ),
            f(
                "recall.briefing.tool.claims_header",
                "Introduces the claim hits inside that tool's reply.",
                "在该工具的回复里，引出命中的断言。",
            ),
            f(
                "recall.briefing.tool.passages_header",
                "Introduces the excerpt hits inside the same reply.",
                "在同一条回复里，引出命中的原文摘录。",
            ),
            f(
                "recall.briefing.tool.search_empty",
                "The reply when nothing inside the pack's range matched.",
                "包的范围内什么都没命中时的回复。",
            ),
            f(
                "recall.briefing.tool.fetch_verbatim",
                "The one-line description of the L0 fetch tool — the second way out of the "
                "fixed pack.",
                "L0 取原文工具的一行描述——从固定知识包伸出去的第二条通道。",
            ),
            f(
                "recall.briefing.tool.fetch_verbatim_doc",
                "Its fuller docstring, including the shape of a locator.",
                "它更完整的文档串，包含定位符的形状。",
            ),
            f(
                "recall.briefing.tool.fetch_verbatim_failed",
                "The reply when that fetch failed.",
                "取原文失败时的回复。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.suggestion_detail_pack",
        group="recall",
        title_en="Card expansion input",
        title_zh="卡片展开输入",
        summary_en=(
            "The card being expanded and the verbatim source text it cites — fetched, not "
            "retrieved, which is why the expansion contract carries no spine. When the "
            "citation cannot be fetched there is no source text at all, and the last clause "
            "here is what makes the card itself the boundary instead."
        ),
        summary_zh=(
            "正在被展开的卡片，以及它引用的逐字原文——是取来的、不是检索来的，"
            "这正是展开契约不带脊柱的原因。引用取不回来时就完全没有原文，"
            "此时是这里的最后一条把边界改成「卡片本身」。"
        ),
        segments=(
            f(
                "recall.suggestion.detail_card",
                "The card being expanded, always first: kind, title, body, and the fragment "
                "that triggered it.",
                "正在被展开的卡片，总是第一段：类型、标题、正文，以及触发它的那段原文。",
            ),
            f(
                "recall.suggestion.detail_sources_header",
                "Introduces the verbatim source text the card cites, when the citation resolves.",
                "当引用能被解析时，引出卡片引用的逐字原文。",
            ),
            f(
                "recall.suggestion.detail_source_head",
                "Labels one such passage with its source id and block span.",
                "为其中一段原文标上材料 id 与块区间。",
            ),
            f(
                "recall.suggestion.detail_no_sources",
                "Takes that section's place when the card has no fetchable citation — then the "
                "expansion may only work from the card itself.",
                "当卡片没有可取回的引用时取代那一节——此时只能就着卡片本身展开。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.fast_select",
        group="recall",
        title_en="Full-document selection pass",
        title_zh="整篇文档选取",
        summary_en=(
            "A small call running concurrently with retrieval: from the glance alone, "
            "name the documents that must be read IN FULL. Selecting nothing is the "
            "normal answer."
        ),
        summary_zh=(
            "与检索并发的一次小调用：只看一览，指出哪些文档必须整篇读。"
            "什么都不选是正常结果。"
        ),
        segments=(
            f(
                "recall.fast.select.contract",
                "The SystemMessage of the selection call: name documents, answer nothing.",
                "选取调用的系统消息：只指出文档，不回答问题。",
            ),
            f(
                "recall.fast.select.request",
                "Its HumanMessage: the glance, the question, and the cap on how many may be "
                "selected.",
                "它的人类消息：一览、问题，以及最多可选几份的上限。",
            ),
            f(
                "recall.fast.select.documents_header",
                "Not part of that call — it opens the selected documents inside the ANSWERING "
                "model's evidence.",
                "不属于这次调用——它在回答模型的证据里开出「整篇文档」那一节。",
            ),
            f(
                "recall.fast.select.document_heading",
                "The heading of one selected document there, once per document read in full.",
                "那一节里某份被选中文档的标题，每份整篇读入的文档一次。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.fast_evidence_select",
        group="recall",
        title_en="Cross-face evidence composition",
        title_zh="跨证据面的证据编排",
        summary_en=(
            "One structured call selects coordinates from broad claim, episode-summary and "
            "verbatim-window candidates, plus known canonical paths. Its output is validated "
            "and bounded before any evidence reaches the answer."
        ),
        summary_zh=(
            "一次结构化调用从宽断言候选、episode 摘要候选、逐字窗口候选以及已知 canonical "
            "路径中选择坐标；证据进入回答前，输出会先被验证并受机械上限约束。"
        ),
        segments=(
            f(
                "recall.fast.evidence_select.contract",
                "The selector's SystemMessage: choose evidence coordinates, never answer.",
                "选择器的系统消息：只选证据坐标，绝不回答问题。",
            ),
            f(
                "recall.fast.evidence_select.request",
                "Its HumanMessage wrapper, with every candidate face before the question.",
                "它的人类消息外壳：所有候选证据面都排在问题之前。",
            ),
            f(
                "recall.fast.evidence_select.glance",
                "The optional canonical glance inside the candidate payload.",
                "候选载荷中可选的 canonical 一览。",
            ),
            f(
                "recall.fast.evidence_select.claims_header",
                "Opens numbered compiled-claim candidates.",
                "开出带编号的已编译断言候选。",
            ),
            f(
                "recall.fast.evidence_select.claim",
                "One claim candidate with its canonical path, section and text.",
                "一条带 canonical 路径、章节和正文的断言候选。",
            ),
            f(
                "recall.fast.evidence_select.episodes_header",
                "Opens numbered derived episode-summary candidates.",
                "开出带编号的派生 episode 摘要候选。",
            ),
            f(
                "recall.fast.evidence_select.episode",
                "One derived summary with date and exact source coordinates.",
                "一条带日期与精确源坐标的派生摘要。",
            ),
            f(
                "recall.fast.evidence_select.windows_header",
                "Opens numbered verbatim source-window candidates.",
                "开出带编号的逐字源窗口候选。",
            ),
            f(
                "recall.fast.evidence_select.window",
                "One verbatim candidate with source id and exact block span.",
                "一条带来源 id 与精确块区间的逐字候选。",
            ),
            f(
                "recall.fast.evidence_select.components_header",
                "Opens the routed component lookups as candidates the selector may pick from "
                "exactly like the ranked faces.",
                "开出路由到的组件查询候选：选择器可以像挑排序面一样从中挑选。",
            ),
            f(
                "recall.fast.evidence_select.component_group",
                "One lookup's group heading — the path and the arguments the router chose.",
                "一条查询的组标题——路由选择的路名与参数。",
            ),
            f(
                "recall.fast.evidence_select.component_item",
                "One component candidate: what kind it is, where it resolves to, and its text.",
                "一条组件候选：它是哪种、落到哪个地址、正文是什么。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.fast_episode_summaries",
        group="recall",
        title_en="Derived episode summaries",
        title_zh="派生 episode 摘要",
        summary_en=(
            "Dense episode descriptions enter answer context as explicitly derived summaries "
            "with source title, occurrence time, section, and exact source span."
        ),
        summary_zh=(
            "高密度 episode 描述以明确标注的派生摘要进入回答上下文，并带来源标题、发生时间、"
            "章节和精确源区间。"
        ),
        segments=(
            f(
                "recall.section.episode_summaries_header",
                "The section header states plainly that these entries are derived episode summaries.",
                "章节标题明确声明这些条目是派生 episode 摘要。",
            ),
            f(
                "recall.fast.episode_summary.item",
                "One derived summary with source metadata and its exact citable block span.",
                "一条带来源元数据和精确可引用块区间的派生摘要。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.fast_plan",
        group="recall",
        title_en="Retrieval planning pass",
        title_zh="检索规划",
        summary_en=(
            "Off by default. One call before retrieval derives extra search queries, so a "
            "multi-aspect question fans out instead of blending into one embedding."
        ),
        summary_zh=(
            "默认关闭。检索之前的一次调用推导出额外的搜索查询，"
            "让多面向的问题散开检索，而不是揉成一个向量。"
        ),
        segments=(
            f(
                "recall.fast.plan.contract",
                "The SystemMessage of the planning call, only when this deployment turns "
                "retrieval planning on.",
                "规划调用的系统消息，只有当本部署开启了检索规划时才存在。",
            ),
            f(
                "recall.fast.route.system",
                "The routing turn's system contract: bind the component paths as tools, choose zero or more in one turn, never answer.",
                '路由轮的 system 契约：把组件路绑成工具，一轮里选零个或多个，绝不作答。',
            ),
            f(
                "recall.fast.route.request",
                "The routing turn's human line: the question, as_of, and the owner's "
                "timezone — so the model resolves a relative time expression into ISO days "
                "itself and the index never parses one.",
                '路由轮的 human 行：问题、as_of 与主人的时区——相对时间表达由模型自己解析成 '
                'ISO 日期，索引一律不解析自然语言时间。',
            ),
            f(
                "recall.fast.plan.request",
                "Its HumanMessage: the question, and the cap on extra queries — an empty answer "
                "is a valid one.",
                "它的人类消息：问题，以及额外查询的上限——返回空也是合法答案。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="recall.rerank",
        group="recall",
        title_en="LLM claim reranker",
        title_zh="LLM 断言重排",
        summary_en=(
            "A cheap non-reasoning call playing the cross-encoder's role. Its output is "
            "consumed mechanically (indexes), so the pass can only reorder evidence."
        ),
        summary_zh=(
            "一次廉价的非推理调用，扮演 cross-encoder 的角色。它的输出被机械消费（下标），"
            "所以这一趟只能重排证据。"
        ),
        segments=(
            f(
                "recall.rerank.llm.system",
                "The SystemMessage of the rerank call, only when this deployment's reranker is "
                "the LLM one.",
                "重排调用的系统消息，只有当本部署的重排器选了 LLM 这一种时才存在。",
            ),
            f(
                "recall.rerank.llm.request",
                "Its HumanMessage: the numbered candidates and the question. The answer is read "
                "as indexes, so this pass can only reorder.",
                "它的人类消息：编号候选与问题。回答被当成下标消费，所以这一趟只能重排。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    # ────────────────────────────────────────────────────────────── persona / skill
    Surface(
        id="persona.profile",
        group="persona",
        title_en="Profile expansion",
        title_zh="档案扩写",
        summary_en=(
            "One sentence a person typed, turned into a profile draft they then confirm "
            "field by field. It fills only what the sentence supports and leaves the rest "
            "empty — no invented name, city or country. Never persisted by this call."
        ),
        summary_zh=(
            "一个人自己写的一句话，变成一份由他逐字段确认的档案草稿。"
            "只填这句话支持得住的部分，其余留空——不编造姓名、城市或国家。这次调用本身从不落库。"
        ),
        segments=(b("persona.profile_instruction"),),
        kind=ASSEMBLED,
        pinned=True,
        note_en=(
            "The SystemMessage only. The one sentence being expanded arrives in the "
            "HumanMessage, and the field names plus the closed enums the draft must choose "
            "from reach the model as the structured-output schema rather than as prose here — "
            "which is why this text names them without listing their members. Nothing on this "
            "path is written anywhere: the endpoint returns a draft, and a person confirms it "
            "field by field before it becomes a profile."
        ),
        note_zh=(
            "这里只有系统消息。被扩写的那句话随人类消息到达；字段名与草稿必须从中取值的封闭枚举"
            "是以结构化输出 schema 的形式到达模型的，而不是这段文字里的文案——"
            "所以这里只点名它们，不列举成员。这条路径上什么都不会被写下：接口返回的是草稿，"
            "要由人逐字段确认之后才成为档案。"
        ),
    ),
    Surface(
        id="skill.derive",
        group="skill",
        title_en="Skill derivation",
        title_zh="领域契约推导",
        summary_en=(
            "Inferring a starting domain contract from what is known about the subject — "
            "occupation, bio, interests."
        ),
        summary_zh="从对主体的已知信息（职业、简介、兴趣）推导出一份起步的领域契约。",
        segments=(
            f(
                "skill.derive_contract",
                "The SystemMessage of the derivation call: the judgement of whether this "
                "subject's work produces a distinct class of knowledge at all.",
                "推导调用的系统消息：判断这位主体的工作是否真的产生一类与众不同的知识。",
            ),
            f(
                "skill.derive.human",
                "Its HumanMessage: the three things known about the subject, and nothing else.",
                "它的人类消息：关于主体已知的三项信息，别无其他。",
            ),
            f(
                "skill.derive.empty",
                "Stands in for whichever of those three the profile does not supply.",
                "档案没有提供那三项中的哪一项，就用它代替那一项。",
            ),
            f(
                "skill.derive.interest_separator",
                "Joins the interests into one line of that message.",
                "把多个兴趣连成那条消息里的一行。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="skill.claim_labels",
        group="skill",
        title_en="Claim strength labels",
        title_zh="断言强度标签",
        summary_en=(
            "The controlled three-tier vocabulary a claim may open with. The projection "
            "layer tiers the presentation from it, so the tiers are a closed set."
        ),
        summary_zh=(
            "断言可以用来开头的三档受控词汇。投影层据此分层呈现，所以这三档是封闭集合。"
        ),
        segments=(
            f(
                "skill.claim_label.clause_marker",
                "Not sent to any model: the phrase whose presence in a contract decides "
                "MECHANICALLY that this version emits strength labels at all.",
                "不发给任何模型：它是否出现在契约里，机械地决定了这个版本到底会不会用强度标签。",
            ),
            f(
                "skill.claim_label.strong.label",
                "The literal prefix of the firm tier, as the reading side and the dataset "
                "record it. What makes the model WRITE it is the contract clause "
                "`contract.rule.strength_labels`.",
                "确定档的字面前缀，阅读侧与数据集按它记录。真正让模型写出这个前缀的是契约条款 "
                "`contract.rule.strength_labels`。",
            ),
            f(
                "skill.claim_label.strong.name",
                "That tier's display name, shown by `GET /skill` and the reading UI — it "
                "reaches no model.",
                "该档的显示名，由 `GET /skill` 与阅读界面使用——它不会到达任何模型。",
            ),
            f(
                "skill.claim_label.strong.description",
                "That tier's meaning as the reading UI explains it: when it applies, and how a "
                "claim is re-tiered forward instead of rewritten.",
                "阅读界面对该档含义的解释：什么情况算这一档，以及断言如何向前重新分档而不是被改写历史。",
            ),
            f(
                "skill.claim_label.medium.label",
                "The literal prefix of the in-progress tier — direction clear, one key slot "
                "still missing.",
                "进行中档的字面前缀——方向明确，但还缺一个关键要素。",
            ),
            f(
                "skill.claim_label.medium.name",
                "That tier's display name on the same read path.",
                "该档在同一条阅读路径上的显示名。",
            ),
            f(
                "skill.claim_label.medium.description",
                "That tier's meaning on the same read path, including what promotes a claim out "
                "of it.",
                "该档在同一条阅读路径上的含义，包括什么条件会让断言升档。",
            ),
            f(
                "skill.claim_label.weak.label",
                "The literal prefix of the mentioned-only tier: a one-off, a hypothesis, a "
                "second-hand account.",
                "仅被提及档的字面前缀：一次性提及、假设、二手转述。",
            ),
            f(
                "skill.claim_label.weak.name",
                "That tier's display name on the same read path.",
                "该档在同一条阅读路径上的显示名。",
            ),
            f(
                "skill.claim_label.weak.description",
                "That tier's meaning on the same read path, including the rule to drop a tier "
                "when unsure rather than raise one.",
                "该档在同一条阅读路径上的含义，包括「不确定时降一档而不是升一档」这条规则。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    # ───────────────────────────────────────────────────────────── rejection wording
    Surface(
        id="feedback.compile_gate",
        group="feedback",
        title_en="Compile gate rejections",
        title_zh="编译闸门拒绝",
        summary_en=(
            "What the compile agent reads when the mechanical checks refuse its round. "
            "Each line names one violation and the repair; the agent gets one repair round."
        ),
        summary_zh=(
            "机械检查拒绝这一轮时，编译代理读到的东西。每一条点名一处违规和它的修复方式；"
            "代理有一次修复回合。"
        ),
        segments=(
            f(
                "gate.feedback_header",
                "Opens every rejection, whichever checks failed, and names the repair route.",
                "无论是哪些检查没过，每次拒绝都以它开头，并指出修复通道。",
            ),
            f(
                "gate.previous_round_cut_off",
                "Prefixed above that header when the round being rejected did not end on "
                "its own but ran out of tool calls — so the repair round knows its "
                "exploration was cut, not completed, and starts from a fresh budget.",
                "当被拒绝的那一轮不是自己结束、而是工具调用用尽时，加在上面那句之前——修复轮"
                "因此知道上一轮的探索是被截断而非跑完的，并且自己有一份全新的预算。",
            ),
            f(
                "gate.overview_budget",
                "The overview is over its character budget — it is a head, not a second ledger.",
                "总览超出字符预算——它是头部，不是第二本账。",
            ),
            f(
                "gate.overview_ungrounded",
                "An overview block references no ledger claim and cites no source span.",
                "某个总览块既没引账本断言，也没引来源区间。",
            ),
            f(
                "compile.overview.refuse_missing",
                "A document the round changed holds more ledger claims than the threshold "
                "and has no overview definition — the same line the finish face states "
                "earlier, said again as a violation.",
                "本轮改动过的某份文档账本断言数已过阈值，却没有总览 definition——与结束"
                "工具面更早说过的是同一句话，这里作为一条违规再说一次。",
            ),
            f(
                "gate.overview_unknown_slot",
                "The overview carries a slot outside the four the region defines.",
                "总览里出现了四个既定槽位之外的槽位。",
            ),
            f(
                "gate.overview_definition_blocks",
                "The overview's definition is more than one block — it is one sentence.",
                "总览的 definition 超过一个块——它只有一句话。",
            ),
            f(
                "gate.overview_definition_length",
                "The overview's definition is over its own character limit.",
                "总览的 definition 超出它自己的字符上限。",
            ),
            f(
                "gate.anchor_continuity",
                "When an anchor that existed before this round is gone after it — v1 has no "
                "deletion channel.",
                "当本轮之前存在的某个锚点在本轮之后消失时——v1 没有删除通道。",
            ),
            f(
                "gate.anchor_uniqueness",
                "When the same anchor id occurs in two places; an anchor is a repo-unique "
                "identity.",
                "当同一个锚点 id 出现在两处时；锚点是全库唯一的身份。",
            ),
            f(
                "gate.anchor_coverage",
                "When a content block carries no anchor, so it would never enter the claim index.",
                "当某个内容块没有锚点、因而永远进不了断言索引时。",
            ),
            f(
                "gate.claim_text_machinery",
                "When a page this round wrote carries an HTML comment or an invented "
                "`__AUTO__` / `__NEW__` anchor placeholder inside a claim's text — typically "
                "two claims glued together by a marker the model wrote itself.",
                "当本轮写过的页面里，某条断言的正文中带了 HTML 注释或自己编出来的 "
                "`__AUTO__` / `__NEW__` 锚点占位符时——通常是模型自己写了个标记，把两条断言粘成了一条。",
            ),
            f(
                "gate.frontmatter_missing",
                "When a document's frontmatter lacks a required field.",
                "当某份文档的 frontmatter 缺少必填字段时。",
            ),
            f(
                "gate.claim_without_provenance",
                "When a newly written claim links back to nothing — this is the citation gate "
                "itself, the check that makes fabrication structurally impossible.",
                "当新写的断言没有任何回溯依据时——这就是引用闸门本身，让编造在结构上不可能的那道检查。",
            ),
            f(
                "gate.citation_unknown_source",
                "When a citation names a source that was not supplied this round.",
                "当引用指向本轮并未提供的材料时。",
            ),
            f(
                "gate.citation_out_of_range",
                "When a citation's block span falls outside the source's actual block count.",
                "当引用的块区间超出材料真实块数时。",
            ),
            f(
                "gate.citation_unparsable_marker",
                "When a `[cite: …]` marker does not parse as a locator; it restates the legal "
                "shape.",
                "当 `[cite: …]` 标记无法解析成定位符时；它顺带重述合法写法。",
            ),
            f(
                "gate.citation_anchor_in_marker",
                "When an anchor id was written inside a `[cite: …]` marker — anchor provenance "
                "is plain text, source provenance is the bracket.",
                "当锚点 id 被写进了 `[cite: …]` 里——锚点依据写成正文，材料依据才用方括号。",
            ),
            f(
                "gate.link_self_reference",
                "When a document links to itself.",
                "当一份文档链接到它自己时。",
            ),
            f(
                "gate.link_dead",
                "When a link points at a document that does not exist.",
                "当链接指向一份并不存在的文档时。",
            ),
            f(
                "gate.path_not_owned",
                "When a write lands outside the contract's ownership templates.",
                "当写入落在契约的归属模板之外时。",
            ),
            f(
                "gate.archive_frozen",
                "When a write targets a frozen archive volume, and it names the active page to "
                "write to instead.",
                "当写入的目标是冻结归档卷时，并指出应该改写哪个活动页面。",
            ),
            f(
                "gate.supersession_target_missing",
                'A supersedes marker names an anchor that exists nowhere.',
                'supersedes 标记指向一个不存在的锚点。',
            ),
            f(
                "gate.supersession_self",
                'A claim names itself as its predecessor.',
                '断言把自己列为前任。',
            ),
            f(
                "gate.supersession_multiple",
                'One claim names several predecessors.',
                '一条断言列出了多个前任。',
            ),
            f(
                "gate.supersession_not_linear",
                'Two claims name the same predecessor — a fact has one current state.',
                '两条断言指向同一个前任——一个事实只有一个当前状态。',
            ),
            f(
                "gate.supersession_cycle",
                'A supersession chain loops back on itself.',
                '取代链回到了自身。',
            ),
            f(
                "gate.supersession_frozen",
                "A superseded claim's text changed; superseded history is immutable.",
                '被取代断言的正文被改动；被取代的历史不可变。',
            ),
            f(
                "gate.supersession_without_evidence",
                'A superseding claim cites no new evidence.',
                '取代断言没有引用新证据。',
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="feedback.compile_writes",
        group="feedback",
        title_en="Write-tool rejections",
        title_zh="写入工具拒绝",
        summary_en=(
            "The early, teachable refusals at the tool face — before the round is spent. "
            "They state the corrective action, not just the rule."
        ),
        summary_zh=(
            "工具面上早期、可教学的拒绝——在这一轮被花掉之前。它们说的是该怎么改，"
            "而不只是规则本身。"
        ),
        segments=(
            f(
                "compile.anchor.edit_unknown_anchor",
                "`edit_claim` naming an anchor that is not in that document; the reply lists the "
                "anchors that are.",
                "`edit_claim` 点了一个不在该文档里的锚点；回复会列出真正存在的锚点。",
            ),
            f(
                "compile.anchor.edit_duplicate_anchor",
                "`edit_claim` on an anchor that occurs twice in the document — the duplicate is "
                "fixed first.",
                "`edit_claim` 指向在文档里出现了两次的锚点——先把重复修掉。",
            ),
            f(
                "compile.anchor.edit_extra_anchor",
                "`edit_claim` whose new text carries other anchors: one edit rewrites exactly "
                "one claim.",
                "`edit_claim` 的新文本里带了别的锚点：一次编辑只重写一条断言。",
            ),
            f(
                "compile.anchor.append_empty_heading",
                "`append_block` with an empty section heading.",
                "`append_block` 的小节标题为空。",
            ),
            f(
                "compile.anchor.append_anchor_present",
                "`append_block` whose new text carries an anchor — the system assigns anchors, "
                "never the model.",
                "`append_block` 的新文本自带锚点——锚点由系统分配，从不由模型分配。",
            ),
            f(
                "compile.anchor.text_machinery",
                "Any write whose claim TEXT carries the system's own machinery — an HTML "
                "comment, or an invented `__AUTO__` / `__NEW__` anchor placeholder. It names "
                "the corrective action: two statements are two blocks.",
                "任何写入的断言正文里带了系统自己的机器标记——HTML 注释，或自己编出来的 "
                "`__AUTO__` / `__NEW__` 锚点占位符。回复会指出该怎么改：两条陈述就是两个块。",
            ),
            f(
                "compile.anchor.supersede_unknown_anchor",
                '`supersede_claim` on an anchor that is not in the document; the reply lists the ones that are.',
                '`supersede_claim` 点了一个不在该文档里的锚点；回复会列出真正存在的锚点。',
            ),
            f(
                "compile.anchor.supersede_duplicate_anchor",
                '`supersede_claim` on an anchor that occurs twice in the document — the duplicate is fixed first.',
                '`supersede_claim` 指向在文档里出现了两次的锚点——先把重复修掉。',
            ),
            f(
                "compile.anchor.supersede_anchor_present",
                '`supersede_claim` whose new text carries an anchor or a supersedes marker: the system assigns both.',
                '`supersede_claim` 的新文本自带锚点或 supersedes 标记：两者都由系统分配。',
            ),
            f(
                "compile.anchor.supersede_not_one_block",
                '`supersede_claim` whose new text is more than one claim block.',
                '`supersede_claim` 的新文本不止一个断言块。',
            ),
            f(
                "compile.anchor.supersede_without_evidence",
                '`supersede_claim` whose new text cites nothing: only new evidence may supersede a state.',
                '`supersede_claim` 的新文本没有引用：只有新证据才能取代一个状态。',
            ),
            f(
                "compile.anchor.edit_supersedes_changed",
                '`edit_claim` whose new text names a different predecessor than the claim already has; the link is system-kept.',
                '`edit_claim` 的新文本改动了断言已有的前任标记；该链接由系统保留。',
            ),
            f(
                "compile.anchor.move_unknown_anchor",
                "A claim move/merge naming an anchor that is not in the source document.",
                "断言搬迁/合并点了一个不在源文档里的锚点。",
            ),
            f(
                "compile.anchor.move_duplicate_anchor",
                "A claim move/merge on an anchor that occurs twice.",
                "断言搬迁/合并指向出现了两次的锚点。",
            ),
            f(
                "compile.anchor.move_missing_anchor",
                "A claim move whose target block carries no anchor, so it is not an existing "
                "claim to move.",
                "断言搬迁的目标块没有锚点，因而它不是一条可搬迁的既有断言。",
            ),
            f(
                "compile.overview.refuse_unread",
                "Refuses a whole-region write (`rewrite_overview` / `set_fields`) against a "
                "document this compile has not read: what to keep cannot be judged against "
                "a picture that was never seen.",
                "拒绝对本次编译没读过的文档做整体写入（`rewrite_overview` / `set_fields`）："
                "没看过的画像，谈不上判断哪些该留。",
            ),
            f(
                "compile.overview.refuse_header",
                "Opens the tool face's overview refusal: nothing was written, and every "
                "failing block is listed under it at once.",
                "工具面总览拒绝的开头：什么都没写入，下面一次列出所有不合格的块。",
            ),
            f(
                "compile.overview.refuse_budget",
                "The candidate overview renders over its character budget — refused before "
                "the write rather than at the gate.",
                "候选总览渲染后超出字符预算——在写入前就拒绝，而不是拖到闸门。",
            ),
            f(
                "compile.overview.refuse_ungrounded",
                "An overview block in the call references no ledger claim and cites no source "
                "span; it names the slot and quotes the block.",
                "本次调用里某个总览块既没引账本断言，也没引来源区间；回复点名槽位并引用原文。",
            ),
            f(
                "compile.overview.refuse_definition_blocks",
                "The call's definition slot renders as more than one block — it is one "
                "sentence.",
                "本次调用的 definition 槽位渲染成不止一个块——它只有一句话。",
            ),
            f(
                "compile.overview.refuse_definition_length",
                "The call's definition is over its own character limit.",
                "本次调用的 definition 超出它自己的字符上限。",
            ),
            f(
                "compile.overview.refuse_dead_connection",
                "A connection in the call links to a document that does not exist in the "
                "draft.",
                "本次调用里某条 connection 链接到草稿中并不存在的文档。",
            ),
            f(
                "compile.overview.refuse_self_connection",
                "A connection in the call links to the document being rewritten.",
                "本次调用里某条 connection 链接到正在被重写的这份文档自己。",
            ),
            f(
                "compile.overview.refuse_missing",
                "Refuses `finish_compile` while a document this round wrote holds more "
                "ledger claims than the threshold and still has no overview definition.",
                "本轮写过的某份文档账本断言数已过阈值、却仍没有总览 definition 时，"
                "`finish_compile` 被拒。",
            ),
            f(
                "compile.patch.read_missing",
                "`read_document` on a path that does not exist.",
                "`read_document` 读了一个不存在的路径。",
            ),
            f(
                "compile.patch.create_path_not_allowed",
                "`create_document` outside the contract's ownership templates; the reply lists "
                "the allowed ones.",
                "`create_document` 落在契约归属模板之外；回复会列出允许的模板。",
            ),
            f(
                "compile.patch.create_exists",
                "`create_document` on a path that already exists, and it names the two tools to "
                "use instead.",
                "`create_document` 的路径已经存在，并指出该改用哪两个工具。",
            ),
            f(
                "compile.patch.move_target_missing",
                "`move_claim` into a document that has not been created yet.",
                "`move_claim` 的目标文档还没被创建。",
            ),
            f(
                "compile.patch.fields_refused",
                "Refuses a `set_fields` / `rewrite_overview` whose structured fields an index "
                "component can prove wrong, naming every failing value at once.",
                "拒绝 `set_fields` / `rewrite_overview` 里被索引组件证伪的结构化字段，一次点名"
                "每一个不合格的值。",
            ),
            f(
                "compile.patch.set_fields_reserved",
                "Refuses `set_fields` on a system-owned frontmatter field (doc_id / type / "
                "slug / title), and says that `title` derives from the document's `# ` "
                "heading.",
                "拒绝对系统持有的前置字段（doc_id / type / slug / title）调用 `set_fields`，"
                "并说明 `title` 由文档的 `# ` 标题派生。",
            ),
            f(
                "compile.patch.volume_frozen",
                "Any write against a frozen history volume, whichever tool attempted it.",
                "任何针对冻结历史卷的写入，无论是哪个工具发起的。",
            ),
            f(
                "compile.patch.claim_superseded",
                'Any rewrite of a claim that already has a successor: it is frozen history, and the reply names the successor.',
                '任何对已有后继的断言的改写：它属于冻结历史，回复会点明其后继。',
            ),
            f(
                "compile.patch.delete_supersession_target",
                "`delete_claim` (evolve) on a claim some successor supersedes: merging it away would dangle the link.",
                "`delete_claim`（evolve）删的是某条后继所取代的断言：合并掉它会让链接悬空。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="feedback.groom_gate",
        group="feedback",
        title_en="Rollover gate refusals",
        title_zh="归档闸门拒绝",
        summary_en=(
            "Recorded on the job rather than fed back: a rollover has no repair round. "
            "Any violation abandons the whole rollover and leaves the document untouched."
        ),
        summary_zh=(
            "记在作业上而不是喂回模型：归档没有修复回合。任何违规都会放弃整次归档，"
            "文档原样不动。"
        ),
        segments=(
            f(
                "gate.groom.claims_not_byte_equal",
                "When the volume plus the retained tail do not reproduce the original claim "
                "blocks byte for byte — a rollover moves text, it does not rewrite it.",
                "当归档卷加保留的尾部无法逐字节复现原来的断言块时——归档只搬文本，不重写文本。",
            ),
            f(
                "gate.groom.link_count_changed",
                "When the move would add or drop one of a claim's outgoing links.",
                "当这次搬迁会给某条断言增加或减少一条外链时。",
            ),
            f(
                "gate.groom.link_target_changed",
                "When a link's re-rendered relative form would point somewhere else.",
                "当某条链接被重新渲染后的相对写法指向了别处时。",
            ),
            f(
                "gate.groom.dead_links_increased",
                "When the rollover would cost the knowledge graph an edge.",
                "当这次归档会让知识图谱丢掉一条边时。",
            ),
            f(
                "gate.groom.heal_not_byte_equal",
                "When the follow-up link heal changed any byte other than a link target.",
                "当后续的链接修复改动了除链接目标以外的任何字节时。",
            ),
            f(
                "gate.groom.heal_repaired_nothing",
                "When a heal did not lower the unresolvable-link count, so it has no business "
                "writing a commit.",
                "当一次修复并没有降低失效链接数时——那它就没有理由写下一个提交。",
            ),
            f(
                "gate.groom.anchor_lost",
                "When an anchor would disappear from the knowledge base.",
                "当某个锚点会从知识库里消失时。",
            ),
            f(
                "gate.groom.anchor_added",
                "When the rollover would invent an anchor; only the new history card's own ids "
                "may be created here.",
                "当这次归档会凭空造出一个锚点时；这里只允许创建新历史卡片自己的 id。",
            ),
            f(
                "gate.groom.overview_without_reference",
                "When a point of the history card cites no archived entry — an uncited assertion "
                "in the one layer that is not rebuildable.",
                "当历史卡片里的某个要点没有引用任何归档条目时——那是在唯一不可重建的层里写了无依据断言。",
            ),
            f(
                "gate.groom.overview_unknown_reference",
                "When such a point references an id that is not an archived entry of this "
                "document.",
                "当某个要点引用的 id 并不是这份文档的归档条目时。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="feedback.evolve_gate",
        group="feedback",
        title_en="Evolve gate rejections",
        title_zh="演进闸门拒绝",
        summary_en=(
            "The reorganization's own mechanical checks: citations must still resolve, "
            "and every path must belong to the new skill's ownership templates."
        ),
        summary_zh=(
            "重组自己的机械检查：引用仍然要能解析，每条路径都要落在新契约的归属模板里。"
        ),
        segments=(
            f(
                "gate.evolve.feedback_header",
                "Opens every evolve rejection and names the repair route.",
                "每次演进拒绝都以它开头，并指出修复通道。",
            ),
            f(
                "gate.evolve.citation_unknown_source",
                "When a moved claim's citation names a source that is not in the store at all "
                "— the whole store, not just this round's material.",
                "当被搬迁断言的引用指向存储中根本不存在的材料时——这里比对的是整个存储，不只是本轮材料。",
            ),
            f(
                "gate.evolve.citation_out_of_range",
                "When a moved claim's citation span falls outside that source's block count.",
                "当被搬迁断言的引用区间超出该材料的块数时。",
            ),
            f(
                "gate.evolve.path_not_owned",
                "When a claim was filed outside the NEW contract's ownership templates.",
                "当断言被归到新契约的归属模板之外时。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    # ─────────────────────────────────────────────────────────────────────── eval
    Surface(
        id="eval.answer_judge",
        group="eval",
        title_en="Answer judge",
        title_zh="回答评判",
        summary_en=(
            "The evaluation package's optional answer-grading arm (full mode only). Its "
            "mechanical mode emits no model-visible prose at all."
        ),
        summary_zh=(
            "评测包可选的回答判分臂（只在 full 模式下）。它的机械模式完全不产生模型可见文案。"
        ),
        segments=(
            f(
                "eval.qa.judge_system",
                "The SystemMessage of one grading call, only in the evaluation package's full "
                "mode — never on any knowledge path.",
                "一次判分调用的系统消息，只出现在评测包的 full 模式里——绝不出现在任何知识路径上。",
            ),
            f(
                "eval.qa.judge_user",
                "Its HumanMessage: the question, the expected statement, and the answer under "
                "grading.",
                "它的人类消息：问题、期望陈述，以及被判分的回答。",
            ),
            f(
                "eval.qa.judge_verdict_yes",
                "The exact token counted as a pass — the verdict is read mechanically, so this "
                "string IS the scoring rule.",
                "被算作通过的那个确切标记——判决是机械读取的，所以这个字符串本身就是计分规则。",
            ),
        ),
        kind=FRAGMENTS,
    ),
    Surface(
        id="eval.claim_judge",
        group="eval",
        title_en="Claim judge",
        title_zh="断言评判",
        summary_en=(
            "Grades a CANONICAL CLAIM against a labelled fact — a claim is written for a "
            "reader, not for a question, which is why it gets its own prose."
        ),
        summary_zh=(
            "拿一条正本断言去比对一个标注事实——断言是写给读者的、不是写给问题的，"
            "所以它有自己的文案。"
        ),
        segments=(
            f(
                "eval.truth_judge.system",
                "The SystemMessage of one claim-grading call, in the evaluation package only.",
                "一次断言判分调用的系统消息，只在评测包里出现。",
            ),
            f(
                "eval.truth_judge.user",
                "Its HumanMessage: the labelled fact, and the claim being checked against it.",
                "它的人类消息：标注事实，以及被拿来比对的那条断言。",
            ),
            f(
                "eval.truth_judge.verdict_yes",
                "The exact token counted as a match; the verdict is read mechanically.",
                "被算作命中的那个确切标记；判决是机械读取的。",
            ),
        ),
        kind=FRAGMENTS,
    ),
)


# ═══════════════════════════════════════════════════════════════════ query + render


def surface_by_id(surface_id: str) -> Surface:
    for surface in SURFACES:
        if surface.id == surface_id:
            return surface
    raise KeyError(f"unknown prompt surface: {surface_id!r}")


def surface_keys(surface: Surface) -> tuple[str, ...]:
    """Every catalog key this surface holds, in declaration order."""
    return tuple(segment.key for segment in surface.segments)


def iter_segments() -> Iterator[tuple[Surface, Segment]]:
    for surface in SURFACES:
        for segment in surface.segments:
            yield surface, segment


def shared_with(surface_id: str, key: str) -> tuple[str, ...]:
    """The OTHER surfaces that also hold `key` — what "editing this moves four prompts"
    is made of. The spine and its two injected clauses are the whole reason this exists."""
    return tuple(
        other.id
        for other in SURFACES
        if other.id != surface_id and key in surface_keys(other)
    )


def _segments_by_key(surface: Surface) -> dict[str, Segment]:
    return {segment.key: segment for segment in surface.segments}


def _resolve(key: str, catalog: Mapping[str, str] | None) -> str:
    """One catalog key's effective template.

    `catalog=None` means "whatever this process resolves", i.e. `prompt()` — that is the
    path the byte pin compares against the real composition functions. A supplied mapping
    is a deployment's own resolution (defaults + its engine directory's overlays), which
    is what the console renders without registering anything into this process.
    """
    if catalog is None:
        return prompt(key)
    try:
        return catalog[key]
    except KeyError:
        raise KeyError(f"unknown prompt key: {key!r}") from None


def _render_segment(
    segment: Segment,
    by_key: Mapping[str, Segment],
    catalog: Mapping[str, str] | None,
    fields: Mapping[str, str],
) -> str:
    template = _resolve(segment.key, catalog)
    values: dict[str, str] = {}
    for slot in segment.slots:
        parts = []
        for key in slot.keys:
            filler = by_key.get(key)
            if filler is None:
                raise KeyError(
                    f"segment {segment.key!r} fills {{{slot.name}}} from {key!r}, which is "
                    "not a segment of this surface"
                )
            parts.append(_render_segment(filler, by_key, catalog, fields))
        values[slot.name] = slot.join.join(parts)
    for name in template_fields(template):
        if name not in values and name in fields:
            values[name] = fields[name]
    return substitute(template, values) if values else template


def render_surface(
    surface: Surface,
    *,
    catalog: Mapping[str, str] | None = None,
    fields: Mapping[str, str] | None = None,
) -> str:
    """Assemble a surface: its block segments in order, with their slots filled.

    Placeholders the framework fills from runtime data are left literal unless `fields`
    names them — the console wants `{question}` visible as a chip, and the byte pin
    supplies exactly what the real composition function would.

    A `fragments` surface has no assembled form and this refuses to fabricate one. That
    refusal is the whole fix for "the ownera conversationThis is…": the concatenation is
    not available to be shown, in the studio or anywhere else.
    """
    if surface.kind == FRAGMENTS:
        raise ValueError(
            f"{surface.id!r} is a fragment family, not an assembly: its clauses reach the "
            "model one at a time, so there is no assembled text to render"
        )
    by_key = _segments_by_key(surface)
    supplied = dict(fields or {})
    out: list[str] = []
    for segment in surface.segments:
        if segment.role != BLOCK:
            continue
        out.append(substitute(segment.prefix, supplied))
        out.append(_render_segment(segment, by_key, catalog, supplied))
        out.append(substitute(segment.suffix, supplied))
    return "".join(out)


def segment_context(segment: Segment) -> dict[str, str] | None:
    """This clause's bilingual "when is it used", or None when its position says it.

    None is not a hole: a block of an assembled surface is explained by standing where it
    stands. Fragments and variants have no such position, and `segments_missing_context`
    is the test that says so.
    """
    if not segment.context_en or not segment.context_zh:
        return None
    return {"en": segment.context_en, "zh": segment.context_zh}


def segments_missing_context() -> tuple[tuple[str, str], ...]:
    """(surface id, key) for every clause that owes a context sentence and has none.

    Owed by every clause of a fragment family and by every variant anywhere — the two
    cases where a reader cannot infer "when does the model see this" from the layout.
    """
    return tuple(
        (surface.id, segment.key)
        for surface, segment in iter_segments()
        if (surface.kind == FRAGMENTS or segment.role == VARIANT)
        and segment_context(segment) is None
    )


def surface_note(surface: Surface) -> dict[str, str] | None:
    """This surface's bilingual "what you are looking at is a template" banner, or None.

    None means the assembled bytes are the message: no runtime substitution, no clause the
    deployment picks between. The console may then say the preview is what the model
    receives — and must not say it whenever this returns a sentence.
    """
    if not surface.note_en or not surface.note_zh:
        return None
    return {"en": surface.note_en, "zh": surface.note_zh}


def variant_keys(surface: Surface) -> tuple[str, ...]:
    """The clauses of `surface` that some knob or caller state picks INSTEAD of a rendered
    one. A surface with any of these renders one branch, so the preview is a branch."""
    return tuple(
        segment.key for segment in surface.segments if segment.role == VARIANT
    )


def surfaces_missing_note(runtime_fields: Mapping[str, bool]) -> tuple[str, ...]:
    """Assembled surfaces that owe a note and have none — the note pin's failure message.

    `runtime_fields` maps surface id → "its byte pin had to supply runtime values", which
    only the pin table knows. A surface owes a note when that is true, or when it declares a
    variant: both mean the rendered bytes are one resolution of a template rather than the
    message itself.
    """
    return tuple(
        surface.id
        for surface in SURFACES
        if surface.kind == ASSEMBLED
        and (runtime_fields.get(surface.id) or variant_keys(surface))
        and surface_note(surface) is None
    )


def covered_keys() -> frozenset[str]:
    """Every catalog key that belongs to at least one surface."""
    return frozenset(segment.key for _, segment in iter_segments())


def uncovered_keys() -> tuple[str, ...]:
    """Catalog keys no surface holds — the coverage pin's failure message, sorted."""
    return tuple(sorted(set(DEFAULTS) - covered_keys()))

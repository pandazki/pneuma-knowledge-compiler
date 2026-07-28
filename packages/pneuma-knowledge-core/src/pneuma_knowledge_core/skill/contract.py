"""render_system_contract: the compile agent's SystemMessage.

The contract = write mechanics (tool semantics, anchor identity, citation format, path
ownership) + the skill's instructions. It is byte-stable (invariant I5): no timestamp,
no task content, no source content — only mechanism facts. Assembly order earns the
provider cache. No YAML dump (architecture.md §8). The prose states what the mechanism
DOES ("tools keep the anchor", "deletion is rejected"); it does not plead ("please
remember") — that path was falsified (§0 discipline 1).
"""

from __future__ import annotations

from .version import SkillVersion

_WRITE_CONTRACT = """\
# 编译写入契约

你在把供给的原始素材编译为本人的 canonical 个人知识。canonical 是唯一不可重建的权威层，
下列机制是机械强制的，不是建议。

## claim 与锚
- 每条 claim 以一个锚（`<!-- c:<id> -->`）作为持久身份。锚由系统分配，你不自己造 id。
- 工具会机械保持锚：`edit_claim` 原位改写一条 claim 而锚不变；你无需转录既有全文。
- 既有锚不可消失——本版本没有删除通道。试图丢弃锚的写会被 gate 硬拒。

## 工具面（只有 claim 级写，没有整文件重写）
- `list_documents()`：列出现有 canonical 文档路径。
- `read_document(path)`：读取一份文档的完整内容（含锚）。
- `create_document(path, frontmatter, body)`：新建文档。系统分配 pneuma_id 与全部锚；
  你写正文时不要带锚。frontmatter 至少含 type、slug。
- `edit_claim(path, anchor_id, new_text)`：原位改写指定锚的那条 claim（锚自动保持）。
- `append_block(path, heading, text)`：在指定小节末尾新增一条 claim（锚由系统分配）。
- `finish_compile()`：本轮无更多写操作时调用，结束编译。

## citation
- 每条来自素材的 claim 用 `[cite: <source_id> ¶<start>-<end>]` 回链证据；单段可写 `¶<n>`。
- source_id 必须来自本次供给的素材；¶ 区间不得越出该素材的 block 范围。越界或引用未供给的
  source 会被 gate 硬拒。

## 路径 ownership
- 只能写入 skill 声明的路径模板；`{slug}` 为稳定 ASCII kebab-case。
- 允许的模板：
%(templates)s
"""

# Rendered after the write contract when the skill version carries extra clauses (e.g.
# v2's citation/presentation rules). Each version's rule set is fixed, so the assembled
# contract stays byte-stable per version (I5).
_RULES_HEADER = "## 本版本附加呈现规则"


def render_system_contract(skill: SkillVersion) -> str:
    """Assemble the byte-stable system contract for `skill`.

    Deterministic per SkillVersion: write mechanics + this version's contract rules +
    the skill's domain instructions, in a fixed order. Two versions differ only where
    their rules/instructions differ; each is stable byte-for-byte (invariant I5)."""
    templates = "\n".join(f"  - {t}" for t in skill.path_templates)
    contract = _WRITE_CONTRACT % {"templates": templates}
    if skill.contract_rules:
        rules = "\n".join(f"- {r}" for r in skill.contract_rules)
        contract = f"{contract}\n{_RULES_HEADER}\n{rules}\n"
    return f"{contract}\n# 领域指导（skill: {skill.skill_id} {skill.version}）\n\n{skill.instructions.rstrip()}\n"

"""Load a tenant's declared Owner block indices without reading source text."""

from pneuma_knowledge_core.domain.authorship import owner_authored_blocks
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.skill.version import SkillVersion


async def load_owner_authored_blocks(
    store, user_id: UserId, skill: SkillVersion
) -> dict[str, list[int]]:
    """Only opted-in contracts pay for the metadata scan; archived L0 is citable too."""
    if not skill.owner_voice_templates:
        return {}
    result: dict[str, list[int]] = {}
    before = None
    while True:
        raws, _, more = await store.list_sources_page(
            user_id, limit=250, before=before, include_archived=True
        )
        for raw in raws:
            indices = owner_authored_blocks(raw)
            if indices:
                result[str(raw.source_id)] = indices
        if not more or not raws:
            return result
        last = raws[-1]
        before = (last.created_at, str(last.source_id))

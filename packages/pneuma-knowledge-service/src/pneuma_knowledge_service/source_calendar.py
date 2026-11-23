"""Calendar days recorded by the conversation adapters in the subject's timezone."""

from datetime import date

from pneuma_knowledge_core.domain.source import StructureMap


def section_days(structure: StructureMap) -> list[str]:
    days = set()
    for section in structure.sections:
        path = section.path
        if not path:
            continue
        try:
            day = date.fromisoformat(path[0])
        except ValueError:
            continue
        if day.isoformat() == path[0]:
            days.add(path[0])
    return sorted(days)

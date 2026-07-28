from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.recall.briefing import Briefing, assemble_messages


def _briefing() -> Briefing:
    return Briefing(
        user_id=UserId("u-1"),
        snapshot=SnapshotRef(ref="deadbeef", label="v1"),
        system_prefix="KNOWLEDGE PACK\nline two\n",
        tool_names=("l0_fetch", "l1_search"),
    )


def test_system_message_byte_stable_across_as_of():
    briefing = _briefing()
    msgs_a = assemble_messages(
        briefing, "what did I decide?", as_of=datetime(2026, 1, 1, 9, 0, 0)
    )
    msgs_b = assemble_messages(
        briefing, "what did I decide?", as_of=datetime(2026, 7, 20, 18, 30, 0)
    )

    sys_a, sys_b = msgs_a[0], msgs_b[0]
    assert isinstance(sys_a, SystemMessage)
    assert isinstance(sys_b, SystemMessage)
    # Byte-for-byte identical System content despite different as_of (I5).
    assert sys_a.content == sys_b.content == briefing.system_prefix


def test_as_of_only_in_human_message():
    briefing = _briefing()
    as_of = datetime(2026, 3, 15, 12, 0, 0)
    msgs = assemble_messages(briefing, "when is the meeting?", as_of=as_of)

    sys, human = msgs
    assert isinstance(human, HumanMessage)
    assert as_of.isoformat() not in sys.content
    assert as_of.isoformat() in human.content
    assert "when is the meeting?" in human.content


def test_message_order_system_then_human():
    msgs = assemble_messages(_briefing(), "q", as_of=datetime(2026, 1, 1))
    assert [type(m) for m in msgs] == [SystemMessage, HumanMessage]

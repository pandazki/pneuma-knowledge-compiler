"""Synthetic source-clock ranking, replay, provenance and tenant boundaries."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, StructureMap
from pneuma_knowledge_core.recall.speech_activity import activity_score, rank, source_mentions
from pneuma_knowledge_core.recall.speech_lexicon import render
from pneuma_knowledge_service.call.speech_activity import activity_path, read_activity, refresh_activity
from pneuma_knowledge_service.call.speech_lexicon import vocabulary

TODAY = date(2026, 9, 22)


def source(sid='s1', *, user='alice', days=('2026-09-22',), texts=('Lyrra arrived.',), archived=False):
    return NormalizedSource(
        raw=RawSource(source_id=SourceId(sid), user_id=UserId(user), kind='im', title='Synthetic names',
            mime='text/plain', checksum=sid, created_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
            archived_at=datetime(2026, 9, 22, tzinfo=timezone.utc) if archived else None,
            meta={'messages': [{'sent_at': day + 'T12:00:00Z' if day else None} for day in days]}),
        blocks=[NormalizedBlock(index=i, text=t) for i, t in enumerate(texts)], structure=StructureMap())


def document(path='topics/lyrra.md', body='Lyrra arrived. [cite: s1 ¶0] <!-- c:aaaa -->', terms=('Lyrra',)):
    return CanonicalDocument(doc_id=path, path=path, body=body, frontmatter={'speech_terms': list(terms)})


class Content:
    def __init__(self, *sources):
        self.sources = {(str(s.raw.user_id), str(s.raw.source_id)): s for s in sources}
        self.calls = []
        self.archived = frozenset()

    async def archived_source_ids(self, user_id):
        return self.archived

    async def get(self, user_id, source_id):
        self.calls.append((str(user_id), str(source_id)))
        return self.sources[(str(user_id), str(source_id))]


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(engine_dir=str(tmp_path), canonical_root='unused')


def test_decay_daily_cap_unknown_future_and_real_exit():
    assert activity_score({'s1': ['2026-09-22']}, today=TODAY) == 1
    assert activity_score({'s1': ['2026-07-24']}, today=TODAY) == .5
    assert activity_score({'s1': ['2026-05-25']}, today=TODAY) == .25
    assert activity_score({'s1': ['2026-05-24']}, today=TODAY) < .25
    assert activity_score({str(i): ['2026-09-22'] for i in range(50)}, today=TODAY) == 3
    assert activity_score({'s1': ['2026-07-24', '2026-09-22', '2026-12-01']}, today=TODAY) == 1
    assert activity_score({'s1': ['2026-12-01']}, today=TODAY) == 0
    assert activity_score({'s1': []}, today=TODAY) == .25
    assert activity_score({'s1': ['2026-05-24'], 'unknown': []}, today=TODAY) < .25
    assert rank([{'term': 'Lyrra'}], {'lyrra': {'s1': ['2026-05-24']}}, today=TODAY) == []


def test_only_actual_mentions_in_cited_blocks_supply_dates():
    data = source(days=('2026-05-24', '2026-09-22'), texts=('Lyrra arrived.', 'Unrelated recent content.'))
    assert source_mentions(data, ['Lyrra', 'Invented'], [(0, 1), (0, 0)]) == {'lyrra': ['2026-05-24']}
    assert source_mentions(data, ['Lyrra'], [(1, 1)]) == {}
    assert source_mentions(source(archived=True), ['Lyrra'], [(0, 0)]) == {}
    assert source_mentions(source(days=(None,)), ['Lyrra'], [(0, 0)]) == {'lyrra': []}
    # Case normalization does not invent a substring spelling.
    assert source_mentions(source(texts=('LYRRA is here.',)), ['Lyrra', 'yrra'], [(0, 0)]) == {'lyrra': ['2026-09-22']}


async def test_repeated_claims_and_pages_share_one_vote_and_do_not_write_canonical(settings):
    docs = [document(), document('topics/copy.md', 'Lyrra arrived. [cite: s1 ¶0] <!-- c:bbbb -->')]
    before = [d.model_dump() for d in docs]
    content = Content(source())
    await refresh_activity(settings, 'alice', docs, content)
    assert content.calls == [('alice', 's1')]
    first = activity_path(settings, 'alice').read_bytes()
    await refresh_activity(settings, 'alice', docs, content)
    assert content.calls == [('alice', 's1')]
    await refresh_activity(settings, 'alice', docs, content, force=True)
    assert activity_path(settings, 'alice').read_bytes() == first
    assert [d.model_dump() for d in docs] == before
    assert 'Lyrra' in vocabulary(settings, 'alice', docs, today=TODAY)
    assert vocabulary(settings, 'alice', docs, today=date(2027, 1, 21)) == ''
    # Another tenant cannot inherit Alice's old dates, even if the file was copied.
    activity_path(settings, 'bob').write_bytes(first)
    assert read_activity(settings, 'bob')['documents'] == {}


async def test_unrelated_new_claim_and_recompile_do_not_renew_but_new_mention_does(settings):
    old = source(days=('2026-05-24',))
    newer = source('s2', texts=('Only a scheduling update.',))
    content = Content(old, newer)
    doc = document()
    await refresh_activity(settings, 'alice', [doc], content)
    assert vocabulary(settings, 'alice', [doc], today=TODAY) == ''
    doc.body += '\n\nScheduling changed. [cite: s2 ¶0] <!-- c:bbbb -->'
    # A committed page awaiting projection cannot become fresh by losing its old digest.
    assert vocabulary(settings, 'alice', [doc], today=TODAY) == ''
    await refresh_activity(settings, 'alice', [doc], content)
    assert vocabulary(settings, 'alice', [doc], today=TODAY) == ''
    new_mention = source('s3', texts=('Lyrra is relevant again.',))
    content.sources[('alice', 's3')] = new_mention
    doc.body += '\n\nLyrra is relevant again. [cite: s3 ¶0] <!-- c:cccc -->'
    await refresh_activity(settings, 'alice', [doc], content)
    assert 'Lyrra' in vocabulary(settings, 'alice', [doc], today=TODAY)


async def test_archive_clear_and_identity_mismatch(settings):
    content = Content(source())
    await refresh_activity(settings, 'alice', [document()], content)
    assert vocabulary(settings, 'alice', [document('archive/lyrra.md')], today=TODAY) == ''
    assert vocabulary(settings, 'alice', [document(terms=())], today=TODAY) == ''
    before = activity_path(settings, 'alice').read_bytes()
    content.sources[('alice', 's1')] = source(user='bob')
    with pytest.raises(ValueError, match='identity'):
        await refresh_activity(settings, 'alice', [document()], content, force=True)
    assert activity_path(settings, 'alice').read_bytes() == before


async def test_rank_wins_over_old_maintained_priority_and_budget_is_retained(settings):
    older = source(days=('2026-07-24',))
    newer = source('s2', texts=('Velora arrived.',))
    docs = [document(), document('topics/velora.md', 'Velora arrived. [cite: s2 ¶0] <!-- c:bbbb -->', ('Velora',))]
    await refresh_activity(settings, 'alice', docs, Content(older, newer))
    text = vocabulary(settings, 'alice', docs, today=TODAY)
    assert text.index('Velora') < text.index('Lyrra')
    rows = rank([{'term': 'Lyrra', 'reason': 'maintained', 'risk': 3}, {'term': 'Velora', 'risk': 1}],
                {'lyrra': {'s1': ['2026-07-24']}, 'velora': {'s2': ['2026-09-22']}}, today=TODAY)
    assert 'Velora' in render(rows, max_terms=1, preserve_order=True)
    assert len(render(rows, max_chars=70, preserve_order=True)) <= 70


async def test_unknown_dates_and_missing_historical_source_do_not_use_ingestion_clock(settings):
    content = Content(source(days=(None,)))
    await refresh_activity(settings, 'alice', [document()], content)
    # Timeless reserve stays low priority; a future as_of cannot fabricate its age.
    assert 'Lyrra' in vocabulary(settings, 'alice', [document()], today=date(2099, 1, 1))
    await refresh_activity(settings, 'alice', [document()], Content(), force=True)
    assert 'Lyrra' in vocabulary(settings, 'alice', [document()], today=TODAY)


async def test_failed_refresh_is_atomic_and_unchanged_retries_do_not_double_count(settings):
    content = Content(source())
    await refresh_activity(settings, 'alice', [document()], content)
    previous = activity_path(settings, 'alice').read_bytes()

    async def broken(*args):
        raise RuntimeError('source store unavailable')

    content.get = broken
    with pytest.raises(RuntimeError):
        await refresh_activity(settings, 'alice', [document()], content, force=True)
    assert activity_path(settings, 'alice').read_bytes() == previous


async def test_missing_source_is_retried_on_next_incremental_refresh(settings):
    content = Content()
    await refresh_activity(settings, 'alice', [document()], content)
    assert 'Lyrra' in vocabulary(settings, 'alice', [document()], today=TODAY)
    content.sources[('alice', 's1')] = source(days=('2026-05-24',))
    await refresh_activity(settings, 'alice', [document()], content)
    assert vocabulary(settings, 'alice', [document()], today=TODAY) == ''


async def test_optional_refresh_failure_does_not_fail_knowledge_projection(settings, monkeypatch, caplog):
    from pneuma_knowledge_service import projection
    from pneuma_knowledge_service.call import speech_activity

    async def broken(*args, **kwargs):
        raise OSError('derived path unavailable')

    monkeypatch.setattr(speech_activity, 'refresh_activity', broken)
    await projection._speech_activity(SimpleNamespace(settings=settings, store=Content()), UserId('alice'), [document()])
    assert 'next sync/rebuild will retry' in caplog.text



def test_decay_does_not_promote_hidden_legacy_hints_but_compile_can_admit_new_names():
    import json
    from pneuma_knowledge_core.recall.speech_lexicon import key

    rows = [{'term': f'Lyrra-{i:03d}', 'reason': 'coined', 'risk': 1} for i in range(100)]
    before = {key(r['term']) for r in json.loads(render(rows))}
    omitted = next(r['term'] for r in rows if key(r['term']) not in before)
    mentions = {key(r['term']): {'old': ['2026-05-24']} for r in rows}
    mentions[key(omitted)] = {'new': ['2026-09-22']}
    # A hot historical-cache hint is still outside the old admission boundary.
    assert rank(rows, mentions, today=TODAY) == []
    # Normal compilation can independently admit the same spelling as page metadata.
    compiled = {'term': omitted, 'reason': 'maintained', 'risk': 3}
    admitted = rank([*rows, compiled], mentions, today=TODAY)
    assert compiled in admitted
    assert {row['term'] for row in admitted} == {omitted}

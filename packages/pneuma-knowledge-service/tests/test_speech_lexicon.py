"""Synthetic lexicon scenarios: admission, persistence, freshness and tenant isolation."""
import json
from types import SimpleNamespace

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.recall.speech_lexicon import ExtractedTerms, SpeechSelection, ProposedTerm, extract, render, maintained
from pneuma_knowledge_service.call.speech_lexicon import cache_path, read, rebuild, vocabulary, write


def doc(path="projects/lyrra.md", body="Lyrra is the coined name. A normal meeting follows.", **metadata):
    return CanonicalDocument(doc_id=path, path=path, body=body, frontmatter=metadata)


class Model:
    def __init__(self):
        self.calls = 0

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages, config=None):
        if self.schema is SpeechSelection:
            return SpeechSelection(terms=["Lyrra", "invented-name"])
        self.calls += 1
        return ExtractedTerms(terms=[
            ProposedTerm(term="Lyrra", reason="coined", risk=3),
            ProposedTerm(term="invented-name", reason="coined", risk=3),
            ProposedTerm(term="yrra", reason="acronym", risk=2),
        ])


async def test_model_cannot_invent_or_slice_latin_spelling():
    rows = await extract(Model(), doc())
    assert [r['term'] for r in rows] == ["Lyrra"]


def test_metadata_shape_dedup_and_ambiguous_confusions():
    rows = maintained(doc(speech_terms=[{"term": "Lyrra", "confusions": ["Lyra", "Lyra", "<instruction>"]}, "lyrra", "Lyra"]))
    rendered = json.loads(render(rows))
    assert len(rendered) == 2
    assert rendered[0] == {"term": "Lyrra", "confusions": []}
    assert maintained(doc(speech_terms={"bad": "shape"})) == []
    assert render(rows, max_chars=8) == ""


async def test_cached_pages_skipped_new_content_rescanned_and_tenants_isolated(tmp_path):
    settings = SimpleNamespace(engine_dir=str(tmp_path), canonical_root="unused")
    model = Model()
    first = doc()
    await rebuild(settings, "alice", [first], model, model_name="test", confusions={"Lyrra": ["leera"]})
    await rebuild(settings, "alice", [first], model, model_name="test")
    assert model.calls == 1
    assert 'leera' in vocabulary(settings, "alice", [first])
    assert vocabulary(settings, "bob", [first]) == ""
    assert vocabulary(settings, "alice", [doc(body="Only ordinary words remain.")]) == ""
    assert vocabulary(settings, "alice", [doc(path="archive/lyrra.md")]) == ""
    await rebuild(settings, "alice", [doc(body=first.body + " Updated.")], model, model_name="test")
    assert model.calls == 2
    # Reject a cache payload even if somebody copied it into another tenant's filename.
    write(cache_path(settings, "bob"), read(cache_path(settings, "alice"), "alice"))
    assert vocabulary(settings, "bob", [first]) == ""


async def test_failure_preserves_prior_snapshot_but_does_not_mark_new_page_complete(tmp_path):
    settings = SimpleNamespace(engine_dir=str(tmp_path), canonical_root="unused")
    await rebuild(settings, "a", [doc()], Model(), model_name="test")
    class Fails(Model):
        async def ainvoke(self, messages, config=None):
            raise RuntimeError("offline")
    before = read(cache_path(settings, "a"), "a")
    result = await rebuild(settings, "a", [doc(body="Lyrra changed.")], Fails(), model_name="test")
    assert result['failures']
    assert result['documents'] == before['documents']
    assert "Lyrra" in vocabulary(settings, "a", [doc(body="Lyrra changed.")])


def test_page_metadata_works_without_a_preprocessing_cache(tmp_path):
    settings = SimpleNamespace(engine_dir=str(tmp_path), canonical_root="unused")
    result = vocabulary(settings, "a", [doc(speech_terms=[{"term": "Lyrra", "confusions": ["leera"]}])])
    assert 'leera' in result


async def test_cross_page_selection_cannot_invent_terms_and_bounds_each_input():
    from pneuma_knowledge_core.recall.speech_lexicon import curate
    class Selector:
        def with_structured_output(self, schema):
            assert schema is SpeechSelection
            return self
        async def ainvoke(self, messages):
            candidates = json.loads(messages[1].content)
            assert len(candidates) <= 300
            return SpeechSelection(terms=[candidates[0]['term'], 'fabricated-name'])
    rows = [{'term': f'Lyrra-{i}', 'path': f'p{i}.md'} for i in range(601)]
    result = await curate(Selector(), rows)
    assert result == ['Lyrra-0']


def test_explicit_correction_survives_budget_even_without_model_selection(tmp_path):
    settings = SimpleNamespace(engine_dir=str(tmp_path), canonical_root='unused')
    write(cache_path(settings, 'a'), {'version': 1, 'user_id': 'a', 'documents': {},
          'selected_terms': [], 'confusions': {'Lyrra': ['leera']}})
    result = vocabulary(settings, 'a', [doc()])
    assert 'leera' in result
    assert vocabulary(settings, 'a', []) == ''


async def test_page_field_supersedes_legacy_cache_and_clear_is_authoritative(tmp_path):
    settings = SimpleNamespace(engine_dir=str(tmp_path), canonical_root='unused')
    await rebuild(settings, 'a', [doc()], Model(), model_name='test', confusions={'Lyrra': ['leera']})
    assert 'leera' in vocabulary(settings, 'a', [doc()])
    assert vocabulary(settings, 'a', [doc(speech_terms=[])]) == ''
    result = vocabulary(settings, 'a', [doc(speech_terms=['Lyrra'])])
    assert 'Lyrra' in result and 'leera' not in result
    assert vocabulary(settings, 'b', [doc(speech_terms=['Lyrra'])]) == result
    assert vocabulary(settings, 'a', [doc(path='archive/lyrra.md', speech_terms=['Lyrra'])]) == ''

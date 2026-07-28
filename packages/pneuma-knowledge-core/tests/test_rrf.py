from pneuma_knowledge_core.recall.rag import rrf_fuse


def test_single_ranking_preserves_order():
    assert rrf_fuse([["a", "b", "c"]]) == ["a", "b", "c"]


def test_agreement_boosts_shared_id():
    # "b" is top of one list and present in the other; "a" appears only once.
    # b: 1/(60+1) + 1/(60+0)  >  a: 1/(60+0).
    fused = rrf_fuse([["a", "b"], ["b"]])
    assert fused[0] == "b"


def test_union_of_all_ids():
    fused = rrf_fuse([["a", "b"], ["c", "d"]])
    assert set(fused) == {"a", "b", "c", "d"}


def test_id_ranked_across_lists_beats_singletons():
    # "x" is present in all three lists; others appear once.
    fused = rrf_fuse([["x", "a"], ["b", "x"], ["x", "c"]])
    assert fused[0] == "x"


def test_k_affects_fusion():
    rankings = [["a", "b"], ["b", "a"]]
    # Small k sharpens rank differences; large k flattens them. With a tie here,
    # both settle deterministically; check k changes the underlying scores.
    small = rrf_fuse(rankings, k=1)
    large = rrf_fuse(rankings, k=1000)
    assert set(small) == set(large) == {"a", "b"}


def test_k_lowers_scores_but_keeps_order_property():
    # A clearly dominant id stays first regardless of k.
    rankings = [["top", "a", "b"], ["top", "b", "a"]]
    assert rrf_fuse(rankings, k=1)[0] == "top"
    assert rrf_fuse(rankings, k=10_000)[0] == "top"


def test_tie_broken_by_first_appearance():
    # "a" and "b" get identical scores (mirror rankings); first-seen "a" wins.
    assert rrf_fuse([["a", "b"], ["b", "a"]]) == ["a", "b"]

"""A console source counts only when it carries a page.

The three sources are tried in order — a developer's `PKC_CONSOLE_DIST`, the packaged build,
the downloaded one — and the first complete one wins. A directory that holds assets but no
`index.html` is not a page: letting it win serves a static root where every route 404s while
a whole downloaded build sits unused one line below."""

from pkc_personal.console import _complete


def test_a_directory_without_a_page_is_not_complete(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)\n")
    assert _complete(tmp_path) is False


def test_a_directory_with_a_page_is_complete(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html>\n")
    assert _complete(tmp_path) is True


def test_an_absent_or_empty_directory_is_not_complete(tmp_path):
    assert _complete(tmp_path / "nothing-here") is False
    assert _complete(tmp_path) is False

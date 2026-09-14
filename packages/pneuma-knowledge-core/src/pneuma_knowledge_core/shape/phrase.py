"""One rendered sentence, and the bound on what may be shown beside it.

Every sentence the check and the lens say is a prompt-catalog key with named fields, rendered
in both shipped packs at the source (docs/design/structure-lens.md §5.2). The key and the
fields stay the authority — a deployment that rewords a surface reworded it — and the
rendered pair travels beside them so no face keeps its own copy of these sentences. A copy
kept in a console is a copy that drifts, and the one that did drift had no placeholders at
all, so a finding read "This project is an island" and never said which project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..prompts import substitute
from ..prompts.catalog import DEFAULTS
from ..prompts.lang_zh import chinese_overlay

#: Evidence is bounded on both axes so a finding stays readable in a terminal and in a card.
MAX_EVIDENCE = 5
MAX_EVIDENCE_CHARS = 200

#: The Chinese pack, resolved once. `chinese_overlay()` hands out a fresh copy of ~800
#: entries per call by design (an overlay is registered into process state and a caller must
#: not be able to mutate the pack for everyone else); a reading over a real library renders
#: hundreds of phrases, and paying for that copy each time is a copy per sentence.
_ZH_PACK: dict[str, str] | None = None


def _zh_template(key: str) -> str | None:
    global _ZH_PACK
    if _ZH_PACK is None:
        _ZH_PACK = dict(chinese_overlay())
    return _ZH_PACK.get(key)


@dataclass(frozen=True)
class Phrase:
    """A catalog key, the fields it substitutes, and the sentence itself in both packs.

    Both texts are rendered from the SHIPPED templates — English from the catalog defaults,
    Chinese from the language pack — deliberately NOT through `prompt()`: whichever overlay a
    process happens to have registered is that process's answer for its own surfaces, and it
    must not decide what the OTHER language in this payload says. Substitution is the
    catalog's own narrow rule (`prompts.substitute`), so a template's literal braces survive
    exactly as they do everywhere else.
    """

    key: str
    fields: dict = field(default_factory=dict)

    def text(self) -> dict[str, str]:
        """`{"en": …, "zh": …}` — this sentence, rendered, in both shipped packs.

        A key the Chinese pack does not carry falls back to the English template rather than
        to an empty string: a missing translation is a sentence in the wrong language, which
        a reader can still act on, and the pack's totality is pinned by its own test.
        """
        english = DEFAULTS.get(self.key, "")
        chinese = _zh_template(self.key) or english
        fields = dict(self.fields)
        return {
            "en": substitute(english, fields) if english else "",
            "zh": substitute(chinese, fields) if chinese else "",
        }

    def to_dict(self) -> dict:
        return {"key": self.key, "fields": dict(self.fields), "text": self.text()}


def clip_evidence(items) -> tuple[str, ...]:
    """Verbatim library strings, whitespace-collapsed and bounded in both directions."""
    out = []
    for item in items:
        text = " ".join(str(item).split())
        out.append(text if len(text) <= MAX_EVIDENCE_CHARS else text[:MAX_EVIDENCE_CHARS])
    return tuple(out[:MAX_EVIDENCE])


__all__ = ["MAX_EVIDENCE", "MAX_EVIDENCE_CHARS", "Phrase", "clip_evidence"]

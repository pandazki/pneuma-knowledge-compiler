"""The `people` component: the first index component, and the reference for writing one.

WHAT IT ADDS (and what it deliberately does not)
------------------------------------------------
Canonical has no concept of a person — by design. This component binds to ONE contract
family (a path template, `memory/people/{slug}.md` by default) and gives its documents two
machine-readable frontmatter fields:

    identities: mailto:jianing@hengyin-print.example, im:u_8812
    aliases: 贾宁, 老贾

Both are comma-separated scalars (canonical frontmatter is a flat map of scalar strings). An
identity is `scheme:value`, the scheme coming from the source boundary (`mailto:`, `im:`,
`meeting:`), so the model never invents a scheme. From those fields, four faces:

Both are part of the document's OVERVIEW — its picture of the subject right now — and are
written whole by `rewrite_overview(fields=…)` / `set_fields`, exactly like the prose slots
beside them. Nothing here only grows: a snapshot's wrong entry is gone after the next
rewrite, which is the only reason a wrong one is repairable at all. Canonical records what is
KNOWN about a person, and nothing else — there is no field for what this person is not
called, because a page listing the names that are not somebody's is a page of distractions.
What the component adds is not ownership of the fields but the FACTS a write can be measured
against:

- gate + write face: an identity is `scheme:value` and at most one page in the library binds
  it (one email is one person — the write-time form of "one subject must not split into
  several pages"); two PERSON IDS that both SPEAK in one conversation are two people, so one
  page may not bind both (the failure the rule above cannot see: three ids lifted from a
  group's member list, the other two holding no page to collide with) — an IM `sender_id`
  and a meeting `speaker_id` are person ids, an email address is not, and `source_speakers`
  says why; an alias is not somebody else's name — not another person page's alias, title or
  slug, and not a display name the sources record for an identity this page does not hold,
  nor one they record for an identity that speaks beside this page's own (a group chat
  titled "Yong BAI, Jie WANG, Fan WANG" is three people). All three are judged over the
  pages a round TOUCHED — body or frontmatter, the framework's own predicate — so one old
  wrong page cannot block every later compile while no write of one escapes them, and all
  three are said twice: `validate_fields` before the round is spent, `gate_checks` as the
  final arbiter. A sixth kind stands behind all of them: `people.not_ready`, the refusal
  when the mirror those library-wide facts are read from could not be loaded at all;
- outline: the identities and aliases render under the page, so "does this subject already
  exist" is answered by lookup, not by the model's memory;
- compile tool `find_person(identity, alias)`: the same lookup, callable;
- fast-recall path `person(alias|identity)` (core recall/paths.py): chosen by the routing
  turn when the question names a person; returns that page's WHOLE record — current claims
  first, superseded history after, each labelled — as the fast lane's component face. Exact
  lookup, no ranking and no truncation: it has no question to rank against, so the framework
  orders the page against the question and spends the path's cap on that order
  (core recall/component_rank.py), which is why it is a face of its own, never enters the
  RRF, and never cuts a page at whatever document order happened to put first;
- deep-recall tools `enumerate_identities(since, until, offset, limit)` — the CLOSED
  candidate set: every external identity the user's L0 sources record in a date range, with
  how many sources, when, and which person page (if any) binds it (unbound identities are
  listed, not hidden: the residue of a "find everyone who…" question is visible by
  construction) — and `person_profile(alias, identity, section, offset, limit)`, one
  person's record in full. Both paginate and end every response with the exact call that
  fetches the rest: in an agentic lane a cap must never be a dead end.

Beside WHO is present, the component states HOW the turns CALL someone: `address_evidence`
reads a source's turn structure (who spoke, whom the turn addresses, who answers next) and
reports address terms as CANDIDATES with a support distribution over targets — never a
binding, because `@X 阿宝怎么样` names a third person. The rule set is turn structure only:
nothing in it is IM-specific, so a meeting, a mail thread and a plain conversation are read
by the same three signals. Those candidates accumulate into the component's PERSISTED
projection (`component_people_terms`, one row per term → target pair), and what is finally
reported is decided there, by concentration across the whole library rather than by a count
inside one conversation — see "the library-wide projection and its rule" below.

TWO VOCABULARIES, KEPT APART
----------------------------
So a person is addressable two ways, and the difference matters:

- `aliases` in frontmatter are CONFIRMATIONS. A compile read material about that person and
  ruled that the name is theirs, writing the field whole through the ordinary gate.
- a REPORTED address term is DERIVED — arithmetic over turn structure that nothing has
  ruled on yet.

The derived one is not canonical and never writes itself into canonical; a confirmation only
ever arrives the ordinary way, on a compile that naturally touches that person. But it is a
perfectly good way to RESOLVE A LOOKUP, so every READ face uses it as a second tier after
canonical, and says so where it does: `find_person` answers with the bound page plus
`(matched via library address term "周总": …)`, the fast `person` path labels the claims it
returns that way `via:address-term`, and `person_profile` prints the confirmed aliases and
the library's address terms on two separate lines. Canonical always wins the tie — a
confirmation is never overruled by a count.

The component holds structure and pointers only. Who is the same person is the contract's
judgement, written into frontmatter through the ordinary gate; this module merely reads it.
Identities are enumerated from `RawSource.meta` as the official source contracts wrote it
(ingest/canonical_sources.py) — meetings, IM archives and email threads; a source of any
other kind contributes nothing, and the enumeration itself is still computed on demand over
`ContentStore.list` (O(sources), derived, never cached as truth). The address terms are the
one thing that CANNOT be computed per query: a term's meaning is its distribution across the
whole library, so it is projected at index time into `component_people_terms` and read back
by the seams. Derived like everything else — `rebuild` re-derives the table from L0 alone,
and where no store is wired (tests, keyless offline checks) the same arithmetic runs in
memory and produces the same rows.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from pypinyin import lazy_pinyin
from pneuma_knowledge_core.canonical_glance import document_title, family_of
from pneuma_knowledge_core.compile.documents import parse_overview
from pneuma_knowledge_core.compile.gate import Violation
from pneuma_knowledge_core.compile.patch import touched_this_round
from pneuma_knowledge_core.components import BaseComponent
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import NormalizedSource, RawSource
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.ports.canonical_store import CanonicalStore
from pneuma_knowledge_core.ports.content_store import ContentStore
from pneuma_knowledge_core.recall.fast import RetrievedClaim
from pneuma_knowledge_core.recall.paths import PathResult
from pneuma_knowledge_core.recall.projection import project_document_claims
from pneuma_knowledge_core.compile.supersession import superseded_index

from .pagination import (
    PAGINATED_NOTE,
    PROFILE_PAGE_LIMIT,
    call_text as _call_text,
    navigation_line,
    section_counts,
)

_log = logging.getLogger(__name__)

IDENTITIES_KEY = "identities"
ALIASES_KEY = "aliases"
#: `scheme:value` — a lowercase scheme, then anything non-empty.
_IDENTITY_RE = re.compile(r"^[a-z][a-z0-9+.-]*:\S.*$", re.IGNORECASE)
_SPLIT_RE = re.compile(r"[,，]")

#: Enumeration output is bounded and SAYS so — a silent cap reads as "that was everyone".
ENUMERATE_MAX_LINES = 200


def split_csv(value: object) -> list[str]:
    """A frontmatter scalar → its comma-separated items (order kept, blanks dropped)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = _SPLIT_RE.split(str(value))
    out: list[str] = []
    for item in items:
        item = item.strip().strip("[]").strip().strip("'\"")
        if item:
            out.append(item)
    return out


def normalize_identity(identity: str) -> str:
    """Identity comparison key: scheme and value casefolded (emails and ids are compared
    case-insensitively; the stored spelling is left alone)."""
    return identity.strip().casefold()


def name_key(name: str) -> str:
    """Name comparison key: trimmed and casefolded. `Jie WANG`, `jie wang` and ` Jie
    Wang ` are one name — a collision the library can prove is a collision however it is
    spelled.

    STRICT, and it stays strict. Every rule that reads this key is about a FACT — this
    alias is already somebody else's name, these two pages hold one identity — and a fact
    that only nearly holds is not a collision. Matching a QUESTION to a page is the opposite
    problem and has its own key set below (`name_keys`): collisions are about facts,
    matching is about retrieval.
    """
    return name.strip().casefold()


# ------------------------------------------------------------- contact-book name matching
# What a contact book does, and what this lookup did not. A page titled `Kexin ZHOU`, bound
# to `im:Kexin ZHOU`, was unreachable by `可欣` — the form every colleague of his would
# actually type — because the exact key of one shares no character with the exact key of the
# other, and the answering model had to guess out loud ("if you mean 周可欣…"). Every address
# book solves this the same mechanical way: expand each name into a SET OF KEYS, expand the
# query the same way, and let the two sets meet.
#
#   Kexin ZHOU  →  kexin zhou · zhou kexin · kexin · zhou · kexinzhou · zhoukexin · kz · zk
#   周可欣      →  周可欣 · 周 · 可欣 · zhoukexin · kexinzhou · zhou kexin · kexin zhou ·
#                  zhou · kexin · zkx · kx
#
# The two scripts meet ON THE PINYIN — `kexin`, `zhoukexin`, `zhou kexin` are keys of both —
# which is what lets a Chinese question reach an English page and an English question reach a
# Chinese one, without either side storing the other's spelling.
#
# Nothing here is a similarity score and nothing is a threshold: every key is an exact string
# a name mechanically produces, so a match is explainable, reproducible, and carries the TIER
# it matched at out to the caller (`NameMatch`). Widening retrieval is safe in a way that
# widening `name_key` would not be — a lookup writes nothing, a wrong hit is a page the
# reader discards, and a miss is a person the library denies knowing.

#: 复姓 — the two-character surnames a given-name split must not cut through. Without them
#: `欧阳锋` splits as 欧 + 阳锋 and `锋`, the half a question actually uses, is never a key.
COMPOUND_SURNAMES = frozenset(
    {
        "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫", "万俟", "闻人",
        "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台", "皇甫", "宗政", "濮阳", "公冶",
        "太叔", "申屠", "公孙", "慕容", "仲孙", "钟离", "长孙", "宇文", "司徒", "鲜于",
        "司空", "闾丘", "子车", "亓官", "司寇", "巫马", "公西", "颛孙", "壤驷", "公良",
        "漆雕", "乐正", "宰父", "谷梁", "拓跋", "夹谷", "轩辕", "令狐", "段干", "百里",
        "呼延", "南门", "羊舌", "微生", "第五", "梁丘", "左丘", "东门", "西门", "宇文",
    }
)

#: Trailing forms of address a question carries and a page never spells, and the leading
#: familiars that go with them. Query-side only, and only as a SECOND attempt — see
#: `strip_honorific`.
HONORIFIC_SUFFIXES = ("姐姐", "老师", "老板", "同学", "总", "哥", "姐")
HONORIFIC_PREFIXES = ("小", "老", "阿")

#: How many pages tie on the best tier before the caller stops listing them. Ambiguity is
#: RETURNED — the reader decides which 可欣 they meant — but a list is not an answer either.
NAME_MATCH_CANDIDATES = 3

#: A query key shorter than this never matches as a PREFIX. Two characters is the floor in
#: both scripts: it keeps `周` a surname key that matches `周` exactly and nothing else,
#: rather than the prefix of every 周 in the library.
PREFIX_MIN_CHARS = 2

#: Content-addressed page keys are never stale, only unbounded — this is the ceiling.
NAME_KEY_CACHE_MAX = 4096

_NAME_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_NAME_CJK_RUN_RE = re.compile(r"([㐀-䶿一-鿿豈-﫿]+)")
#: everything that separates the parts of a written name: spaces, dots, hyphens, the CJK
#: interpuncts, quotes, brackets, commas.
_NAME_SEP_RE = re.compile(r"[^0-9a-z㐀-䶿一-鿿豈-﫿]+")


def _pinyin(text: str) -> list[str]:
    """The toneless syllables of a CJK run — `周可欣` → `['zhou', 'ke', 'xin']`.

    One syllable per character, which is what lets the surname/given split above be carried
    over to the pinyin by index. Anything the transcriber leaves untranslated is dropped.
    """
    return [
        syllable
        for syllable in (str(s).strip().casefold() for s in lazy_pinyin(text))
        if syllable.isascii() and syllable.isalpha()
    ]


def split_cjk_name(name: str) -> tuple[str, str]:
    """A CJK name → (surname, given name), the compound surnames respected. A single
    character is a surname with no given half; nothing else is guessed."""
    if len(name) >= 3 and name[:2] in COMPOUND_SURNAMES:
        return name[:2], name[2:]
    if len(name) >= 2:
        return name[:1], name[1:]
    return name, ""


def _keeps(key: str) -> bool:
    """A key worth holding: any CJK key (a one-character surname is a real key), and a latin
    key of two characters or more (`j` is not a name, `kz` is a pair of initials)."""
    if not key:
        return False
    return bool(_NAME_CJK_RE.search(key)) or len(key) >= 2


def _normalized_name(text: str) -> str:
    """Casefolded, punctuation flattened to single spaces, and the scripts separated so
    `周可欣Kexin` is two parts rather than one unspellable token."""
    lowered = _NAME_CJK_RUN_RE.sub(r" \1 ", text.strip().casefold())
    return " ".join(part for part in _NAME_SEP_RE.split(lowered) if part)


def _latin_keys(tokens: list[str]) -> set[str]:
    """A latin name's keys: each token alone, both orders spaced, both orders concatenated,
    and the initials both ways. `Kexin ZHOU` and `ZHOU Kexin` are one person written by two
    conventions, and a library holds both conventions at once."""
    keys = set(tokens)
    if len(tokens) > 1:
        reverse = list(reversed(tokens))
        keys.add(" ".join(tokens))
        keys.add(" ".join(reverse))
        keys.add("".join(tokens))
        keys.add("".join(reverse))
        initials = "".join(token[0] for token in tokens)
        keys.add(initials)
        keys.add(initials[::-1])
    return keys


def _cjk_keys(run: str) -> set[str]:
    """A CJK name's keys: the name whole, its surname and given halves, and the pinyin of
    all three in both orders, spaced and concatenated, plus the initials.

    The pinyin is the bridge: it is the only key a latin-titled page and a CJK question can
    both produce. A run longer than four characters is not a name — it keeps its whole form
    and its whole pinyin and is not cut, because guessing where a name ends inside a longer
    run needs a lexicon and a wrong guess is worse than silence.
    """
    keys = {run}
    syllables = _pinyin(run)
    if not (2 <= len(run) <= 4) or len(syllables) != len(run):
        if syllables:
            keys.add("".join(syllables))
        return keys
    surname, given = split_cjk_name(run)
    keys.add(surname)
    keys.add(given)
    head = "".join(syllables[: len(surname)])
    tail = "".join(syllables[len(surname) :])
    if head and tail:
        keys.update(
            {
                head + tail,
                tail + head,
                f"{head} {tail}",
                f"{tail} {head}",
                head,
                tail,
                "".join(s[0] for s in syllables),
                "".join(s[0] for s in syllables[len(surname) :]),
            }
        )
    return keys


def name_keys(text: str) -> frozenset[str]:
    """Every key one written name can be reached by — the one normaliser BOTH sides of every
    people lookup go through: a page's title, aliases, slug and identity display names on one
    side, the question on the other.

    Latin and CJK parts are expanded by their own conventions and the result is one flat set;
    a name written in both scripts simply contributes both, which is how a page titled
    `Kexin ZHOU` and a page titled `周可欣` answer each other's questions.
    """
    full = _normalized_name(text)
    if not full:
        return frozenset()
    keys = {full}
    latin: list[str] = []
    for chunk in full.split(" "):
        if _NAME_CJK_RE.search(chunk):
            keys.update(_cjk_keys(chunk))
        elif len(chunk) >= 2 and not chunk.isdigit():
            latin.append(chunk)
    if latin:
        keys.update(_latin_keys(latin))
    return frozenset(key for key in keys if _keeps(key))


def name_tokens(text: str) -> tuple[str, ...]:
    """The atomic parts a name is made of — latin words, and the surname/given halves of a
    CJK run. What the token-subset rule is measured over: `Anna Schmidt` names the same
    person as `Anna Maria Schmidt`, and no reordering of two tokens can say so."""
    tokens: list[str] = []
    for chunk in _normalized_name(text).split(" "):
        if _NAME_CJK_RE.search(chunk):
            surname, given = split_cjk_name(chunk)
            tokens.extend(part for part in (surname, given) if part)
        elif len(chunk) >= 2 and not chunk.isdigit():
            tokens.append(chunk)
    return tuple(tokens)


def identity_display_name(identity: str) -> str:
    """The half of an identity that is a NAME. `im:Kexin ZHOU` carries one; `mailto:…@…`,
    `im:u_123` and `meeting:p_7` carry a handle, and a handle expanded into name keys would
    mint `example` and `print` out of an email domain. Exact `identity=` lookup already
    reaches those, and it reaches them without inventing anything."""
    _, _, value = identity.strip().partition(":")
    value = value.strip()
    if not value or "@" in value or "_" in value or any(c.isdigit() for c in value):
        return ""
    return value


@dataclass(frozen=True)
class NameMatch:
    """One page the name keys reached, and how well.

    TIER 1 — a key of the query IS a key of the page (`可欣` → `kexin`, `zhou kexin` →
    `kexin zhou`), or every token of the query is a token of the page. Exact, in some
    convention both sides can write.
    TIER 2 — a key of the query (two characters or more) is a PREFIX of a key of the page.
    A shortened form, and never a one-character CJK query, which would otherwise prefix
    every name that starts with it.

    Two numbers separate pages that land on the same tier, and they are ordered the way a
    person reads a match. `span` is the length of the LONGEST key that met — how much of the
    name the two sides agreed on, so a whole given name (`kexin`) outranks one syllable of
    one (`xin`, which any number of unrelated aliases contain). `keys` is how many keys met
    at all, which separates a full name from a bare surname. What still ties after both is a
    real ambiguity — two people ARE called that — and is returned as one.
    """

    path: str
    tier: int
    keys: int
    query: str
    span: int = 0

    @property
    def rank(self) -> tuple[int, int, int]:
        """Best first, and the tie that means ambiguity."""
        return (self.tier, -self.span, -self.keys)

    @property
    def label(self) -> str:
        return f"via:name-match tier{self.tier}"

    def render(self) -> str:
        how = "in some spelling of it" if self.tier == 1 else "as a prefix of it"
        return (
            f"matched `{self.query}` against this page's own names {how} · tier {self.tier}, "
            f"{self.keys} key(s) — a name match, not a declared alias"
        )


def match_tier(
    query: frozenset[str],
    page: frozenset[str],
    *,
    tokens: tuple[str, ...] = (),
    prefix: bool = True,
) -> tuple[int, int, int]:
    """(tier, how many query keys met, the longest one's length) for one page, best tier
    first. `(0, 0, 0)` is no match.

    `prefix=False` turns the second tier off for a query too short to shorten — a single
    character. `周` is then a surname key that matches `周` exactly, which is a real answer,
    rather than the prefix of every name in the library that begins with it.
    """
    shared = query & page
    if shared:
        return 1, len(shared), max(len(k) for k in shared)
    if len(tokens) >= 2 and all(token in page for token in tokens):
        return 1, len(tokens), max(len(t) for t in tokens)
    if not prefix:
        return 0, 0, 0
    prefixed = {
        q
        for q in query
        if len(q) >= PREFIX_MIN_CHARS and any(p != q and p.startswith(q) for p in page)
    }
    if prefixed:
        return 2, len(prefixed), max(len(k) for k in prefixed)
    return 0, 0, 0


def strip_honorific(query: str) -> str:
    """`可欣姐` → `可欣`, `小周` → `周`. The query side only, and only as a SECOND attempt
    after the raw form found nothing — 老王 may be somebody's confirmed alias, and stripping
    a name that already answers would trade a confirmation for a guess.

    Returns `""` when nothing was stripped or what is left is too short to be a name (one
    CJK character is; one latin character is not). Nothing here is ever written anywhere: an
    honorific is not knowledge about a person, and the page never learns the question was
    asked this way.
    """
    text = query.strip()
    original = text
    if text in HONORIFIC_SUFFIXES or text in HONORIFIC_PREFIXES:
        # The question is the form of address and nothing else. There is no name under it.
        return ""
    for suffix in sorted(HONORIFIC_SUFFIXES, key=len, reverse=True):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    for prefix in HONORIFIC_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix) :]
            break
    text = text.strip()
    if text == original or not text:
        return ""
    if _NAME_CJK_RE.search(text):
        return text
    return text if len(text) >= 2 else ""


def _definition_line(claims: list) -> list:
    """One page's ONE line, for when several pages answer at once: the overview's
    `definition` — who this is — or, on a page whose overview is still empty, its first
    claim. Enough to tell two people apart, little enough that three candidates are a
    choice rather than a flood."""
    for claim in claims:
        if "definition" in claim.labels:
            return [claim]
    return claims[:1]


@dataclass(frozen=True)
class NameClaim:
    """A name that is already somebody's, and what says so: another person page (by its
    alias, title or slug), or an identity the sources carry a display name for."""

    name: str
    kind: str
    owner: str

    def render(self) -> str:
        if self.kind == "cospeaker":
            return (
                f"the display name this library's sources record for {self.owner}, who "
                f"SPEAKS beside this page's own identity in one conversation"
            )
        if self.kind == "identity":
            return f"the display name this library's sources record for {self.owner}"
        return f"the {self.kind} of `{self.owner}`"


# ------------------------------------------------------------------ L0 identity extraction


@dataclass
class IdentityMention:
    identity: str
    display_name: str
    source_id: str
    occurred_on: str


def _mailto(address: str | None) -> str | None:
    address = (address or "").strip()
    return f"mailto:{address.casefold()}" if address else None


def identity_mentions(raw: RawSource) -> list[IdentityMention]:
    """Every NON-owner identity one source records, as the source contract wrote it.

    Owner ids are excluded: the owner is the subject of the library, not a contact. A
    meeting participant or IM user with an email is keyed by `mailto:` so the same person
    across channels collapses mechanically wherever the sources themselves say so; without
    one, the channel's own id is kept (`meeting:` / `im:`) and any cross-channel identity is
    the contract's to declare on the page.
    """
    meta = raw.meta or {}
    when = raw.occurred_on()
    sid = str(raw.source_id)
    out: list[IdentityMention] = []
    if raw.kind == "meeting":
        owners = set(meta.get("owner_participant_ids") or [])
        for p in meta.get("participants") or []:
            pid = str(p.get("participant_id") or "")
            if not pid or pid in owners:
                continue
            identity = _mailto(p.get("email")) or f"meeting:{pid}"
            out.append(IdentityMention(identity, str(p.get("display_name") or ""), sid, when))
    elif raw.kind == "im":
        owners = set(meta.get("owner_user_ids") or [])
        for u in meta.get("users") or []:
            uid = str(u.get("user_id") or "")
            if not uid or uid in owners or u.get("is_bot"):
                continue
            identity = _mailto(u.get("email")) or f"im:{uid}"
            out.append(IdentityMention(identity, str(u.get("display_name") or ""), sid, when))
    elif raw.kind == "email":
        owners = {str(a).strip().casefold() for a in meta.get("owner_addresses") or []}
        for m in meta.get("messages") or []:
            for addr in [m.get("from") or {}, *(m.get("to") or []), *(m.get("cc") or [])]:
                address = str(addr.get("address") or "").strip()
                if not address or address.casefold() in owners:
                    continue
                out.append(
                    IdentityMention(
                        _mailto(address) or "", str(addr.get("display_name") or ""), sid, when
                    )
                )
    return out


@dataclass(frozen=True)
class CoSpeaking:
    """One source and the non-owner identities that SPOKE in it, with what to call it by.

    Two PERSON IDS that both take a turn in one conversation are two people. That is the
    whole fact — needing no judgement — and it is what catches the failure the collision
    rules cannot see: a page whose `identities` hold three ids lifted from a group chat's
    title, where neither of the other two has a page of its own to collide with.

    "Person id" is the load-bearing half, and it is a property of the channel rather than of
    this rule: an IM `sender_id` and a meeting `speaker_id` are the platform's own handle for
    one participant, which is what makes two of them two people. An email ADDRESS is not —
    one human writing from `alex@work.example` and `alex@personal.example` is ordinary, and
    the correct person page binds both. See `source_speakers`.
    """

    source_id: str
    title: str
    occurred_on: str
    #: Normalized identities, so a member compares equal to a page's declared one.
    speakers: frozenset[str]

    def render(self) -> str:
        """How a refusal names this source: the title a reader can find it by, and when."""
        where = self.title.strip() or self.source_id
        day = self.occurred_on[:10]
        return f"{where} ({day})" if day else where


def source_speakers(raw: RawSource) -> CoSpeaking | None:
    """Who SPOKE in one source, or `None` when fewer than two non-owner identities did.

    Two things have to hold before a turn is evidence, and only two channels give both.

    Membership is not speech. A group's member list says who is in the room, and two ids
    from it may still be one person reached two ways — which is exactly why a page is
    allowed to bind several. A TURN is different: a message with a sender, a meeting segment
    with a speaker. Two turns by two ids in one source are two people, and no page may bind
    both.

    And the id has to be a PERSON id — the channel's own handle for one participant, the
    thing it would use to say "these two messages are the same human". `im` `sender_id` and
    `meeting` `speaker_id` are exactly that, validated by their contracts against the
    archive's user list and the meeting's participants. `email` is NOT, and that is the one
    channel this fact stays silent about: a thread's turns are addresses, one human commonly
    writes from two of them (`alex@work.example`, `alex@personal.example`), and the correct
    person page binds both. `email/v1` carries no stable actor id and no equivalence
    relation, so "two senders are two people" cannot be derived from it — and a hard refusal
    derived from something the contract does not establish leaves only two ways past it:
    discard a truthful identity, or turn the rule off. Should a contract version arrive with
    a person-level sender id, this is where it would be keyed on.

    Keyed exactly like `identity_mentions` (`mailto:` where the contract carries an email,
    the channel's own id otherwise; owners and bots excluded), so a speaker here compares
    equal to an identity a page declares. `meta` only — the envelopes the source contracts
    record — so this costs no block fetch and is computable from `ContentStore.list` alone.

    A plain `conversation` contributes nothing either, and for its own reason: its turns
    carry speaker LABELS rather than identities, a label is not `scheme:value` and so can
    never be a page's identity at all (`people.identity_shape` refuses it first). There is
    nothing for this fact to say there — not a gap, an absence of subject matter.
    """
    meta = raw.meta or {}
    speakers: set[str] = set()
    if raw.kind == "meeting":
        owners = {str(x) for x in meta.get("owner_participant_ids") or []}
        by_id = {
            pid: _mailto(p.get("email")) or f"meeting:{pid}"
            for pid, p in (
                (str((p or {}).get("participant_id") or ""), p)
                for p in meta.get("participants") or []
            )
            if pid and pid not in owners
        }
        spoke = (str((seg or {}).get("speaker_id") or "") for seg in meta.get("segments") or [])
    elif raw.kind == "im":
        owners = {str(x) for x in meta.get("owner_user_ids") or []}
        by_id = {
            uid: _mailto(u.get("email")) or f"im:{uid}"
            for uid, u in (
                (str((u or {}).get("user_id") or ""), u) for u in meta.get("users") or []
            )
            if uid and uid not in owners and not (u or {}).get("is_bot")
        }
        spoke = (str((m or {}).get("sender_id") or "") for m in meta.get("messages") or [])
    else:
        return None
    for key in spoke:
        identity = by_id.get(key)
        if identity:
            speakers.add(normalize_identity(identity))
    if len(speakers) < 2:
        return None
    return CoSpeaking(
        source_id=str(raw.source_id),
        title=raw.title or "",
        occurred_on=raw.occurred_on(),
        speakers=frozenset(speakers),
    )


@dataclass
class IdentitySummary:
    identity: str
    display_names: list[str] = field(default_factory=list)
    source_ids: set[str] = field(default_factory=set)
    first: str = ""
    last: str = ""


def summarize_identities(
    sources: Iterable[RawSource], *, since: str = "", until: str = ""
) -> list[IdentitySummary]:
    """Closed-world enumeration: one summary per external identity across the given
    sources, restricted to occurrence days within [since, until] (ISO day strings; either
    bound empty = open). Sorted by source count (desc) then identity, for determinism."""
    by_id: dict[str, IdentitySummary] = {}
    for raw in sources:
        day = raw.occurred_on()[:10]
        if since and day < since[:10]:
            continue
        if until and day > until[:10]:
            continue
        for m in identity_mentions(raw):
            key = normalize_identity(m.identity)
            s = by_id.setdefault(key, IdentitySummary(identity=m.identity))
            if m.display_name and m.display_name not in s.display_names:
                s.display_names.append(m.display_name)
            s.source_ids.add(m.source_id)
            if day:
                s.first = min(s.first, day) if s.first else day
                s.last = max(s.last, day) if s.last else day
    return sorted(by_id.values(), key=lambda s: (-len(s.source_ids), s.identity))


# ------------------------------------------------------------------ address evidence
# HOW a person is CALLED, read off conversation structure — never off a name list.
#
# The identities above answer WHO is present. They never answer what the turns call that
# person: a corpus that says `@Hao WEN 阿宝，我不发通知…` 84 times still leaves every
# person page's `aliases` holding nothing but the display name, because nothing points at
# where the evidence sits. The evidence is structural, and it is the same structure in every
# channel: a turn, its speaker, who it is addressed to, and who speaks next.
#
# Three mechanical signals, none of them proof (the owner's own counter-example:
# `@X 阿宝怎么样` — the term after the @ names a THIRD person):
#
#   addressed   an email to/cc addressee, or an `@<display name>` marker that resolves to a
#               present identity, IS that identity — the turn is addressed to them. This
#               IDENTIFIES; it is not an alias, and it is never reported as one. It is what
#               the two signals below are measured against.
#   answered    a turn opens with an address term and the next turn by a DIFFERENT speaker,
#               within `ANSWER_WINDOW`, is identity Y → one `answered` support for term → Y.
#               Y may simply be whoever spoke next, so one occurrence is noise.
#   co_mention  the term appears in a turn that also addresses X (`@X 阿宝，…`) → one
#               `co_mention` support for term → X. Explicitly weak: the term may name a
#               third person, which is exactly the case above.
#
# So the output is always a CANDIDATE with a support DISTRIBUTION over targets, never a
# binding. When a term points at more than one identity, every target is stated, so the
# ambiguity reaches the model instead of being resolved by a counter. What is worth SAYING is
# decided one level up, over the whole library (`reported_terms`); who the term names stays
# the contract's judgement.

#: Kinds whose blocks are turns with a speaker. A document has no turns → no evidence.
ADDRESS_KINDS = ("meeting", "im", "email", "conversation")

#: Which index-aligned `meta` list names the speaker of each block, and its field.
#: (Email is not a speaker column — its turns carry `from`/`to`/`cc` headers instead.)
_SPEAKER_META = {"meeting": ("segments", "speaker_id"), "im": ("messages", "sender_id")}

#: How far "answered" looks ahead for the next turn by a different speaker.
ANSWER_WINDOW = 3

#: A term the SOURCE itself repeats this often is worth showing as *emerging* under it, and a
#: (term → target) pair needs this much LIBRARY-wide support before it can be reported at all.
#: Below either bar a term is still counted — repetition across turns and sources is the whole
#: point — just not yet worth saying.
ADDRESS_MIN_SUPPORT = 2
ADDRESS_LIBRARY_MIN_SUPPORT = 3

#: Candidates stated under one source; the rest are counted in a `…and N more` tail.
ADDRESS_PREAMBLE_MAX = 6

#: A term ends where the turn's own punctuation ends it (or at the end of the text). One
#: definition: the same delimiters close a term and are stepped over before the next one.
#:
#: The ASCII colon is the one CONDITIONAL member: it closes a term only before whitespace or
#: end of text. `周总：` (full-width) is a vocative; `https://…`, `msgId:abc` and `a017:` are not,
#: and a delimiter that fires inside them is exactly how a URL scheme became a "nickname".
_DELIMITERS = "，,：:、 \t"
_HARD_DELIMITERS = "，,：、 \t"
_TERM_END = f"(?=[{re.escape(_HARD_DELIMITERS)}]|:(?=\\s|$)|$)"
#: A term is at most 4 CJK characters, or a Latin token that starts with a letter and carries
#: letters only. Digits, `/`, `.` and `_` are not name material — they are identifiers,
#: versions and paths (`a017`, `MIRO-DISC-001`, `msgId`), and admitting one character of that
#: class admits the whole class.
_TERM_CJK_RE = re.compile(f"^([\u3400-\u4dbf\u4e00-\u9fff]{{1,4}}){_TERM_END}")
_TERM_LATIN_RE = re.compile(f"^([A-Za-z][A-Za-z'-]{{1,23}}){_TERM_END}")

#: Openers that are not names. `_GREETINGS` may be stepped over ONCE (`Hi Kun,` is an
#: address term behind a greeting); every stopword, greetings included, is rejected as a term.
_GREETINGS = frozenset(
    {
        "hi", "hello", "hey", "dear", "morning", "ok", "okay", "thanks", "thank",
        "你好", "您好", "大家好", "早上好", "下午好", "晚上好", "好的", "收到", "谢谢",
    }
)
#: The Latin half of the function-word head rule below. A Latin term is one token, so
#: "starts with a pronoun" and "is a pronoun" are the same test — closed-class words only,
#: never anything that doubles as a name (`Will`, `May`, `Grace` stay eligible).
_LATIN_FUNCTION_WORDS = frozenset(
    {
        "i", "me", "my", "mine", "we", "us", "our", "ours", "you", "your", "yours",
        "he", "him", "his", "she", "her", "hers", "they", "them", "their", "it", "its",
        "this", "that", "these", "those", "there", "here", "and", "but", "or", "so",
        "then", "also", "just", "still", "the", "an", "if", "when", "what", "why", "who",
        "which", "how", "can", "could", "would", "should", "did", "does", "was", "were",
        "am", "are", "been", "being", "not", "yeah", "yep", "yup", "nope", "lol", "haha",
        "hmm", "btw", "etc",
    }
)
_ADDRESS_STOPWORDS = _GREETINGS | _LATIN_FUNCTION_WORDS | frozenset(
    {
        "all", "team", "guys", "folks", "everyone", "yes", "no", "sure", "fyi", "re",
        "fw", "fwd", "cc", "please", "sorry", "noted", "done",
        "大家", "各位", "同学", "同事", "老师", "请问", "麻烦", "抱歉", "不好意思",
        "了解", "明白", "知道", "可以", "没问题", "在吗", "多谢", "辛苦", "好嘞", "嗯嗯",
        "行", "好", "嗯", "对", "是", "哦", "啊", "有", "没", "我", "你", "他", "她",
    }
)


#: Belt-and-braces, NOT the mechanism. What actually separates a nickname from a common
#: phrase is library-wide concentration (`reported_terms` below): a real nickname points at
#: one person, while `是的` and `看下` are "answered" by everyone. These two lists only stop the
#: most frequent openers from consuming a term slot before that arithmetic runs, and either
#: could be deleted without changing what is finally reported.
_PARTICLE_TAIL = frozenset("了吗呢吧呀嘛么的啊哦")
_FUNCTION_HEAD = frozenset("我你这那就也都没是好看请先")


def _repeats(term: str) -> bool:
    """A character or bigram repeated three times running — `哈哈哈`, `hhhh`, `呵呵呵呵`.

    Laughter and filler are the one class of token that reaches a turn's head as often as a
    name does, and they are recognisable by shape alone rather than by a word list that would
    have to grow with every language.
    """
    for size in (1, 2):
        for start in range(len(term) - size * 3 + 1):
            unit = term[start : start + size]
            if term[start : start + size * 3] == unit * 3:
                return True
    return False


def rejects_address_term(term: str) -> str:
    """Why `term` cannot be an address term, or `""` when it can be one.

    One implementation, shared by every path that produces a term (per-source evidence, the
    projection write, the library-wide report), so a term reported under a source and a term
    counted in the projection are the same term by construction.
    """
    if not term:
        return "empty"
    if term.casefold() in _ADDRESS_STOPWORDS:
        return "stopword"
    if _repeats(term):
        return "repetition"
    if term[0] in _FUNCTION_HEAD:
        return "function word head"
    if term[-1] in _PARTICLE_TAIL:
        return "sentence-final particle"
    return ""


def term_key(term: str) -> str:
    """The comparison key a term is counted under. Latin terms are compared
    case-insensitively (`Momo` and `momo` are one nickname); CJK casefolds to itself."""
    return term.strip().casefold()


#: A Latin word or a run of CJK — the pieces a title is made of, and the same two shapes the
#: term grammar admits.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]*|[\u3400-\u4dbf\u4e00-\u9fff]+")


def structural_tokens(title: str) -> frozenset[str]:
    """The comparison keys a source's OWN NAME already occupies.

    A conversation's title is the source's structural vocabulary, not its speech: a group
    named after a product, a company or a workstream makes that word open messages all day,
    and somebody answers each of them. Measured on a real corpus that is half of what reached
    the report — a vendor's name, a company's name, a topic word — so a term the title itself
    supplies is not counted as a way of addressing anybody. Equality against a token, never
    containment: a nickname that happens to sit inside a longer title run is still a nickname.
    """
    return frozenset(key for key in (term_key(t) for t in _TOKEN_RE.findall(title or "")) if key)


def occurrences(term: str, text: str) -> int:
    """How many times `term` appears in `text` — one whole token for Latin (case-insensitive),
    a plain substring for CJK. The same counting `unresolved_names` does, for the same reason:
    a Latin term inside a longer word is a different word, while CJK carries no such boundary
    and asking for one would need a lexicon."""
    if not term or not text:
        return 0
    if term.isascii():
        return len(re.findall(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", text, re.I))
    return text.count(term)


@dataclass(frozen=True)
class AddressTarget:
    """Who a term could name: an identity from the source boundary, or — when the boundary
    gives none (a plain conversation) — the speaker label the blocks themselves render."""

    key: str
    name: str = ""


@dataclass
class AddressCandidate:
    """One (term → target) pair with its support per signal. A candidate, never a binding.

    `answered` and `co_mention` are both VOCATIVE counts — they are only ever reached from a
    term at the head of a turn — and `non_vocative` is the same term seen mid-sentence in the
    same source, which belongs to the TERM rather than to this target: every candidate a term
    produces under one source carries the same number.
    """

    term: str
    target: str
    target_name: str = ""
    answered: int = 0
    co_mention: int = 0
    non_vocative: int = 0

    @property
    def support(self) -> int:
        return self.answered + self.co_mention

    def render(self) -> str:
        signals = [
            f"{name} {count}"
            for name, count in (
                ("answered", self.answered),
                ("co_mention", self.co_mention),
                ("non_vocative", self.non_vocative),
            )
            if count
        ]
        return f"{self.target} ({', '.join(signals)})"


@dataclass
class _Turn:
    """One block as a turn: who spoke (a comparison key + their target, if they are one),
    the turn's OWN text with the renderer's label prefix removed, and whom the turn's
    envelope addresses. Turns stay index-aligned with blocks — a block whose rendering does
    not match keeps its place with empty text, so adjacency is never silently shifted."""

    speaker: str
    speaker_target: AddressTarget | None = None
    text: str = ""
    addressees: tuple[AddressTarget, ...] = ()


_SENTINEL = "\x00"
_TEXT_SENTINEL = "\x01"


def _turn_prefix(label: str) -> str:
    """Exactly what the renderer puts before a turn's own text, asked of the renderer's own
    prompt rather than guessed (`ingest.turn_line`, whose separator is language-dependent)."""
    return prompt("ingest.turn_line", label=label, text=_TEXT_SENTINEL).split(_TEXT_SENTINEL)[0]


def _turn_body(text: str, label: str) -> str:
    prefix = _turn_prefix(label)
    return text[len(prefix) :] if text.startswith(prefix) else ""


def _owner_label(label: str) -> bool:
    """Is this rendered label the owner's? Both owner renderings are prompt surfaces
    (`ingest.owner_label`, `ingest.owner_wrapped`), so both are read from them."""
    if label == prompt("ingest.owner_label"):
        return True
    head, _, tail = prompt("ingest.owner_wrapped", label=_SENTINEL).partition(_SENTINEL)
    return bool(head) and label.startswith(head) and label.endswith(tail)


def _speaker_meta_turns(
    raw: RawSource, blocks
) -> tuple[list[_Turn], dict[str, AddressTarget | None]]:
    meta = raw.meta or {}
    if raw.kind == "meeting":
        owners = {str(x) for x in meta.get("owner_participant_ids") or []}
        people = [(str(p.get("participant_id") or ""), p) for p in meta.get("participants") or []]
        scheme = "meeting"
    else:
        owners = {str(x) for x in meta.get("owner_user_ids") or []}
        people = [(str(u.get("user_id") or ""), u) for u in meta.get("users") or []]
        scheme = "im"
    labels: dict[str, str] = {}
    targets: dict[str, AddressTarget | None] = {}
    names: dict[str, AddressTarget | None] = {}
    for pid, person in people:
        if not pid:
            continue
        display = str(person.get("display_name") or "")
        labels[pid] = prompt("ingest.owner_wrapped", label=display) if pid in owners else display
        # The owner is the subject of the library, not a contact; a bot is not a person.
        # Both still occupy a name (a turn opening with the owner's own name is not an
        # alias for whoever answers), so they are present under `names` with no target.
        eligible = pid not in owners and not person.get("is_bot")
        targets[pid] = (
            AddressTarget(_mailto(person.get("email")) or f"{scheme}:{pid}", display)
            if eligible
            else None
        )
        if display:
            names.setdefault(display.casefold(), targets[pid])
    list_key, field = _SPEAKER_META[raw.kind]
    entries = meta.get(list_key) or []
    if len(entries) != len(blocks):
        # Index alignment is the whole contract (the same rule the time component keeps for
        # per-block instants): a mismatch drops the signal for this source, never guesses it.
        return [], names
    turns: list[_Turn] = []
    for block, entry in zip(blocks, entries):
        pid = str((entry or {}).get(field) or "")
        label = labels.get(pid)
        turns.append(
            _Turn(
                speaker=pid,
                speaker_target=targets.get(pid),
                text=_turn_body(block.text, label) if label is not None else "",
            )
        )
    return turns, names


def _email_turns(raw: RawSource, blocks) -> tuple[list[_Turn], dict[str, AddressTarget | None]]:
    meta = raw.meta or {}
    owners = {str(a).strip().casefold() for a in meta.get("owner_addresses") or []}
    names: dict[str, AddressTarget | None] = {}

    def target_of(addr: Mapping | None) -> AddressTarget | None:
        address = str((addr or {}).get("address") or "").strip()
        if not address:
            return None
        display = str((addr or {}).get("display_name") or "")
        target = (
            None
            if address.casefold() in owners
            else AddressTarget(_mailto(address) or "", display)
        )
        if display:
            names.setdefault(display.casefold(), target)
        return target

    entries = meta.get("messages") or []
    if len(entries) != len(blocks):
        return [], names
    turns: list[_Turn] = []
    for block, entry in zip(blocks, entries):
        entry = entry or {}
        sender = entry.get("from") or {}
        subject_line = prompt("ingest.email.subject", subject=str(entry.get("subject") or ""))
        _, found, body = block.text.partition(f"\n{subject_line}\n")
        addressees = tuple(
            t
            for t in (
                target_of(a) for a in [*(entry.get("to") or []), *(entry.get("cc") or [])]
            )
            if t is not None
        )
        turns.append(
            _Turn(
                speaker=str(sender.get("address") or "").strip().casefold(),
                speaker_target=target_of(sender),
                text=body if found else "",
                addressees=addressees,
            )
        )
    return turns, names


def _label_turns(blocks) -> tuple[list[_Turn], dict[str, AddressTarget | None]]:
    """A conversation with no identity metadata (plain / context-stream intake): the
    speaker is the label the blocks themselves render — `Owner:` / `ParticipantN (id):` /
    a verbatim speaker name. No identity exists, so the label IS the target: the candidate
    still says which speaker answers to a term, and a page binds an identity, not this."""
    # The renderer's own separator (`ingest.turn_line` is language-dependent), then the
    # plain adapter's literal one — `f"{speaker}: {text}"`, which is not a prompt surface.
    separators = [sep for sep in (_turn_prefix(_SENTINEL).split(_SENTINEL)[-1], ": ") if sep]
    names: dict[str, AddressTarget | None] = {}
    turns: list[_Turn] = []
    for block in blocks:
        label, body = "", ""
        for sep in separators:
            head, found, rest = block.text.partition(sep)
            if found and head and "\n" not in head and len(head) <= 64:
                label, body = head, rest
                break
        if not label:
            turns.append(_Turn(speaker=""))
            continue
        target = None if _owner_label(label) else AddressTarget(label, label)
        names.setdefault(label.casefold(), target)
        turns.append(_Turn(speaker=label, speaker_target=target, text=body))
    return turns, names


def _turns(source: NormalizedSource) -> tuple[list[_Turn], dict[str, AddressTarget | None]]:
    raw = source.raw
    if raw.kind == "email":
        return _email_turns(raw, list(source.blocks))
    if raw.kind in _SPEAKER_META:
        return _speaker_meta_turns(raw, list(source.blocks))
    if raw.kind == "conversation":
        return _label_turns(list(source.blocks))
    return [], {}


def _resolve_marker(
    text: str, names: Mapping[str, AddressTarget | None]
) -> tuple[AddressTarget | None, int] | None:
    """`text` starts with `@`. The LONGEST present display name right after it wins (names
    contain spaces: `@Hao WEN 阿宝` addresses Hao WEN and then says 阿宝)."""
    body = text[1:]
    hit = ""
    for name in names:
        if len(name) > len(hit) and body[: len(name)].casefold() == name:
            hit = name
    if not hit:
        return None
    return names[hit], 1 + len(hit)


def _leading_token(text: str) -> str | None:
    match = _TERM_CJK_RE.match(text) or _TERM_LATIN_RE.match(text)
    return match.group(1) if match else None


def _leading_address_term(
    text: str,
    names: Mapping[str, AddressTarget | None],
    blocked: frozenset[str] = frozenset(),
) -> tuple[str, list[AddressTarget], str]:
    """The address term at the very start of a turn, whom the turn's `@` markers address, and
    THE REST — everything of the turn that is not its vocative head.

    An unresolved `@token` is not skipped — it IS the term (`@momo 既然…` is how a nickname
    that no identity carries appears in the first place). `blocked` are keys the source's own
    structure already accounts for (`structural_tokens`).

    The third element is what makes the mid-sentence count possible at all: the vocative
    position is a place, so everything else in the turn is the other place, and one pass over
    the text decides both rather than two rules that could disagree about where the head ends.
    """
    marked: list[AddressTarget] = []
    rest = text.lstrip()
    for _ in range(4):
        if not rest.startswith("@"):
            break
        resolved = _resolve_marker(rest, names)
        if resolved is None:
            rest = rest[1:].lstrip(_DELIMITERS)
            break
        target, used = resolved
        if target is not None:
            marked.append(target)
        rest = rest[used:].lstrip(_DELIMITERS)
    term = _leading_token(rest)
    if term is not None and term.casefold() in _GREETINGS:
        rest = rest[len(term) :].lstrip(_DELIMITERS)
        term = _leading_token(rest)
    if term is None or rejects_address_term(term) or term_key(term) in blocked:
        return "", marked, rest
    if term.casefold() in names:
        # The term IS a present display name: that identifies the person (signal 1), and an
        # identity is recorded in the page's `identities`, not reported here as a nickname.
        return "", marked, rest
    return term, marked, rest[len(term) :]


def address_evidence(
    source: NormalizedSource, *, min_support: int = 1
) -> list[AddressCandidate]:
    """Address-term candidates from one source's turn structure. Pure, channel-neutral.

    `min_support` gates a TERM by its best target: once a term is worth saying, its whole
    distribution is returned — the sub-threshold targets are the ambiguity, and hiding them
    would be the mechanism deciding what only the contract may decide.

    Both signals are counted at the VOCATIVE POSITION only. Alongside them each candidate
    carries `non_vocative`: the same term seen in the turns' own text away from that position
    — mid-sentence, where a topic word lives and a way of addressing somebody does not. That
    count is per TERM (every candidate of one term carries it), and the reporting rule below
    is what uses it.
    """
    turns, names = _turns(source)
    blocked = structural_tokens(getattr(source.raw, "title", "") or "")
    pairs: dict[tuple[str, str], AddressCandidate] = {}
    bodies: list[str] = []

    def bump(term: str, target: AddressTarget | None, signal: str) -> None:
        if target is None or not target.key:
            return
        candidate = pairs.setdefault(
            (term_key(term), target.key),
            AddressCandidate(term=term, target=target.key, target_name=target.name),
        )
        setattr(candidate, signal, getattr(candidate, signal) + 1)

    for position, turn in enumerate(turns):
        if not turn.text:
            bodies.append("")
            continue
        term, marked, body = _leading_address_term(turn.text, names, blocked)
        bodies.append(body)
        if not term:
            continue
        seen: set[str] = set()
        for target in (*turn.addressees, *marked):
            own = turn.speaker_target is not None and turn.speaker_target.key == target.key
            if own or target.key in seen:
                continue
            seen.add(target.key)
            bump(term, target, "co_mention")
        for following in turns[position + 1 : position + 1 + ANSWER_WINDOW]:
            if following.speaker == turn.speaker:
                continue
            bump(term, following.speaker_target, "answered")
            break

    # One text, one pass: the mid-sentence count is taken over what the vocative head left
    # behind in every turn, joined by a newline so nothing straddles two turns.
    elsewhere = "\n".join(bodies)
    mid: dict[str, int] = {}
    for candidate in pairs.values():
        key = term_key(candidate.term)
        if key not in mid:
            mid[key] = occurrences(key, elsewhere)
        candidate.non_vocative = mid[key]

    best: dict[str, int] = {}
    for candidate in pairs.values():
        key = term_key(candidate.term)
        best[key] = max(best.get(key, 0), candidate.support)
    return sorted(
        (c for c in pairs.values() if best[term_key(c.term)] >= min_support),
        key=lambda c: (-c.support, c.term, c.target),
    )


def render_address_candidates(
    candidates: list[AddressCandidate], *, cap: int = ADDRESS_PREAMBLE_MAX
) -> str:
    """`"阿宝" → im:u_hw (answered 2, co_mention 1) · im:u_yb (answered 1); "momo" → …`"""
    shown, cut = candidates[:cap], max(len(candidates) - cap, 0)
    by_term: dict[str, list[AddressCandidate]] = {}
    for candidate in shown:
        by_term.setdefault(candidate.term, []).append(candidate)
    text = "; ".join(
        f'"{term}" → ' + " · ".join(c.render() for c in group)
        for term, group in by_term.items()
    )
    return f"{text}; …and {cut} more" if cut else text


def merge_address_candidates(
    candidates: Iterable[AddressCandidate], *, term: str = ""
) -> list[AddressCandidate]:
    """The same (term → target) pairs seen in several sources, summed into one distribution.
    `term` restricts to one address term (exact, case-insensitive)."""
    want = term_key(term)
    merged: dict[tuple[str, str], AddressCandidate] = {}
    for candidate in candidates:
        if want and term_key(candidate.term) != want:
            continue
        into = merged.setdefault(
            (term_key(candidate.term), candidate.target),
            AddressCandidate(
                term=candidate.term, target=candidate.target, target_name=candidate.target_name
            ),
        )
        into.answered += candidate.answered
        into.co_mention += candidate.co_mention
        into.non_vocative += candidate.non_vocative
    return sorted(merged.values(), key=lambda c: (-c.support, c.term, c.target))


# --------------------------------------------------- the library-wide projection and its rule
# A term's meaning is not in the source that carries it. Inside ONE conversation, `看下` and
# `阿宝` look identical: both open a turn, both are followed by an answer. What separates them
# is what the REST of the library does with them — a nickname keeps pointing at the same
# person, while a common phrase is answered by whoever happens to speak next, everywhere.
#
# So the unit that is stored and judged is the (term → target) pair with its LIBRARY-WIDE
# support, and the rule is concentration:
#
#     support(term→target) >= REPORT_MIN_SUPPORT
#     sources(term→target) >= REPORT_MIN_SOURCES        (one conversation is an anecdote)
#     support(term→target) / support(term) >= REPORT_MIN_CONCENTRATION
#     support / (support + non_vocative) >= REPORT_MIN_VOCATIVE_SHARE
#
# All four must hold. `是的` spread over twelve targets fails the third no matter how large
# its total grows; `阿宝` with 13 of its 16 supports on one identity passes. Nothing in this is
# a word list, and nothing in it is language-specific: it is arithmetic over turn structure.
#
# The fourth is POSITION, and concentration alone cannot see it. Measured on 88 days of a real
# corpus, about half of what passed the first three was not a way of addressing anybody: a
# vendor's name, a company's name, a topic word, a short phrase that opens messages — each of
# them concentrated on the one person who habitually answers, each of them therefore reported,
# and the forced decision then handed a model noise to judge, which it judged badly in both
# directions. What separates the genuine terms is where they appear: a way of addressing a
# person occupies the vocative position and almost nothing else, while a topic word is all
# over the middle of the same sources' sentences. So a term is also asked how it is used —
# `support` is the vocative-position count by construction (both signals are only ever reached
# from a term at the head of a turn), `non_vocative` is the same term mid-sentence, and a term
# that is mostly mid-sentence is not an address term whatever its reply rate.
#
# A term that passes is REPORTED, and a reported term is rendered with its WHOLE distribution
# — the runner-up targets ARE the ambiguity, and hiding them would be the counter deciding
# what only the contract may decide.


#: A (term → target) pair must reach this much support, from this many sources, and hold this
#: share of the term's total, before it is worth saying anywhere.
REPORT_MIN_SUPPORT = ADDRESS_LIBRARY_MIN_SUPPORT
REPORT_MIN_SOURCES = 2
REPORT_MIN_CONCENTRATION = 0.6

#: …and this share of where the term is USED must be the vocative position. Half is the
#: honest bar for a distributional statement: a term used mid-sentence more often than it is
#: used to address somebody is being talked about, not being called out.
REPORT_MIN_VOCATIVE_SHARE = 0.5

#: Reported terms / emerging terms stated under one source; the rest become a `…and N more`.
PREAMBLE_REPORTED_MAX = ADDRESS_PREAMBLE_MAX
PREAMBLE_EMERGING_MAX = 3


@dataclass
class TermSupport:
    """One (term → target) pair's library-wide support: a projection row, and the unit the
    reporting rule is applied to. `term` is the comparison key (`term_key`).

    `answered` + `co_mention` is the VOCATIVE-position support; `non_vocative` counts the same
    term mid-sentence in the sources that produced this row. That last one is a fact about the
    TERM, replicated onto each of its targets by the source that saw it, so it is read per row
    and NEVER summed across a term's distribution — summing would count one source's
    mid-sentence usage once per target it happens to have.
    """

    term: str
    target: str
    target_name: str = ""
    answered: int = 0
    co_mention: int = 0
    non_vocative: int = 0
    sources: int = 0
    first_day: str = ""
    last_day: str = ""
    #: The day this pair FIRST satisfied the reporting rule — the day the library started
    #: asking about it. Derived like every other column here (`stamp_reported_since` sets
    #: it, `rebuild` re-derives it), and monotone: a pair that later drops back under the
    #: bar keeps the day it crossed it, because the question WAS asked, and it was asked
    #: then. Empty on a row nothing has stamped yet — a library whose table predates the
    #: column, which is why an empty one means "ask" and never "already answered".
    reported_since: str = ""

    @property
    def support(self) -> int:
        return self.answered + self.co_mention

    def signals(self) -> str:
        """`answered 36, co_mention 11, 31 sources` — the support behind this row, in one
        phrase. One definition, because every face that shows a derived match has to show
        exactly what the arithmetic saw."""
        parts = [
            f"{name} {count}"
            for name, count in (
                ("answered", self.answered),
                ("co_mention", self.co_mention),
                ("non_vocative", self.non_vocative),
            )
            if count
        ]
        parts.append(_sources_phrase(self.sources))
        return ", ".join(parts)

    def render(self) -> str:
        who = f"{self.target} — {self.target_name}" if self.target_name else self.target
        return f"{who} ({self.signals()})"

    def row(self) -> dict:
        return {
            "term": self.term,
            "target_identity": self.target,
            "target_name": self.target_name,
            "answered": self.answered,
            "co_mention": self.co_mention,
            "non_vocative": self.non_vocative,
            "sources": self.sources,
            "first_day": self.first_day,
            "last_day": self.last_day,
            "reported_since": self.reported_since,
        }


def term_support_from_row(row: Mapping) -> TermSupport:
    return TermSupport(
        term=str(row.get("term") or ""),
        target=str(row.get("target_identity") or ""),
        target_name=str(row.get("target_name") or ""),
        answered=int(row.get("answered") or 0),
        co_mention=int(row.get("co_mention") or 0),
        non_vocative=int(row.get("non_vocative") or 0),
        sources=int(row.get("sources") or 0),
        first_day=str(row.get("first_day") or ""),
        last_day=str(row.get("last_day") or ""),
        reported_since=str(row.get("reported_since") or ""),
    )


def term_rows(source: NormalizedSource) -> list[dict]:
    """One source's contribution to the projection. Pure — the store adds whatever this
    returns to what is already there, so every row counts exactly one source."""
    day = source.raw.occurred_on()[:10]
    return [
        TermSupport(
            term=term_key(c.term),
            target=c.target,
            target_name=c.target_name,
            answered=c.answered,
            co_mention=c.co_mention,
            non_vocative=c.non_vocative,
            sources=1,
            first_day=day,
            last_day=day,
        ).row()
        for c in address_evidence(source)
    ]


def accumulate_term_rows(
    into: dict[tuple[str, str], TermSupport], rows: Iterable[Mapping]
) -> dict[tuple[str, str], TermSupport]:
    """The store's upsert arithmetic, in memory. ONE definition of "add a source's counts to
    the projection", so the keyless fallback and the PG table cannot drift apart."""
    for row in rows:
        add = term_support_from_row(row)
        key = (add.term, add.target)
        current = into.get(key)
        if current is None:
            into[key] = add
            continue
        current.answered += add.answered
        current.co_mention += add.co_mention
        current.non_vocative += add.non_vocative
        current.sources += add.sources
        if not current.target_name:
            current.target_name = add.target_name
        if add.first_day:
            current.first_day = min(current.first_day, add.first_day) if current.first_day else add.first_day
        if add.last_day:
            current.last_day = max(current.last_day, add.last_day)
        if add.reported_since and (
            not current.reported_since or add.reported_since < current.reported_since
        ):
            current.reported_since = add.reported_since
    return into


def is_reported(row: TermSupport, total: int) -> bool:
    """The rule itself, in one place: enough support, from more than one source, holding most
    of what the term points at — and used mostly to ADDRESS somebody rather than mid-sentence.

    `total` is the term's whole support across its targets (concentration); the vocative share
    is read off this row alone, because `non_vocative` belongs to the term and is already on
    every one of its rows. Written as a product rather than a quotient so a row with no
    mid-sentence occurrences at all needs no special case.
    """
    return (
        row.support >= REPORT_MIN_SUPPORT
        and row.sources >= REPORT_MIN_SOURCES
        and row.support >= REPORT_MIN_CONCENTRATION * total
        and row.support >= REPORT_MIN_VOCATIVE_SHARE * (row.support + row.non_vocative)
    )


def reported_terms(rows: Iterable[TermSupport]) -> dict[str, list[TermSupport]]:
    """term → its FULL distribution, for the terms that pass the concentration rule.

    A term is present in the result when at least one of its targets is reported; every
    target of such a term is listed, best-supported first. A term whose support is spread
    thin over many targets is absent — reported nowhere, for anyone."""
    by_term: dict[str, list[TermSupport]] = {}
    for row in rows:
        by_term.setdefault(row.term, []).append(row)
    out: dict[str, list[TermSupport]] = {}
    for term, group in by_term.items():
        total = sum(r.support for r in group)
        if not total:
            continue
        if not any(is_reported(r, total) for r in group):
            continue
        out[term] = sorted(group, key=lambda r: (-r.support, r.target))
    return dict(sorted(out.items(), key=lambda kv: (-sum(r.support for r in kv[1]), kv[0])))


def stamp_reported_since(
    rows: Mapping[tuple[str, str], TermSupport], day: str
) -> list[tuple[str, str]]:
    """Mark every pair that is REPORTED now and carries no stamp yet with `day`; return the
    keys just stamped, so the caller can write the same days to its table.

    This is the clock the one-time ask runs on. `is_reported` is a fact about the projection
    as it stands and says nothing about WHEN it became true, so the moment it becomes true
    is recorded — once. Monotone by construction: a pair whose concentration later shifts
    back under the bar keeps its day, because the library did ask about it then and a page
    written since has answered.

    Called after a source's counts are folded in, with THAT source's day, so the stamp is
    the day of the material that pushed the pair over rather than the day the index job
    happened to run — which is what lets `rebuild`, replaying L0 in source order, reproduce
    the same dates from nothing.
    """
    stamped: list[tuple[str, str]] = []
    if not day:
        return stamped
    for group in reported_terms(rows.values()).values():
        total = sum(r.support for r in group)
        for row in group:
            if row.reported_since or not is_reported(row, total):
                continue
            row.reported_since = day
            stamped.append((row.term, row.target))
    return sorted(stamped)


def reported_targets(rows: Iterable[TermSupport], term: str) -> list[TermSupport]:
    """The rows one address term is REPORTED for, strongest first — `[]` when it is not.

    The lookup form of the concentration rule. `reported_terms` answers "which terms does
    the library back, and what is their whole distribution"; this answers the question a
    READ face asks — "the question wrote 周总; does the library back that as a way of
    addressing somebody, and whom" — and answers it with only the targets that actually
    cross the bar, because a runner-up that is 3 of 40 is ambiguity to display, never an
    identity to resolve a lookup to.
    """
    key = term_key(term) if term.strip() else ""
    if not key:
        return []
    group = reported_terms(rows).get(key)
    if not group:
        return []
    total = sum(r.support for r in group)
    return [row for row in group if is_reported(row, total)]


def render_term_match(row: TermSupport) -> str:
    """`matched via library address term "周总": answered 36, co_mention 11, 31 sources`

    A derived match states its own evidence inline, because it is NOT the same fact as a
    canonical `aliases` entry: that one is a confirmation a compile wrote against material,
    this one is arithmetic over turn structure that nothing has ruled on yet."""
    return f'matched via library address term "{row.term}": {row.signals()}'


def _sources_phrase(count: int) -> str:
    return f"{count} source" + ("s" if count != 1 else "")


def render_term_supports(rows: Iterable[TermSupport]) -> str:
    """`"阿宝" → im:Hao WEN — Hao WEN (answered 9, co_mention 4, 7 sources)`"""
    by_term: dict[str, list[TermSupport]] = {}
    for row in rows:
        by_term.setdefault(row.term, []).append(row)
    return "; ".join(
        f'"{term}" → ' + " · ".join(r.render() for r in group)
        for term, group in by_term.items()
    )


def address_terms_by_target(sources: Iterable[NormalizedSource]) -> dict[str, list[str]]:
    """Library-wide scan: target identity → the terms REPORTED for it with their support
    (`阿宝 ×13`). The keyless form of the projection — same rows, same rule, computed on
    demand instead of read from a table."""
    aggregate: dict[tuple[str, str], TermSupport] = {}
    for source in sources:
        accumulate_term_rows(aggregate, term_rows(source))
    out: dict[str, list[str]] = {}
    for group in reported_terms(aggregate.values()).values():
        total = sum(r.support for r in group)
        for row in group:
            if is_reported(row, total):
                out.setdefault(row.target, []).append(f"{row.term} ×{row.support}")
    return {target: out[target] for target in sorted(out)}


# --------------------------------------------------------------- the decision, asked once
# A reported term is evidence the library produced and nobody ruled on. Left there, it stays
# unruled forever: measured on a real library, a term reported under 31 sources for 88 days
# never reached the person's page while ten other documents' claims used it. The model does
# what the gate forces and skips what nothing forces, so the ROUND is made to end with the
# question answered — recorded as an alias, or declined. What the answer IS stays the
# contract's judgement; only the answering is mechanical.
#
# NOTHING IS STORED WHEN THE ANSWER IS "NO". Canonical records what is known about a person;
# a field listing the names that are NOT theirs is a column of distractions on the page a
# reader came to for the person. So a decline is round-local: `decline_alias` satisfies the
# gate for the round that calls it, writes nothing, and the page commits without a trace of
# the question.
#
# What stops the question coming back forever is a DERIVED clock, not a stored answer. The
# projection records `reported_since` — the day a (term → target) pair first crossed the
# reporting bar — and the canonical repository already records, free, the day each page was
# last written. A page WRITTEN on or after the day the term became reported has answered,
# whatever it wrote: the term was in front of the model, under the source, in the violation
# it had to clear, and what the round decided is the round's own business. A page written
# BEFORE that day never saw the question, so it is asked.
#
# That is the whole mechanism, and both halves of it are derived and rebuildable (I7): the
# stamp comes back from L0, the write day comes from git. Recording the term in `aliases` is
# still the way to say yes, and it is the only half worth keeping — a confirmation is
# knowledge, a refusal is not.
#
# The cost of asking once is honest and small: a term declined in a round that then writes
# nothing to the page is asked again next round, which is exactly right — nothing committed,
# so nothing answered.


#: (page, term) pairs stated per repair round. A library with hundreds of undecided terms
#: would otherwise hand the model a violation list nothing can act on in one round.
ALIAS_UNDECIDED_MAX = 8

#: `people.not_ready` — the refusal when a mirror this component judges by never loaded.
#: The alternative is the one thing a gate may not do: pass because it could not look. A
#: library-wide fact read from an empty mirror is not a weaker check, it is a different and
#: always-true one, so the round is refused instead and the next one retries the read.
#:
#: TWO mirrors, TWO refusals, and they are kept apart on purpose. The SOURCE BOUNDARY (who
#: the sources record, who spoke beside whom) is what the identity and alias rules are
#: measured against; the ADDRESS-TERM PROJECTION (a derived table another process writes) is
#: what the forced alias decision is measured against. One bit for both meant a failing
#: derived table refused a topic-only compile that needed no term at all — and worse, cleared
#: a healthy boundary mirror on its way out. Each is demanded only by the round that needs
#: it: nothing is judged blind, and nothing is refused for a fact it never asks.
NOT_READY = (
    "the people component could not load this library's source boundary; the compile is "
    "refused rather than judged blind. The identity and alias rules are measured against "
    "every source L0 holds, and a mirror that failed to load would answer about an empty "
    "library — allowing exactly the writes those rules exist to refuse. Nothing was written. "
    "The next compile reads it again."
)

NOT_READY_TERMS = (
    "the people component could not load this library's address-term projection; the compile "
    "is refused rather than judged blind. Whether a term the library's turns use for a person "
    "this round is reading about is REPORTED — and therefore has to end the round recorded as "
    "an alias or declined — is measured against that projection, and one that failed to load "
    "would answer that nothing is reported about anybody. Nothing was written. The next "
    "compile reads it again."
)


@dataclass(frozen=True)
class Decision:
    """One declined (term → identity) pair, for the length of ONE compile round.

    `term` is `term_key` and `identity` is normalized, so the decision matches the projection
    row it answers however the material spells either. It lives in the job-local state and
    nowhere else: the gate a moment later sees the question answered, the commit carries no
    record of it, and the next round asks again unless the page was written.

    The REASON the round gave is not carried either. A decline is not knowledge — an
    honorific several people earn is a real form of address, it simply is not this person's
    name — and the round's reasoning belongs where reasoning belongs, in what it wrote about
    the person.
    """

    term: str
    identity: str
    path: str = ""


# ------------------------------------------------------- names nothing structural can target
# The address evidence above needs a VOCATIVE: a turn opened with the term, or a turn that
# also addresses somebody. Measured on the same library, a nickname can occur 51 times and be
# a vocative once — the other fifty are third-person mentions (`和 momo 商量`), which no turn
# structure can point at a target. Nothing mechanical can name whom they mean.
#
# What IS mechanical is noticing that a repeated name-shaped token in this source matches
# nobody the source boundary knows. So the preamble states the tokens and stops: no target is
# suggested and no support is claimed, because there is none. Whether one of them names a
# person present here is contextual judgement, and the contract owns it — the way it reaches
# the library is the ordinary one, an `aliases` entry on that person's page.
#
# Two shapes, both channel-neutral and both a plain scan of the block text:
#   Latin   a capitalised or all-lowercase word of 2–12 letters (ALLCAPS is an acronym,
#           MixedCase is an identifier);
#   CJK     a 2–3 character core led by 和/跟/找/让/给/@ or trailed by 说/发/给/提/看/的 —
#           the particles that bracket a person in a mention. A longer unsegmented run is
#           left alone: guessing where a name ends inside it needs a lexicon, and a wrong
#           guess is worse than silence.
# Then the same exclusions the address terms use (`rejects_address_term`, one word list for
# both), every display name the library's sources record, every name the person pages already
# hold, and anything this source's preamble already states.

#: A token must repeat inside the source before it is worth a line: one mention of one word
#: is not a discovery, it is the text.
UNRESOLVED_MIN_COUNT = 2

#: Tokens listed under one source; the rest become a `…and N more`.
UNRESOLVED_MAX = 8

_CJK_RUN_RE = re.compile("[㐀-䶿一-鿿]+")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
#: The particles that bracket a person named in the third person.
_NAME_LEAD = "和跟找让给"
_NAME_FOLLOW = "说发给提看的"


def _latin_name_shaped(token: str) -> bool:
    """`Ravi`, `momo` — a capitalised or all-lowercase word of 2–12 letters. `API` is an
    acronym and `msgId` an identifier; neither is how anyone is named."""
    if not 2 <= len(token) <= 12:
        return False
    if not token.isascii() or not token[0].isalpha():
        return False
    return token.islower() or (token[0].isupper() and token[1:].islower())


def name_shaped_tokens(text: str) -> list[str]:
    """Every name-shaped token in one piece of text, in order of appearance (duplicates
    kept — the caller counts). Pure: no identities, no library, no state.

    A CJK core is 2–3 characters that a particle brackets on one side and a boundary closes
    on the other: `找小林，` (led, then the run ends), `小林说` (starts the run, then a verb).
    `和小林商量` is deliberately NOT read: three unsegmented characters follow the particle
    and choosing where the name stops inside them needs a lexicon. A miss says nothing; a
    guess would say something wrong.
    """
    out: list[str] = []
    for match in _LATIN_TOKEN_RE.finditer(text):
        token = match.group(0)
        if _latin_name_shaped(token):
            out.append(token)
    for match in _CJK_RUN_RE.finditer(text):
        run = match.group(0)
        at_mention = match.start() > 0 and text[match.start() - 1] == "@"
        for start in range(len(run)):
            led = run[start - 1] in _NAME_LEAD if start else at_mention
            if start and not led:
                continue  # a core only ever begins the run or follows a particle
            if not start and not led and run[0] in _NAME_LEAD:
                continue  # the particle itself is not the first character of a name
            for size in (2, 3):
                core = run[start : start + size]
                if len(core) < size or core[0] in _NAME_LEAD or core[-1] in _NAME_FOLLOW:
                    continue
                after = run[start + size : start + size + 1]
                if after in _NAME_FOLLOW and after:
                    out.append(core)  # a verb closes it: `小林说`
                elif led and not after:
                    out.append(core)  # a particle opened it and the run ends: `找小林`
    return out


def name_parts(name: str) -> list[str]:
    """One name → the comparison keys it accounts for: itself, and each of its letter runs.

    `Mei LIN` accounts for `mei` and `lin` as well as `mei lin`, because a source writes a
    person's name in as many pieces as it likes and none of those pieces is an unresolved
    name. Unfiltered by shape on purpose — this side subtracts, so being generous here can
    only ever say less, never say something wrong.
    """
    keys = [name_key(name)] if name.strip() else []
    keys.extend(term_key(part) for part in re.findall("[A-Za-z]+|[㐀-䶿一-鿿]+", name))
    return [key for key in keys if key]


def unresolved_names(
    source: NormalizedSource, *, known: Iterable[str] = (), stated: Iterable[str] = ()
) -> list[tuple[str, int]]:
    """Name-shaped tokens this source repeats that match nobody it knows, commonest first.

    `known` are the names the library can already account for (display names the source
    contracts record, the names the person pages hold); `stated` are the terms the preamble
    says elsewhere under this same source — a token is never said twice about one source.
    Whoever the source's OWN turns name — every speaker, every addressee, by label, display
    name or id — is subtracted here rather than asked of the caller: they are accounted for
    by definition, and the same subtraction then holds in every channel.

    Only the turns' own text is scanned. A speaker label is the renderer's, not the source's
    sentence, and a name that only ever appears as a label is not a mention of anything.

    A token's count is its occurrences in that text, not the bracketed ones: the signal a
    reader gets from `momo ×51` is how present the name is, and one bracketed mention is
    only what made it a candidate at all.
    """
    turns, _ = _turns(source)
    accounted = {key for name in known for key in name_parts(str(name))}
    accounted.update(term_key(str(term)) for term in stated)
    if turns:
        text = "\n".join(turn.text for turn in turns)
        for turn in turns:
            named = [turn.speaker, *(a.name for a in turn.addressees), *(a.key for a in turn.addressees)]
            if turn.speaker_target is not None:
                named.extend((turn.speaker_target.key, turn.speaker_target.name))
            accounted.update(key for name in named for key in name_parts(str(name)))
    else:
        text = "\n".join(block.text for block in source.blocks)
    if not text:
        return []
    candidates: dict[str, str] = {}
    for token in name_shaped_tokens(text):
        key = term_key(token)
        if key in candidates or key in accounted or rejects_address_term(token):
            continue
        candidates[key] = token
    counted: list[tuple[str, int]] = []
    for key, token in candidates.items():
        if token.isascii():
            count = len(re.findall(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text, re.I))
        else:
            count = text.count(token)
        if count >= UNRESOLVED_MIN_COUNT:
            counted.append((token, count))
    return sorted(counted, key=lambda pair: (-pair[1], pair[0]))


# ------------------------------------------------------------------------ the component


class PeopleComponent(BaseComponent):
    name = "people"

    def __init__(
        self,
        family: str,
        *,
        content: ContentStore | None = None,
        canonical: CanonicalStore | None = None,
    ) -> None:
        self.family = family
        self._content = content
        self._canonical = canonical
        # The address-term projection, mirrored per user. `source_preamble` and
        # `find_person` are SYNC seams inside prompt assembly and cannot await a query, so
        # they read this mirror — the same pattern the time component uses for the subject's
        # zone. It is filled from the store when the framework tells this component whose job
        # is about to run (`prepare` → `_warm`, once per process per user) and kept in step
        # afterwards by applying the same increments the store gets. Without a store it IS
        # the projection (tests, keyless offline checks).
        self._terms: dict[str, dict[tuple[str, str], TermSupport]] = {}
        # user -> person page path -> the day that page was last WRITTEN by a committed
        # patch, read from the canonical repository's own history (`written_on`). The other
        # half of the one-time ask: a page written on or after the day a term became
        # reported has already been shown the question. Filled by `prepare` — the head of a
        # COMPILE job, the only job that asks it — and empty means ASK.
        self._written: dict[str, dict[str, str]] = {}
        # Readiness, per half and per user. TWO bits, because there are two mirrors read from
        # two places for two rules: a derived table that is briefly unreadable must not make
        # this component say it does not know who the library's sources are.
        self._boundary_ready: set[str] = set()
        self._terms_ready: set[str] = set()
        self._cold_logged: set[str] = set()
        # user -> the REAL L0 source ids already folded into the two mirrors below. `_warm`
        # runs per job and adds only what it has not seen, so a long-lived worker's later
        # compiles see the sources imported since its first one without re-deriving the lot.
        self._mirrored: dict[str, set[str]] = {}
        # user -> (created_at, source_id) of the last source folded in, so the refresh above
        # is incremental AT THE DATABASE BOUNDARY and not merely in this process: without it
        # every compile, evolve and adopt job pulled every source envelope the library holds
        # across the wire to discard all but the new ones. Cleared with the mirror it
        # describes — a watermark that outlived its mirror would skip every earlier source
        # forever.
        self._watermark: dict[str, tuple] = {}
        # name key -> the identities the sources carry that display name for, per user. The
        # other half of the alias rule: a page may not take a name the library already knows
        # to be somebody else's. Filled from L0 in `_warm`, keyed by REAL source id.
        self._names: dict[str, dict[str, set[str]]] = {}
        # source id -> the non-owner identities that SPOKE in that source, per user. The
        # fact behind `people.identity_cospeakers`, and the alias rule's last resort: two
        # speakers of one conversation are two people, and neither of them needs a page for
        # that to hold. Filled from L0 META in `_warm` (no blocks are fetched), keyed by REAL
        # source id. Small: one frozenset of identities per multi-speaker source.
        self._cospeak: dict[str, dict[str, CoSpeaking]] = {}
        # The same two facts read off THIS JOB's own sources, kept apart from the mirrors
        # above and thrown away at the next job. The runner hands components the ALIASED
        # sources — `s01`, `s02`, a handle that means a different source in the next compile
        # — so nothing derived from them may be keyed into a cross-job structure: a later
        # job's `s01` would silently overwrite an earlier one's evidence and a correction
        # that should have been refused would pass. Cleared by `prepare` and by
        # `compile_tools`, so a handle can only ever describe the job that minted it.
        self._job_cospeak: dict[str, CoSpeaking] = {}
        self._job_names: dict[str, set[str]] = {}
        # Whose job is running. `prepare` is the framework's per-job announcement, and the
        # sync faces below (`gate_checks`, `validate_fields`) get no user of their own. Unset
        # means an EMPTY mirror — the page-side rules still hold and nothing is judged
        # against another user's library (I1).
        self._job_user: str = ""
        # The declines THIS ROUND made (`decline_alias`), and nothing else — no page
        # declares one, no table holds one. Cleared by `prepare` at the head of every job, so
        # a decision counts for the round that made it and a round that aborts leaves none.
        self._declines: dict[str, dict[tuple[str, str], Decision]] = {}
        # The identities THIS compile's sources carry, recorded in `compile_tools` (which the
        # runner calls before the gate) and read by `gate_checks`, which is handed documents
        # and never a source. The alias decision is demanded only about people this round is
        # actually reading about — a library-wide sweep would make every compile answer for
        # every page, which is the shape of rule that gets a library stuck.
        self._present: dict[str, set[str]] = {}
        # The names the person pages already hold (alias, title, slug), recorded in
        # `compile_tools` from the draft. The unresolved-names line subtracts them: a token
        # the library can already account for is not an unresolved name.
        self._page_names: dict[str, set[str]] = {}
        # The contact-book keys of the person pages, CONTENT-ADDRESSED: the cache key is the
        # sorted names the page carries, so a page that changed gets new keys with no
        # invalidation step, and one user's keys can never be handed to another user's
        # lookup even where two libraries hold the same path (I1). Computing them costs a
        # pinyin pass per name, which is why they are held at all; `prepare` clears them with
        # the mirrors and a ceiling keeps a long-lived recall process bounded.
        self._name_key_cache: dict[tuple[str, ...], frozenset[str]] = {}

    # --- face 0: the projection channel ------------------------------------------------

    def _persists(self) -> bool:
        return self._content is not None and hasattr(self._content, "add_people_terms")

    def _forget_boundary(self, key: str) -> None:
        """Drop this process's SOURCE-BOUNDARY mirror for one user, readiness and watermark
        included.

        Called when the boundary read fails. A half-loaded mirror is the dangerous state: it
        answers, so nothing looks wrong, and it answers about a smaller library than the one
        being judged. Dropping it costs one re-read on the next job and keeps the only two
        states this half has honest — the library, or not ready. The watermark goes with it:
        a cursor that survived its mirror would resume from the end of a library this process
        no longer holds.
        """
        self._boundary_ready.discard(key)
        self._mirrored.pop(key, None)
        self._names.pop(key, None)
        self._cospeak.pop(key, None)
        self._watermark.pop(key, None)
        self._name_key_cache.clear()

    def _forget_terms(self, key: str) -> None:
        """…and the ADDRESS-TERM mirror, on its own. A failed read of a derived table says
        nothing about who the library's sources are, so it takes nothing else with it."""
        self._terms_ready.discard(key)
        self._terms.pop(key, None)

    async def _warm(self, user_id: UserId) -> None:
        """Fill this user's two mirrors from the store, so the sync seams see the LIBRARY
        rather than only what this process has indexed — and RAISE if they cannot.

        BOTH halves are refreshed on every call, SEPARATELY, and neither failure touches the
        other's state. The source boundary incrementally, from a `(created_at, source_id)`
        watermark: the answer for a source never changes (its speakers and display names are
        what its envelope says), so a job reads the sources imported since the last one and
        nothing else — the fetch is bounded at the database boundary, not merely deduplicated
        after every envelope has crossed it. The term counts wholesale, because a count is
        exactly what DOES change: every index job adds to it, in another process, and a table
        read once per process would leave a long-lived compile worker stating the library as
        it stood at its first job forever. One ordered SELECT per job against a table keyed by
        (user, term, target) — one short row per distinct (term → target) pair, which is the
        cheap half of a compile, and unbounded only in the sense that `find_person(alias=…)`
        may ask about any term in the library mid-round and cannot await a query to find out.

        Refreshing the boundary at all is what lets the cross-job mirrors be keyed on real
        source ids: L0 is written before the compile job that reads it is enqueued, so this
        job's own sources are already listable here.

        A failure is not a smaller library, it is no answer for THAT half: the user is dropped
        from that half's readiness and the exception propagates. The fan-out above
        (`prepare_components`) is fail-soft and logs it; the WRITE-TIME faces are not, and
        refuse a round they cannot judge — but only the rounds that need the half that failed
        (`gate_checks`). Marking a user warmed before the reads — which this once did — turned
        one transient error into a gate that stayed open for the process's life.
        """
        key = str(user_id)
        failures: list[Exception] = []
        try:
            await self._warm_boundary(key, user_id)
        except Exception as exc:  # noqa: BLE001 — re-raised below, after the other half
            self._forget_boundary(key)
            failures.append(exc)
        else:
            self._boundary_ready.add(key)
        try:
            await self._warm_terms(key, user_id)
        except Exception as exc:  # noqa: BLE001
            self._forget_terms(key)
            failures.append(exc)
        else:
            self._terms_ready.add(key)
        if failures:
            # Both halves were attempted before anything is raised: a job whose terms table
            # is down still gets its boundary, and the round decides for itself whether it
            # needed the half that failed.
            raise failures[0]

    async def _warm_boundary(self, key: str, user_id: UserId) -> None:
        """The source boundary: every display name the source contracts recorded, keyed by
        name, and who SPOKE in each source. Meta only — no blocks are fetched — read forward
        from this user's watermark and derived like everything else here.

        `list_since` is the incremental read; a store that does not offer one (an in-memory
        stand-in, a store written before the cursor existed) is read whole and deduplicated
        by `_mirrored` as it always was. The cursor is `(created_at, source_id)` — the
        timestamp alone is not a cursor, because two sources imported in the same
        transaction share it and one of them would be skipped forever.
        """
        incremental = getattr(self._content, "list_since", None)
        listing = getattr(self._content, "list", None)
        if incremental is None and listing is None:
            return
        mirrored = self._mirrored.setdefault(key, set())
        names = self._names.setdefault(key, {})
        speaking = self._cospeak.setdefault(key, {})
        mark = self._watermark.get(key)
        if incremental is not None:
            raws = await incremental(user_id, after=mark)
        else:
            raws = await listing(user_id)
        for raw in raws:
            sid = str(raw.source_id)
            stamp = (getattr(raw, "created_at", None), sid)
            if stamp[0] is not None and (mark is None or stamp > mark):
                mark = stamp
            if sid in mirrored:
                continue
            mirrored.add(sid)
            record = source_speakers(raw)
            if record is not None:
                speaking[record.source_id] = record
            for mention in identity_mentions(raw):
                if mention.display_name.strip():
                    names.setdefault(name_key(mention.display_name), set()).add(
                        mention.identity
                    )
        if mark is not None:
            self._watermark[key] = mark

    async def _warm_terms(self, key: str, user_id: UserId) -> None:
        """The address-term projection, read whole. With no table wired there is nothing to
        read and the in-process aggregate IS the projection (tests, keyless offline checks),
        which is ready by construction."""
        if not self._persists():
            return
        rows = await self._content.people_terms(user_id)
        self._terms[key] = {
            (r["term"], r["target_identity"]): term_support_from_row(r) for r in rows
        }

    async def _warm_written(self, key: str, user_id: UserId) -> None:
        """The day each person page was last WRITTEN by a committed patch — the other half
        of the one-time ask, read off the canonical history.

        NOT part of the readiness bits, and not raised through: a mirror that failed to load
        here answers "no page has a known write day", and that answer makes every reported
        term ASKED. The `not_ready` doctrine exists for the opposite failure — a library-wide
        check that goes always-TRUE when its mirror is empty and lets through exactly the
        writes it exists to refuse. This one degrades toward asking a question twice, which
        costs a round's attention and never a wrong page, so it is logged and carried rather
        than turned into a refusal.

        Read at the head of a COMPILE job only. It is the committed history as this round
        found it, which is the right clock: what this round is about to write is not yet an
        answer to a question it is still being asked. The index job never asks it — a git
        walk per indexed source would buy that job nothing at all.
        """
        self._written.pop(key, None)
        if self._canonical is None or not hasattr(self._canonical, "written_on"):
            return
        try:
            self._written[key] = dict(
                await self._canonical.written_on(user_id, prefix=self._family_prefix())
            )
        except Exception:  # noqa: BLE001 — an unknown write day means ASK, never allow
            _log.warning(
                "people: could not read the canonical write days for user %s; every "
                "reported term will be asked about this round",
                key,
                exc_info=True,
            )

    def _ready(self, flags: set[str], user_id: object) -> bool:
        if self._content is None:
            return True
        key = str(user_id) if user_id is not None else self._job_user
        return bool(key) and key in flags

    def boundary_ready(self, user_id: object = None) -> bool:
        """Did this process load the SOURCE BOUNDARY for the user whose job is running?

        The half the identity and alias rules are measured against. With no content store
        wired there is nothing to read and the in-memory state IS the mirror (tests, keyless
        offline checks), so readiness is unconditional there.
        """
        return self._ready(self._boundary_ready, user_id)

    def terms_ready(self, user_id: object = None) -> bool:
        """…and the ADDRESS-TERM PROJECTION, the half the forced alias decision is measured
        against. A derived table, read from another process's writes."""
        return self._ready(self._terms_ready, user_id)

    def is_ready(self, user_id: object = None) -> bool:
        """Both halves loaded — the whole answer, for callers that want one bit."""
        return self.boundary_ready(user_id) and self.terms_ready(user_id)

    async def prepare(self, user_id: str) -> None:
        """The framework is about to run a job for this user through the SYNC seams — read
        the projection now, because they cannot.

        This is what makes the address-term line reach a compile at all: compile runs in its
        own process (the index job ran in another one, possibly on another machine), so the
        mirror `source_preamble` and `find_person` read is cold until this is awaited.

        It is also the only place the sync WRITE-TIME faces learn whose library they are
        judging: `gate_checks` and `validate_fields` are handed documents, never a user. One
        compile runs per process at a time (core `components/__init__.py:component_job` holds
        that open as a lock while any component is registered), so this is the job's user for
        as long as its sync seams run — and the faces that DO get a user of their own check
        that it is still this one.
        """
        self._job_user = str(user_id)
        # A previous job in this process left its own present-identity set behind, and the
        # alias decision is about the people THIS round reads about. `compile_tools` fills it
        # again a moment later; between here and there the rule simply demands nothing.
        self._present.pop(str(user_id), None)
        self._page_names.pop(str(user_id), None)
        # …and the declines IT made: a decline answers one round, and this is a new one.
        self._declines.pop(str(user_id), None)
        # …and its own sources, under handles that mean something else now.
        self._job_cospeak.clear()
        self._job_names.clear()
        # …and the page name keys, refreshed with the mirrors they are read beside. They are
        # content-addressed and so can never be WRONG, only stale in the sense of holding
        # pages a later job no longer reads; clearing them here keeps the process's memory
        # tied to the job it is running.
        self._name_key_cache.clear()
        await self._warm_written(str(user_id), UserId(user_id))
        await self._warm(UserId(user_id))

    async def on_source_indexed(self, user_id: str, source: NormalizedSource) -> None:
        """One source finished L1/L2 → add its (term → target) counts to the projection.

        ADDS, never replaces: what a term means is its distribution across the library, and a
        row that only ever held the last source's counts would answer a different question.
        The cost of that choice is that re-indexing one source without a rebuild counts it
        twice — acceptable because the rows are derived (I2) and `rebuild` re-derives them
        exactly, and visible because `sources` would then exceed the library's source count.
        """
        uid = UserId(user_id)
        rows = term_rows(source)
        if not rows:
            return
        await self._warm(uid)
        if self._persists():
            await self._content.add_people_terms(uid, rows)
        mirror = self._terms.setdefault(str(uid), {})
        accumulate_term_rows(mirror, rows)
        # …and the pairs this source pushed over the reporting bar are stamped with ITS day,
        # not with today: the stamp is a fact about the material, so a rebuild replaying L0
        # in source order arrives at the same dates from nothing.
        stamped = stamp_reported_since(mirror, source.raw.occurred_on()[:10])
        if stamped and self._persists():
            await self._content.set_people_terms_reported_since(
                uid, [{"term": t, "target_identity": i} for t, i in stamped],
                source.raw.occurred_on()[:10],
            )

    async def rebuild(self, user_id: str) -> None:
        """Re-derive this user's whole address-term projection from L0. The one operation
        that makes the accumulating write path safe: it starts from nothing.

        Everything this component stores is derived and this re-derives all of it (I7), and
        that includes the `reported_since` stamps the one-time ask runs on: the sources are
        replayed in `(occurred_on, source_id)` order, and each pair is stamped with the day
        of the source that pushed it over the bar. So the dates are a function of L0 alone —
        two rebuilds of the same library produce the same days, and a table stamped by the
        incremental path is re-derived into the answer the material actually supports.

        Nothing canonical is touched, here or anywhere else this component writes.
        """
        if self._content is None:
            return
        uid = UserId(user_id)
        key = str(uid)
        # Everything DERIVED starts from nothing — the counts and the source boundary alike,
        # the incremental cursor included: a rebuild that kept its watermark would re-derive
        # the library and then resume from a point past most of it.
        self._terms[key] = {}
        names = self._names[key] = {}
        speaking = self._cospeak[key] = {}
        mirrored = self._mirrored[key] = set()
        self._watermark.pop(key, None)
        if self._persists():
            await self._content.delete_people_terms(uid)
        # Replayed in the MATERIAL's order, not the import order `list` answers in: the
        # stamp below is the day of the source that made a term reportable, so the sequence
        # the sources are folded in has to be the sequence they happened in for a rebuild to
        # be a function of L0. `(occurred_on, source_id)` — the day alone is not an order,
        # because a day holds many sources and their arithmetic composes differently
        # depending on which is folded in first.
        stamps: dict[tuple[str, str], str] = {}
        listing = sorted(
            await self._content.list(uid),
            key=lambda r: (r.occurred_on()[:10], str(r.source_id)),
        )
        for raw in listing:
            # The source boundary re-derived alongside the counts: one listing, both mirrors,
            # and after a rebuild this process holds the library rather than half of it.
            mirrored.add(str(raw.source_id))
            record = source_speakers(raw)
            if record is not None:
                speaking[record.source_id] = record
            for mention in identity_mentions(raw):
                if mention.display_name.strip():
                    names.setdefault(name_key(mention.display_name), set()).add(
                        mention.identity
                    )
            if raw.kind not in ADDRESS_KINDS:
                continue
            normalized = await self._content.get(uid, raw.source_id)
            rows = term_rows(normalized)
            if not rows:
                continue
            if self._persists():
                await self._content.add_people_terms(uid, rows)
            accumulate_term_rows(self._terms[key], rows)
            day = raw.occurred_on()[:10]
            for pair in stamp_reported_since(self._terms[key], day):
                stamps[pair] = day
        if stamps and self._persists():
            # One write per distinct day, after the replay: the rows were deleted at the top
            # of this rebuild, so every stamp lands on a NULL and the order of the writes
            # cannot change the outcome.
            for day in sorted(set(stamps.values())):
                await self._content.set_people_terms_reported_since(
                    uid,
                    [
                        {"term": term, "target_identity": identity}
                        for (term, identity), stamped in sorted(stamps.items())
                        if stamped == day
                    ],
                    day,
                )
        # The mirror is now the library, so say so.
        await self._warm(uid)

    def _mirrored_terms(self, user_id: object) -> list[TermSupport]:
        """The projection as the SYNC seams see it. Cold means an empty library view, and the
        seams that read it then say only what THIS source shows — never a wrong count.

        `prepare` is what fills it, and the framework awaits `prepare` at the head of every
        job that renders these seams. So a cold mirror with a store wired means the hook did
        not run — the seam is about to render a silently smaller library, and the log below
        is the tripwire that says so. Once per (process, user): a warning that repeats per
        source is a warning nobody reads.
        """
        key = str(user_id)
        if self._persists() and key not in self._terms_ready and key not in self._cold_logged:
            self._cold_logged.add(key)
            _log.debug(
                "people: the address-term mirror is cold for user %s — prepare() did not run "
                "before a sync seam; the library-wide terms will be absent from it",
                key,
            )
        return list(self._terms.get(key, {}).values())

    async def library_terms(self, user_id: UserId) -> list[TermSupport]:
        """The projection for the async seams: from the store when one is wired (no per-call
        scan), else the in-process aggregate, else — nothing indexed in-process and no store
        — an on-demand scan over L0, which is what this component did before it had a table.
        """
        if self._persists():
            return [term_support_from_row(r) for r in await self._content.people_terms(user_id)]
        cached = self._mirrored_terms(user_id)
        if cached:
            return cached
        if self._content is None:
            return []
        aggregate: dict[tuple[str, str], TermSupport] = {}
        for raw in await self._content.list(user_id):
            if raw.kind not in ADDRESS_KINDS:
                continue
            accumulate_term_rows(
                aggregate, term_rows(await self._content.get(user_id, raw.source_id))
            )
        return list(aggregate.values())

    # --- the declines -------------------------------------------------------------

    def declines(self, user_id: object) -> dict[tuple[str, str], Decision]:
        """The (term key, identity) pairs THIS ROUND declined. Job-local and nowhere else:
        `prepare` clears it at the head of every job and `decline_alias` is the only thing
        that adds to it, so the gate sees the round's own answer and the commit carries no
        record of it."""
        return self._declines.get(str(user_id), {})

    def is_declined(self, user_id: object, term: str, identity: str) -> bool:
        return (term_key(term), normalize_identity(identity)) in self.declines(user_id)

    def written_on(self, user_id: object, path: str) -> str:
        """The day `path` was last written by a committed patch — `""` when the library's
        history does not name it (a page created this round, or a canonical face this
        deployment did not wire). Read from the mirror `prepare` filled, so it is the
        COMMITTED history as this round found it: what this round is about to write is not
        an answer to a question this round is still being asked."""
        return self._written.get(str(user_id), {}).get(path, "")

    # --- family membership and field access --------------------------------------

    def is_member(self, path: str) -> bool:
        return family_of(path, [self.family]) is not None

    def _family_prefix(self) -> str:
        """The literal path prefix of this component's family — `memory/people/` out of
        `memory/people/{slug}.md`. A pathspec, so the history walk behind `written_on`
        visits the commits that touched this family and not the whole library's."""
        return self.family.split("{", 1)[0]

    @staticmethod
    def identities_of(frontmatter: Mapping) -> list[str]:
        return split_csv(frontmatter.get(IDENTITIES_KEY))

    @staticmethod
    def aliases_of(frontmatter: Mapping) -> list[str]:
        return split_csv(frontmatter.get(ALIASES_KEY))

    # --- face 1: gate ---------------------------------------------------------------

    def known_names(self, user_id: object = None) -> dict[str, set[str]]:
        """The library's display names as the SYNC faces see them: name key → the identities
        the sources record it for. The L0 mirror (`prepare`) plus THIS job's own sources.

        Empty when nothing has told this component whose job is running: the page-side half
        of the alias rule still holds, and no name is ever judged against another user's
        library (I1).
        """
        key = str(user_id) if user_id is not None else self._job_user
        if not key:
            return {}
        merged = {name: set(ids) for name, ids in self._names.get(key, {}).items()}
        if key == self._job_user:
            for name, ids in self._job_names.items():
                merged.setdefault(name, set()).update(ids)
        return merged

    def _display_names(self) -> dict[str, set[str]]:
        return self.known_names()

    def _cospeaking_sources(self) -> list[CoSpeaking]:
        """This user's multi-speaker sources, earliest first — the order that decides WHICH
        source a refusal names, so the same page is always refused with the same words. The
        L0 mirror plus this job's own sources, which is why the job-local half exists at all:
        the compile's own material must be judged by the same fact as the library's.
        Empty until something tells this component whose job is running (I1)."""
        if not self._job_user:
            return []
        records = dict(self._cospeak.get(self._job_user, {}))
        records.update(self._job_cospeak)
        return sorted(
            records.values(),
            key=lambda record: (record.occurred_on, record.source_id),
        )

    def _cospeak_source(self, one: str, other: str) -> CoSpeaking | None:
        """The earliest source where both identities SPOKE, or `None` if none did."""
        a, b = normalize_identity(one), normalize_identity(other)
        if a == b:
            return None
        for record in self._cospeaking_sources():
            if a in record.speakers and b in record.speakers:
                return record
        return None

    def _page_claims(
        self, docs: Mapping[str, object], path: str
    ) -> dict[str, list[NameClaim]]:
        """Every name the OTHER person pages already hold — alias, title and slug alike."""
        claims: dict[str, list[NameClaim]] = {}
        for other in sorted(docs):
            if other == path or not self.is_member(other):
                continue
            doc = docs[other]
            fm = doc.frontmatter or {}
            named = [(alias, "alias") for alias in self.aliases_of(fm)]
            named.append((document_title(doc), "title"))
            named.append((str(fm.get("slug") or ""), "slug"))
            for name, kind in named:
                key = name_key(name)
                if key:
                    claims.setdefault(key, []).append(NameClaim(name.strip(), kind, other))
        return claims

    def field_problems(
        self,
        docs: Mapping[str, object],
        path: str,
        *,
        identities: Iterable[str] | None = None,
        aliases: Iterable[str] | None = None,
    ) -> list[tuple[str, str]]:
        """The whole mechanical judgement over one page's structured fields, in ONE place —
        the gate is the final arbiter, the write tools say the same thing earlier.

        Three FACTS, and nothing else. (1) An identity is `scheme:value` and at most one
        page binds it: one email is one person, and a second page claiming it is a subject
        splitting in two. (2) Two PERSON IDS that both SPEAK in one source are two people,
        so one page may not bind both — the fact (1) cannot see, because the other speaker
        needs no page of their own for it to hold, and the one that catches a page whose
        `identities` were lifted whole from a group chat's title. Person ids come from the
        channels that have them (`im` senders, `meeting` speakers); an email thread's two
        `from` addresses may be one human and contribute nothing here (`source_speakers`).
        (3) An alias is not
        somebody else's name — not another person page's alias, title or slug, and not a
        display name the sources record for an identity this page does not hold, nor one
        they record for an identity that speaks beside this page's own. A group chat titled
        "Yong BAI, Jie WANG, Fan WANG" is three people, and the page for one of them may
        not take the other two.

        Everything else about these fields is the contract's JUDGEMENT and is written whole
        on every rewrite: the frontmatter is a snapshot of the picture, not a ledger, so a
        wrong entry is gone after the next rewrite instead of forever.
        """
        doc = docs.get(path)
        fm = (doc.frontmatter or {}) if doc is not None else {}
        identities = (
            self.identities_of(fm) if identities is None else [str(i) for i in identities]
        )
        aliases = self.aliases_of(fm) if aliases is None else [str(a) for a in aliases]
        out: list[tuple[str, str]] = []

        bound_elsewhere: dict[str, str] = {}
        for other in sorted(docs):
            if other == path or not self.is_member(other):
                continue
            for identity in self.identities_of(docs[other].frontmatter or {}):
                bound_elsewhere.setdefault(normalize_identity(identity), other)
        # The identities this page may still be holding legitimately, in written order: an
        # identity that co-speaks with one of them is the offender, and it is measured
        # against the kept ones only, so N ids from one group chat cost N-1 refusals rather
        # than every pair of them.
        kept: list[str] = []
        for identity in identities:
            if not _IDENTITY_RE.match(identity):
                out.append(
                    (
                        "people.identity_shape",
                        f"identity {identity!r} is not `scheme:value` (e.g. "
                        f"mailto:name@example.com, im:u_123, meeting:p_7).",
                    )
                )
                continue
            owner = bound_elsewhere.get(normalize_identity(identity))
            if owner:
                out.append(
                    (
                        "people.identity_duplicate",
                        f"identity {identity} is bound by `{owner}` as well; one identity "
                        f"belongs to one page. Keep it on the page whose subject it is, "
                        f"and leave it out of the other.",
                    )
                )
            clash: tuple[str, CoSpeaking] | None = None
            for held in kept:
                record = self._cospeak_source(held, identity)
                if record is not None:
                    clash = (held, record)
                    break
            if clash is None:
                kept.append(identity)
                continue
            held, record = clash
            out.append(
                (
                    "people.identity_cospeakers",
                    f"{identity} and {held} both speak in {record.render()}; one page "
                    f"cannot bind two speakers of one conversation — keep the identity of "
                    f"this page's subject, and give the other person their own page if "
                    f"they earn one.",
                )
            )

        own_names = {name_key(str(fm.get("slug") or ""))}
        if doc is not None:
            own_names.add(name_key(document_title(doc)))
        own_names.discard("")
        own_identities = {normalize_identity(i) for i in identities}
        claims = self._page_claims(docs, path)
        known = self._display_names()
        for alias in aliases:
            key = name_key(alias)
            if not key or key in own_names:
                continue
            carriers = sorted(known.get(key, set()))
            own_carrier = any(normalize_identity(i) in own_identities for i in carriers)
            rivals = [i for i in carriers if normalize_identity(i) not in own_identities]
            # The co-speaking fact, said from the alias side: an identity that takes a turn
            # beside this page's own is provably a different person, so a name the sources
            # record for THEM is theirs — no count and no page of their own required.
            cospeaking = [
                i
                for i in rivals
                if any(self._cospeak_source(i, mine) is not None for mine in own_identities)
            ]
            if own_carrier:
                # The sources name one of THIS page's own identities that way — the person's
                # own name, however many other people are present in the same source. Unless
                # one of the others SPOKE beside them: the name is then demonstrably shared
                # with a different person, and only that half of the collision is stated —
                # the rest is what the page was being forgiven for a moment ago.
                if not cospeaking:
                    continue
                hits = [NameClaim(alias.strip(), "cospeaker", i) for i in cospeaking]
            else:
                hits = list(claims.get(key, ()))
                hits.extend(
                    NameClaim(
                        alias.strip(), "cospeaker" if i in cospeaking else "identity", i
                    )
                    for i in rivals
                )
            if hits:
                out.append(
                    (
                        "people.alias_collision",
                        f"alias {alias.strip()!r} is already "
                        + " and ".join(hit.render() for hit in hits)
                        + ". An alias is how THIS person is addressed; a name the library "
                        f"knows as someone else's is not one — leave it out, and record it "
                        f"on that person's page if it belongs anywhere.",
                    )
                )
        return out

    def validate_fields(self, path, fields, docs) -> list[str]:
        """The same facts at the WRITE face, on what this call actually writes.

        Fields are written whole, so the call IS the page's next state: incoming
        `identities` replace the declared ones, which is what keeps the ordinary flow open —
        a page may take the display name of an identity the same call records. A field this
        call does not carry is not this call's business; the gate judges the result anyway.
        """
        if not self.is_member(path) or path not in docs:
            return []
        written = {str(key) for key in (fields or {})}
        if not written & {IDENTITIES_KEY, ALIASES_KEY}:
            return []
        # The SOURCE BOUNDARY is the half these two fields are judged against — who the
        # library's sources record, and who spoke beside whom. The term projection has no
        # say here, so a table that is briefly unreadable does not refuse this write.
        if not self.boundary_ready():
            return [NOT_READY]
        fm = docs[path].frontmatter or {}
        identities = (
            split_csv(fields.get(IDENTITIES_KEY))
            if IDENTITIES_KEY in written
            else self.identities_of(fm)
        )
        aliases = split_csv(fields.get(ALIASES_KEY)) if ALIASES_KEY in written else []
        return [
            message
            for kind, message in self.field_problems(
                docs, path, identities=identities, aliases=aliases
            )
            if IDENTITIES_KEY in written or kind == "people.alias_collision"
        ]

    def gate_checks(self, docs, base_docs) -> list[Violation]:
        """The final arbiter, over the person pages this round TOUCHED.

        Touched is the framework's own predicate (`compile/patch.py:touched_this_round`): the
        page's body OR its frontmatter differs from what it held at the head of the round, or
        the page is new. Not "its frontmatter changed" — a claim appended to a person page is
        a write like any other, and the rule that measures what the page DECLARES applies the
        moment the page is written, whatever half of it the round wrote. Judging only the
        frontmatter left the pages this rule exists for uncorrected through their commonest
        future write.

        A page nobody wrote is still left as it stands, even carrying a collision from an
        older compile: one wrong page must not make every later compile in that library
        unpassable, and the repair is always available inside the round that touches it —
        `set_fields` writes the field whole, so dropping the rival identity costs one call.
        The OTHER side of a collision is always the whole library: an untouched page still
        holds its name and its identities.
        """
        touched = [
            path
            for path in sorted(docs)
            if self.is_member(path)
            and touched_this_round(docs[path], base_docs.get(path))
        ]
        present = self._present.get(self._job_user, set())
        # READINESS IS DEMANDED PER RULE, not per component. The identity and alias rules read
        # the source boundary, and this round only reaches them if it wrote a person page that
        # DECLARES one of those fields, or if its own sources carry an identity at all (the
        # page it is about to be written into may not exist yet). A round that touches no
        # person page and carries no identity — a topic-only compile, an evolve over the
        # taxonomy, an empty library — asks the boundary nothing, and refusing it would be
        # this component blocking work it has no rule about.
        needs_boundary = bool(present) or any(
            self.identities_of(docs[path].frontmatter or {})
            or self.aliases_of(docs[path].frontmatter or {})
            for path in touched
        )
        if needs_boundary and not self.boundary_ready():
            return [Violation("people.not_ready", self.family, NOT_READY)]
        violations: list[Violation] = []
        for path in touched:
            for kind, message in self.field_problems(docs, path):
                violations.append(Violation(kind, path, message))
        # …and the forced decision reads the OTHER mirror, so it demands the other half — and
        # only when it applies at all: no identity in this round's sources, nothing to decide.
        if not present:
            return violations
        if not self.terms_ready():
            violations.append(
                Violation("people.not_ready", self.family, NOT_READY_TERMS)
            )
            return violations
        return violations + self.undecided_terms(docs)

    def undecided_terms(self, docs: Mapping[str, object]) -> list[Violation]:
        """`people.alias_undecided` — the round must END with every reported term decided.

        The problem this exists for is not a wrong answer, it is no answer. The preamble
        shows the model, under every source, the terms the whole library uses for the people
        present in it; the contract asks for aliases; and measured over 88 days on a real
        library the page still held none while ten other documents' claims used the term. A
        model reliably does what the gate forces and skips maintenance nothing forces, so the
        decision is made unavoidable and the JUDGEMENT is left exactly where it was: record
        the term as an alias if the material confirms it, or decline it on the page.

        ASKED ONCE. The question closes when the page is next WRITTEN, and it closes on
        derived state — the projection's `reported_since` (the day the pair first crossed the
        reporting bar) against the canonical history's day of that page's last commit. A page
        written on or after that day has been shown the question: the term was under its
        source in the preamble and in the violation the round had to clear, and what the
        round decided is the round's own business. A page written before it never saw the
        question, so it is asked. Nothing is stored to say "asked and answered" — the two
        dates the library already holds say it, and both are rebuildable (I7).

        The two "unknown" cases both mean ASK, and deliberately: a page created this round
        has no committed write day, and a projection row from a library that predates the
        stamp has none either. Silence is only ever earned by two dates that exist and order
        the right way; an absent date is a library that cannot say the question was seen.

        Recording the alias is one answer, `decline_alias` is the other, and the second one
        holds for THIS ROUND only — it satisfies the gate and writes nothing, so a round that
        declines and then writes the page commits an answer, while a round that declines and
        aborts leaves the question exactly where it was.

        Scope is this round's material, twice over: only identities THIS compile's sources
        carry (`compile_tools` recorded them; without a source there is nothing to decide
        about), and only terms the library already REPORTS for them. A page created this
        round counts — it is a page about somebody the round is reading about, which is the
        whole test.

        Capped, and the cap SAYS how much it cut. A library with hundreds of undecided terms
        would otherwise answer one round's first violation with a list nothing can act on.
        """
        present = self._present.get(self._job_user, set())
        if not present:
            return []
        rows = self._mirrored_terms(self._job_user)
        declined = self.declines(self._job_user)
        pending: list[tuple[str, TermSupport]] = []
        for path in sorted(docs):
            if not self.is_member(path):
                continue
            doc = docs[path]
            fm = doc.frontmatter or {}
            recorded = {name_key(a) for a in self.aliases_of(fm)}
            # The day this page last reached a commit — never what this round is about to
            # write, which is not yet an answer to a question this round is still being asked.
            written = self.written_on(self._job_user, path)
            for row in self.page_terms(rows, doc):
                identity = normalize_identity(row.target)
                if identity not in present:
                    continue
                # …recorded as an alias, this round or an earlier one — the one answer that
                # is knowledge, and the one that is kept.
                if row.term in recorded:
                    continue
                # …declined in THIS round: job-local, nothing written, gone at the next job.
                if (row.term, identity) in declined:
                    continue
                # …or asked already and answered by the page being written since.
                if written and row.reported_since and written >= row.reported_since:
                    continue
                pending.append((path, row))
        pending.sort(key=lambda item: (item[0], item[1].term))
        shown, cut = pending[:ALIAS_UNDECIDED_MAX], len(pending) - ALIAS_UNDECIDED_MAX
        violations = [
            Violation(
                "people.alias_undecided",
                path,
                f'the address term "{row.term}" is reported for {row.render()} — an identity '
                f"this page binds and this compile's sources carry — and this page has not "
                f"answered it. Decide it before the round ends: record it with the page's "
                f"other aliases if the material confirms this is how this person is "
                f"addressed (`rewrite_overview` / `set_fields`, `aliases` written whole), or "
                f'call decline_alias(path="{path}", term="{row.term}", reason=…) if it is '
                f"not their name — that answer is this round's and is stored nowhere, so "
                f"write this page in the round you decline in and the question is closed.",
            )
            for path, row in shown
        ]
        if cut > 0 and violations:
            last = violations[-1]
            violations[-1] = Violation(
                last.kind,
                last.path,
                last.detail + f" …and {cut} more undecided terms, listed once these are.",
            )
        return violations

    # --- face 2: outline ---------------------------------------------------------------

    def outline_tail(self, doc) -> str | None:
        if not self.is_member(doc.path):
            return None
        fm = doc.frontmatter or {}
        parts: list[str] = []
        if ids := self.identities_of(fm):
            parts.append("identities: " + ", ".join(ids))
        if aliases := self.aliases_of(fm):
            parts.append("aliases: " + ", ".join(aliases))
        return " · ".join(parts) or None

    # --- face 3: compile tool -----------------------------------------------------------

    def page_name_keys(self, doc) -> frozenset[str]:
        """Every contact-book key this person page can be reached by: its title, its
        confirmed aliases, its slug, and the NAME half of the identities it binds (an
        `im:Kexin ZHOU` carries one; an email or an account handle does not).

        One normaliser, `name_keys`, is used here and on the query side — the page and the
        question are expanded by exactly the same rules, which is the only reason a match
        means anything.
        """
        fm = doc.frontmatter or {}
        names = (
            document_title(doc),
            str(fm.get("slug") or ""),
            *self.aliases_of(fm),
            *(identity_display_name(i) for i in self.identities_of(fm)),
        )
        signature = tuple(sorted({n.strip() for n in names if n and n.strip()}))
        if not signature:
            return frozenset()
        cached = self._name_key_cache.get(signature)
        if cached is None:
            if len(self._name_key_cache) >= NAME_KEY_CACHE_MAX:
                self._name_key_cache.clear()
            cached = frozenset().union(*(name_keys(name) for name in signature))
            self._name_key_cache[signature] = cached
        return cached

    def find_by_name(self, docs: Mapping[str, object], *, alias: str) -> list[NameMatch]:
        """`find_in`'s CONTACT-BOOK twin: the family pages whose name keys the query's keys
        meet, ranked best first (`NameMatch.rank`), then by path.

        The rank is what keeps a wide match from becoming a vague one. Measured on a real
        library, a two-character given name met the right page on the whole given name and
        an unrelated page on one syllable of somebody else's alias (`kexin` against `xin`).
        Both are tier 1 and both met exactly one key; the LENGTH of the key that met is what
        says which of them is the answer.
        """
        query = name_keys(alias)
        if not query:
            return []
        tokens = name_tokens(alias)
        # A one-character query is matched EXACTLY and never as a prefix: `周` is a surname
        # and a real answer, `周` as the first character of every 周-something is not.
        prefix = len(_normalized_name(alias).replace(" ", "")) >= PREFIX_MIN_CHARS
        out: list[NameMatch] = []
        for path in sorted(docs):
            if not self.is_member(path):
                continue
            tier, hits, span = match_tier(
                query, self.page_name_keys(docs[path]), tokens=tokens, prefix=prefix
            )
            if tier:
                out.append(NameMatch(path, tier, hits, alias.strip(), span))
        out.sort(key=lambda m: (*m.rank, m.path))
        return out

    def name_candidates(
        self, docs: Mapping[str, object], *, alias: str, cap: int = NAME_MATCH_CANDIDATES
    ) -> list[NameMatch]:
        """The best answer the name keys have — AMBIGUITY INCLUDED.

        A library with two 可欣 in it has two answers to `可欣`, and a lookup that picked one
        of them would be inventing the half it dropped. So every page that ties on the best
        RANK comes back, capped, and the caller states them all: the model disambiguates
        from the definitions, and the reader sees why there was a choice. A page that beat
        the others on any part of the rank is the single winner it looks like.
        """
        matches = self.find_by_name(docs, alias=alias)
        if not matches:
            return []
        best = matches[0].rank
        return [m for m in matches if m.rank == best][:cap]

    def resolve_by_name(
        self, docs: Mapping[str, object], *, alias: str
    ) -> tuple[list[NameMatch], list[NameMatch]]:
        """The name side of a lookup, as (what ANSWERS, what answers only if nothing else
        does) — two attempts, and the better tier wins between them.

        The raw question answers when it lands on tier 1. Otherwise the honorific comes off
        (`可欣姐` → `可欣`) and THAT form gets its turn, because a raw form matching three
        people by their first syllable is not what the question asked: measured on a real
        library, `可欣姐` reached three unrelated pages as a prefix while `可欣` reached the
        two people actually called that. The raw form's weak hits are not thrown away, only
        held back.

        Between the two, in `_resolve_pages`, sits the address-term projection: a term the
        whole library concentrates on one person is evidence out of the corpus, while
        stripping an honorific is a guess about the question, and evidence goes first.
        """
        raw = self.name_candidates(docs, alias=alias)
        if raw and raw[0].tier == 1:
            return raw, []
        plain = strip_honorific(alias)
        stripped = self.name_candidates(docs, alias=plain) if plain else []
        if stripped:
            return stripped, raw
        return [], raw

    def find_in(self, docs: Mapping[str, object], *, identity: str = "", alias: str = "") -> list[str]:
        """Paths of family pages binding `identity` or naming `alias` (alias also matches
        the page's slug and title). EXACT, case-insensitive — the strict tier every lookup
        tries first, and the one a confirmation is measured by. What a near miss should
        reach is `find_by_name` above, one tier down and labelled as what it is."""
        want_id = normalize_identity(identity) if identity.strip() else ""
        want_alias = alias.strip().casefold()
        hits: list[str] = []
        for path in sorted(docs):
            if not self.is_member(path):
                continue
            doc = docs[path]
            fm = doc.frontmatter or {}
            if want_id and want_id in {normalize_identity(i) for i in self.identities_of(fm)}:
                hits.append(path)
                continue
            if want_alias:
                names = {a.casefold() for a in self.aliases_of(fm)}
                names.add(str(fm.get("slug") or "").casefold())
                names.add(document_title(doc).casefold())
                if want_alias in names:
                    hits.append(path)
        return hits

    def find_by_term(
        self, docs: Mapping[str, object], rows: Iterable[TermSupport], *, alias: str = ""
    ) -> list[tuple[str, TermSupport]]:
        """`find_in`'s DERIVED twin: pages reached through a REPORTED address term.

        Canonical `aliases` are confirmations — a compile read the material and wrote them.
        The projection holds something else: how the library's turns actually address
        people, with the support behind it. That is a derived fact, so it never becomes a
        frontmatter entry on its own (only a compile touching the person may confirm it) —
        but it is a perfectly good way to RESOLVE A LOOKUP, and refusing to use it meant a
        question written in the vocabulary the library itself uses missed the page.

        Returns (path, the row that matched) so every caller can state the evidence; a page
        reached by two terms is listed once, under the strongest.
        """
        out: list[tuple[str, TermSupport]] = []
        seen: set[str] = set()
        for row in reported_targets(rows, alias):
            for path in self.find_in(docs, identity=row.target):
                if path in seen:
                    continue
                seen.add(path)
                out.append((path, row))
        return out

    def page_terms(self, rows: Iterable[TermSupport], doc) -> list[TermSupport]:
        """The address terms REPORTED for any identity this page binds, strongest first."""
        bound = {normalize_identity(i) for i in self.identities_of(doc.frontmatter or {})}
        if not bound:
            return []
        hits: list[TermSupport] = []
        for group in reported_terms(rows).values():
            total = sum(r.support for r in group)
            hits.extend(
                row
                for row in group
                if is_reported(row, total) and normalize_identity(row.target) in bound
            )
        return sorted(hits, key=lambda r: (-r.support, r.term))

    async def _resolve_pages(
        self,
        user_id: UserId,
        docs: Mapping[str, object],
        *,
        alias: str = "",
        identity: str = "",
        rows: list[TermSupport] | None = None,
    ) -> tuple[list[str], dict[str, TermSupport], dict[str, NameMatch]]:
        """The person page(s) this lookup names, in four tiers, the first that answers
        winning outright:

        1. CANONICAL EXACT — a declared identity, alias, slug or title. A confirmation, and
           a confirmation is never overruled by anything below it.
        2. CONTACT-BOOK NAME KEYS — the same canonical names read in every convention they
           can be written in (`可欣` → `Kexin ZHOU`), the honorific taken off the question
           where the raw form does not reach tier 1 (`resolve_by_name`). Still canonical
           material, matched mechanically; labelled `via:name-match tier<n>` to the caller.
        3. THE ADDRESS-TERM PROJECTION — how the library's turns actually address people,
           with library-wide support behind it. Unchanged, and it runs on the raw query.
        4. THE NAME KEYS' WEAK HITS — a raw form that only ever matched as a prefix. Last,
           because a reported term is evidence out of the corpus and a prefix is a
           resemblance.

        The three returned faces are the paths, path → the term row that matched, and path →
        the name match — so every caller can state which tier answered it.

        `rows` lets a caller that already read the projection hand it in, so one request
        never queries the same table twice.
        """
        hits = self.find_in(docs, identity=identity, alias=alias)
        if hits or not alias.strip():
            return hits, {}, {}
        named, weak = self.resolve_by_name(docs, alias=alias)
        if named:
            return [m.path for m in named], {}, {m.path: m for m in named}
        if rows is None:
            rows = await self.library_terms(user_id)
        matched = self.find_by_term(docs, rows, alias=alias)
        if matched:
            return [path for path, _ in matched], dict(matched), {}
        if weak:
            return [m.path for m in weak], {}, {m.path: m for m in weak}
        return [], {}, {}

    def describe(self, path: str, doc) -> str:
        fm = doc.frontmatter or {}
        tail = self.outline_tail(doc) or "(no identities or aliases declared)"
        return f"- `{path}` — {document_title(doc)} · {tail}" if fm else f"- `{path}`"

    def render_name_matches(
        self, docs: Mapping[str, object], matches: list[NameMatch]
    ) -> str:
        """The contact-book answer as text, for the compile tool: the page(s), what matched,
        and the one thing a compile can do about it. A tie is printed as a tie — the round
        reads the material and knows which of them it is about; this lookup does not."""
        lines = [
            f"{self.describe(m.path, docs[m.path])} · ({m.render()})" for m in matches
        ]
        if len(matches) > 1:
            lines.append(
                "More than one page's name matches that form equally well. The material "
                "this round is reading is what says which of them it means — this lookup "
                "cannot."
            )
        lines.append(
            "No page DECLARES the name in that form. If the material confirms it is this "
            "person's, the page's `aliases` field is where the form becomes a confirmation "
            "— and the next lookup finds it exactly."
        )
        return "\n".join(lines)

    def profile_tail(self, doc) -> str:
        """The frontmatter line for the `person_profile` header. Same two fields the outline
        tail shows, but the aliases are labelled `confirmed`: the profile prints the derived
        address terms on the very next line, and the two lists must not read as one."""
        fm = doc.frontmatter or {}
        parts: list[str] = []
        if ids := self.identities_of(fm):
            parts.append("identities: " + ", ".join(ids))
        if aliases := self.aliases_of(fm):
            parts.append("aliases (confirmed): " + ", ".join(aliases))
        return " · ".join(parts)

    def compile_tools(self, draft, *, sources=()) -> list[StructuredTool]:
        component = self
        # This compile's own turn structure, read once per job and shared by the tools: a
        # miss on a nickname is exactly when the address evidence under the sources matters.
        evidence: list[AddressCandidate] = []
        draft_user = ""
        for source in sources:
            evidence.extend(address_evidence(source))
            draft_user = str(source.raw.user_id)
        if draft_user:
            # This job's user, for the sync write-time faces. `prepare` announced one a
            # moment ago; if the sources say somebody else, two jobs are interleaving in this
            # process and every library-wide fact below would be read out of the wrong
            # mirror. Refuse — I1 is not "no cross-user read happened to occur".
            if self._job_user and self._job_user != draft_user:
                raise RuntimeError(
                    f"people: compile_tools was called for user {draft_user} while the job "
                    f"prepared in this process is {self._job_user}. One compile per process "
                    f"at a time (core components/__init__.py:component_job)."
                )
            self._job_user = draft_user
            # This job's own source boundary, kept JOB-LOCAL. These are the ALIASED sources
            # (`sNN`), so nothing read off them may be keyed into a cross-job mirror: the same
            # handle means another source in the next compile. The library half of both facts
            # came from L0 under real ids in `prepare` — including these very sources, which
            # were written to L0 before this job was enqueued. Same definition of "a display
            # name the sources record" as `_warm` uses — `identity_mentions`, from the source
            # contracts themselves.
            self._job_cospeak.clear()
            self._job_names.clear()
            present = self._present.setdefault(draft_user, set())
            for source in sources:
                record = source_speakers(source.raw)
                if record is not None:
                    self._job_cospeak[record.source_id] = record
                for mention in identity_mentions(source.raw):
                    present.add(normalize_identity(mention.identity))
                    if mention.display_name.strip():
                        self._job_names.setdefault(
                            name_key(mention.display_name), set()
                        ).add(mention.identity)
            # The names the person pages already hold. The runner builds these tools before
            # it renders the task text, so this is what the unresolved-names line under each
            # source subtracts — a token the library can already account for is not a
            # discovery. Read from the draft, so it costs no I/O and cannot go stale.
            page_names = self._page_names.setdefault(draft_user, set())
            for path, doc in draft.documents().items():
                if not self.is_member(path):
                    continue
                fm = doc.frontmatter or {}
                page_names.update(name_key(a) for a in self.aliases_of(fm))
                page_names.add(name_key(document_title(doc)))
                page_names.add(name_key(str(fm.get("slug") or "")))
            page_names.discard("")

        def find_person(identity: str = "", alias: str = "") -> str:
            docs = draft.documents()
            hits = component.find_in(docs, identity=identity, alias=alias)
            if hits:
                return "\n".join(component.describe(p, docs[p]) for p in hits)
            # Nothing spells the name that way — but a name is written in more than one
            # convention, and the page's own title, aliases, slug and identity names say
            # what it can be written as. Same normaliser and same tier order the recall
            # paths use, so a compile and a question resolve a name identically.
            named, weak = (
                component.resolve_by_name(docs, alias=alias) if alias.strip() else ([], [])
            )
            if named:
                return component.render_name_matches(docs, named)
            # Nothing canonical answers — ask the projection. A term the whole library
            # concentrates on one identity resolves the lookup to the page bound to that
            # identity, and says so IN the answer: this is a derived match, not a
            # confirmation, and the page's `aliases` field is still what turns it into one.
            terms = component._mirrored_terms(draft_user or "")
            matched = component.find_by_term(docs, terms, alias=alias)
            if matched:
                lines = [
                    f"{component.describe(p, docs[p])} · ({render_term_match(row)})"
                    for p, row in matched
                ]
                lines.append(
                    "That page does not declare this name — the match is derived from turn "
                    "structure across the library. If the material confirms it, the page's "
                    "`aliases` field is where it becomes a confirmation."
                )
                return "\n".join(lines)
            # …and last, the name keys' WEAK hits — a form that only ever matched as a
            # prefix. After the projection deliberately: a term the library's turns
            # concentrate on one person is evidence, and a prefix is a resemblance.
            if weak:
                return component.render_name_matches(docs, weak)
            what = " / ".join(x for x in (identity.strip(), alias.strip()) if x) or "(empty query)"
            lines = [
                f"no person page binds {what}. An existing page records it in its structured "
                f"fields (`rewrite_overview` / `set_fields` with fields: identities, "
                f"aliases — written whole, every time); `create_document` opens a new one "
                f"under {component.family}."
            ]
            # Library first: a term that already concentrates on one identity is a far
            # stronger answer than this job's own turns, and it is the one a page may act on.
            library = reported_terms(terms)
            group = library.get(term_key(alias))
            if group:
                lines.append(
                    f"Across the library the turns address that name: "
                    f"{render_term_supports(group)} — reported because that support "
                    f"concentrates on one target, still not a binding: the term may name a "
                    f"third person."
                )
            pointed = merge_address_candidates(evidence, term=alias)
            if pointed:
                lines.append(
                    f"This compile's turns address that name: "
                    f"{render_address_candidates(pointed)} — candidates from turn structure, "
                    f"not a binding: the term may name a third person."
                )
            return "\n".join(lines)

        def decline_alias(path: str, term: str, reason: str = "") -> str:
            """THIS ROUND'S ANSWER, and nothing more. It records the decision in the job's
            own state so the gate a moment later sees the question answered; it writes
            nothing to the draft, and the commit carries no trace of it.

            That is the whole design and not a limitation of it. Canonical records what is
            KNOWN about a person; a name that is not theirs is not knowledge, and a field
            listing such names would be a column of distractions on the page. What keeps the
            question from returning is the page being WRITTEN: the library knows the day the
            term became reported and the day the page was last committed, so a page written
            since has answered.

            The page need not have been read this round — nothing is written, so there is no
            previous state a write would be replacing unobserved. A round that means the
            decline to last writes the page, and writing it requires reading it anyway.

            The `reason` is the round's own articulation and is echoed back, not stored.
            """
            docs = draft.documents()
            doc = docs.get(path)
            if doc is None or not component.is_member(path):
                return (
                    f"no person page at `{path}`. decline_alias names the page the term was "
                    f"reported against — one of {component.family}."
                )
            fm = doc.frontmatter or {}
            key = term_key(term)
            if key in {name_key(a) for a in component.aliases_of(fm)}:
                return (
                    f'`{path}` already records "{term.strip()}" in its aliases. A recorded '
                    f"alias is a confirmation and is not declined; remove it from the field "
                    f"first if this round rules that it is not this person's name."
                )
            rows = component._mirrored_terms(draft_user or "")
            bound = {normalize_identity(i) for i in component.identities_of(fm)}
            targets = [
                row
                for row in component.page_terms(rows, doc)
                if row.term == key and normalize_identity(row.target) in bound
            ]
            if not targets:
                return (
                    f'"{term.strip()}" is not a term this library reports for any identity '
                    f"`{path}` binds, so there is nothing to decline. Only a reported term "
                    f"has to be decided."
                )
            if not draft_user:
                return "decline_alias needs a source in this compile to know whose library it is."
            component._declines.setdefault(draft_user, {}).update(
                {
                    (key, normalize_identity(row.target)): Decision(
                        term=key, identity=normalize_identity(row.target), path=path
                    )
                    for row in targets
                }
            )
            where = ", ".join(row.target for row in targets)
            return (
                f'declined: "{term.strip()}" is not a name of `{path}` ({where})'
                + (f" — {reason.strip()}" if reason.strip() else "")
                + ". This round's answer, and nothing is stored: no claim, no alias, no "
                "field. A name you decline is simply not written. The term goes on being "
                "counted and goes on resolving lookups; it is no longer demanded of this "
                "round, and it will not be asked again once this page commits — so write "
                "the page in this round if there is anything to write. Recording the term "
                "in `aliases` later is how it becomes this person's name after all."
            )

        return [
            StructuredTool.from_function(
                find_person,
                name="find_person",
                description=(
                    "Look up whether a person page already exists — call it before writing a "
                    "person's name anywhere. identity: a source identity such as "
                    "mailto:name@example.com or im:u_123 (exact). alias: a name, nickname or "
                    "title as it appears in the material (exact, case-insensitive; matches "
                    "declared aliases, slug and title). Returns the page's path when one "
                    "exists, and says so when none does. A person page carries two "
                    "structured fields you write, both written whole by rewrite_overview / "
                    "set_fields: "
                    "`identities` (scheme:value, as the source boundary records them — at "
                    "most one page may bind each) and `aliases` (how this person is "
                    "addressed — never a name that is somebody else's). What the two kinds "
                    "of listed term mean: a REPORTED term has library-wide support "
                    "concentrated on that target; an EMERGING one is repeated in this source "
                    "and not yet backed by the library. Neither is a binding — both are what "
                    "the address index observed, and the contract rules on them."
                ),
            ),
            StructuredTool.from_function(
                decline_alias,
                name="decline_alias",
                description=(
                    "Record that a reported address term is NOT this person's name. This is "
                    "THIS ROUND'S ANSWER and nothing is stored — a name you decline is "
                    "simply not written, and it will not be asked again once this page "
                    "commits. A decline is a decision about a name, never knowledge: it "
                    "writes no claim, no alias and no field, and the term goes on being "
                    "counted and goes on resolving lookups. Each term this library reports "
                    "for an identity a page binds must end the round either recorded in that "
                    "page's `aliases` or declined here. path: the person page the term was "
                    "reported against. term: the term, as reported. reason: what the "
                    "material shows — an honorific several people earn (周总, 老师), a term "
                    "that names a third person, a phrase the counter liked, someone else's "
                    "name; it is echoed back to you and not stored. \"honorific\" is an "
                    "ordinary reason and an ordinary outcome. Recording the term in "
                    "`aliases` later is how it becomes this person's name after all."
                ),
            ),
        ]

    # --- face 4: deep-recall tool --------------------------------------------------------

    async def _address_terms(self, user_id: UserId) -> dict[str, list[str]]:
        """Target identity → the address terms REPORTED for it, library-wide.

        Library-wide is not an approximation of a windowed answer, it is the answer: a term
        is a nickname because of how the whole corpus uses it, so restricting the count to
        the window being enumerated would make the same term reportable in June and not in
        July. The window restricts which IDENTITIES are listed; what they are called does not
        move with it.
        """
        rows = await self.library_terms(user_id)
        out: dict[str, list[str]] = {}
        for group in reported_terms(rows).values():
            total = sum(r.support for r in group)
            for row in group:
                if is_reported(row, total):
                    out.setdefault(normalize_identity(row.target), []).append(
                        f"{row.term} ×{row.support}"
                    )
        return out

    async def enumerate(
        self,
        user_id: UserId,
        *,
        since: str = "",
        until: str = "",
        offset: int = 0,
        limit: int = ENUMERATE_MAX_LINES,
        documents=None,
    ) -> str:
        if self._content is None:
            return "enumerate_identities unavailable: no content store wired."
        sources = await self._content.list(user_id)
        summaries = summarize_identities(sources, since=since, until=until)
        terms = await self._address_terms(user_id)
        bound: dict[str, str] = {}
        for doc in (await self._documents(user_id, documents)).values():
            if not self.is_member(doc.path):
                continue
            for identity in self.identities_of(doc.frontmatter or {}):
                bound.setdefault(normalize_identity(identity), doc.path)
        pages = {bound[normalize_identity(s.identity)] for s in summaries if normalize_identity(s.identity) in bound}
        n_bound = sum(1 for s in summaries if normalize_identity(s.identity) in bound)
        window = f"{since or '…'}..{until or '…'}" if (since or until) else "all time"
        lines = [
            f"{len(summaries)} external identities in {window} · {n_bound} bound to "
            f"{len(pages)} person page(s) · {len(summaries) - n_bound} unbound"
        ]
        offset = max(int(offset), 0)
        limit = max(int(limit), 1)
        for s in summaries[offset : offset + limit]:
            page = bound.get(normalize_identity(s.identity))
            names = ", ".join(s.display_names[:3]) or "(no display name)"
            span = f"{s.first}..{s.last}" if s.first else "(no occurrence date)"
            called = terms.get(normalize_identity(s.identity)) or []
            lines.append(
                f"- {s.identity} → {page or '(unbound)'} · {len(s.source_ids)} source(s) · "
                f"{span} · {names}"
                + (f" · terms: {', '.join(called)}" if called else "")
            )
        lines.append(
            navigation_line(
                total=len(summaries),
                offset=offset,
                shown=len(summaries[offset : offset + limit]),
                unit="identities",
                more=_call_text(
                    "enumerate_identities",
                    since=since,
                    until=until,
                    offset=offset + limit,
                    limit=limit,
                ),
            )
        )
        return "\n".join(lines)

    # --- face 5: fast-recall path ---------------------------------------------------------

    async def _documents(self, user_id: UserId, documents) -> dict[str, object]:
        """The lane's pinned `documents` when given (a snapshot query stays pinned), else
        canonical HEAD from the store."""
        if documents is not None:
            return {d.path: d for d in documents}
        if self._canonical is None:
            return {}
        return {d.path: d for d in await self._canonical.list(user_id)}

    async def person_claims(
        self,
        user_id: UserId,
        *,
        alias: str = "",
        identity: str = "",
        documents=None,
    ) -> list[RetrievedClaim]:
        """The person page(s) matching the query as ordinary claims: current first (label
        `current`), superseded history after (label `superseded`).

        The WHOLE page, never a prefix of it. This lookup has no question to rank against,
        so any cap it applied would be a cap on document order — which is exactly how the
        one claim that answers the question ends up just past the edge. The framework orders
        these against the question and spends the path's cap on that order
        (core `recall/component_rank.py`).

        The lookup itself is tiered (`_resolve_pages`): a canonical alias/identity/slug/title
        first, then the contact-book name keys, then a REPORTED address term, then the name
        keys again without an honorific. Claims reached below the first tier carry an extra
        label — `via:name-match tier<n>` or `via:address-term` — so the answering lane can
        see that the page was found by how the name can be WRITTEN, or by what the library
        CALLS this person, rather than by what canonical declares.

        WHEN THE NAME KEYS TIE, EVERY CANDIDATE COMES BACK — with its definition line only.
        Two colleagues share a given name, so a question that uses it has two answers; the
        lane holding the question is the one that can choose between them. Returning up to
        `NAME_MATCH_CANDIDATES` pages, each stating who it is, hands over the ambiguity
        instead of picking one page and looking certain. A single winner comes back whole,
        exactly as before."""
        docs = await self._documents(user_id, documents)
        hits, via_term, via_name = await self._resolve_pages(
            user_id, docs, alias=alias, identity=identity
        )
        if not hits:
            return []
        ambiguous = len(hits) > 1 and bool(via_name)
        dead = superseded_index({p: d.body for p, d in docs.items()})
        current: list[RetrievedClaim] = []
        history: list[RetrievedClaim] = []
        for path in hits:
            derived: tuple[str, ...] = ()
            if path in via_term:
                derived = ("via:address-term",)
            elif path in via_name:
                derived = (via_name[path].label,)
            projected = list(project_document_claims(docs[path]))
            if ambiguous:
                projected = _definition_line(projected)
            for pc in projected:
                superseded = str(pc.anchor) in dead
                claim = RetrievedClaim(
                    anchor=pc.anchor,
                    document_path=pc.document_path,
                    section_path=pc.section_path,
                    text=pc.text,
                    citations=pc.citations,
                    paths=("people",),
                    score=1.0,
                    # `pc.labels` carries ("overview", "<slot>") for a claim in the page's
                    # overview region, so the answering lane can see that a line is the
                    # page's head rather than one of its ledger claims.
                    labels=(("superseded",) if superseded else ("current",))
                    + derived
                    + pc.labels,
                )
                (history if superseded else current).append(claim)
        return [*current, *history]

    def fast_paths(self, user_id: str):
        component = self
        uid = UserId(user_id)

        class PersonArgs(BaseModel):
            alias: str = Field(default="", description="a name, nickname or title as written in the question")
            identity: str = Field(default="", description="a source identity such as mailto:… or im:… if the question contains one")

        class PersonPath:
            name = "person"
            description = (
                "Exact lookup of ONE person the owner knows, by the name/nickname/title the "
                "question uses (or an email/account identity). Returns that person's page: "
                "the claims that hold NOW first, then earlier states marked superseded, each "
                "with its source citation. Use when the question is about a specific person "
                "(who they are, their role, what changed, how the owner works with them)."
            )
            args_schema = PersonArgs
            cap = 24

            async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):
                claims = await component.person_claims(
                    uid, alias=args.alias, identity=args.identity, documents=documents
                )
                return PathResult(claims=tuple(claims))

        return [PersonPath()]

    async def person_profile(
        self,
        user_id: UserId,
        *,
        alias: str = "",
        identity: str = "",
        section: str = "",
        offset: int = 0,
        limit: int = PROFILE_PAGE_LIMIT,
        documents=None,
    ) -> str:
        """One person's record as text: identities/aliases, the claims that hold now, then
        the superseded history — each line with its `[cite: …]` provenance. A derived render
        over canonical, never a stored summary.

        PAGINATED, never truncated. The deep lane is agentic: a cap there must not be a dead
        end, so a page that does not fit comes back with the exact call that fetches the
        rest, and the section index needed to jump straight at one part of the record."""
        docs = await self._documents(user_id, documents)
        # Read once: the same rows resolve the lookup and print the header's derived line.
        terms = await self.library_terms(user_id)
        hits, via_term, via_name = await self._resolve_pages(
            user_id, docs, alias=alias, identity=identity, rows=terms
        )
        if not hits:
            what = " / ".join(x for x in (alias.strip(), identity.strip()) if x) or "(empty query)"
            return f"no person page binds {what}."
        lines: list[str] = []
        claims = await self.person_claims(
            user_id, alias=alias, identity=identity, documents=documents
        )
        # The overview is printed whole above; its lines are out of the ledger BEFORE the
        # section index is built, or the navigation line would offer a narrow call
        # (`section="overview › definition"`) that comes back empty.
        claims = [c for c in claims if "overview" not in c.labels]
        sections = section_counts(claims)
        wanted = section.strip().casefold()
        if wanted:
            # Both spellings resolve: one heading (`位置`) and the full breadcrumb the
            # navigation line itself prints (`贾宁 › 位置`). A tool that offers a call the
            # model then copies must accept exactly that call back.
            claims = [
                c
                for c in claims
                if wanted in {p.casefold() for p in c.section_path}
                or wanted == " › ".join(c.section_path).casefold()
            ]
        # The header states BOTH vocabularies and keeps them apart: the confirmed aliases a
        # compile wrote onto the page, then — on their own line — the address terms the
        # library's turns back, each with the support behind it. Same person, two different
        # kinds of fact, and a reader who cannot tell them apart cannot judge either.
        for path in hits:
            doc = docs[path]
            lines.append(f"# {document_title(doc)} — `{path}` · {self.profile_tail(doc)}".rstrip(" ·"))
            derived = self.page_terms(terms, doc)
            if derived:
                lines.append(
                    "library address terms: "
                    + ", ".join(f"{row.term} ({row.signals()})" for row in derived)
                )
            if path in via_term:
                lines.append(f"({render_term_match(via_term[path])})")
            if path in via_name:
                lines.append(f"({via_name[path].render()})")
                if len(hits) > 1:
                    lines.append(
                        f"(one of {len(hits)} pages whose name matches that form equally "
                        f"well — each is printed with its overview so the right one can be "
                        f"told apart)"
                    )
            # The page's OVERVIEW first, whole: who this is, where they stand now, how they
            # got there, who they are connected to. It is the same order a person reads a
            # profile in, and it means the claim ledger below is read as detail rather than
            # as the only thing on offer. Its lines are then left out of the paginated ledger
            # — printing them twice would make the head look like evidence of its own.
            overview, _ = parse_overview(doc.body)
            if overview is not None and not overview.is_empty():
                lines.append("## overview")
                for slot in ("definition", "summary", "introduction"):
                    text = " ".join(str(getattr(overview, slot)).split())
                    if text:
                        lines.append(f"- {slot}: {text}")
                for connection in overview.connections:
                    lines.append(
                        f"- connection: `{connection.path}` — {connection.relation}"
                    )
        def line(c: RetrievedClaim) -> str:
            section_path = " › ".join(c.section_path)
            cites = " ".join(f"[cite: {x.source_id} ¶{x.block_start}-{x.block_end}]" for x in c.citations)
            return f"- [c:{c.anchor}{' · ' + section_path if section_path else ''}] {c.text} {cites}".rstrip()
        offset = max(int(offset), 0)
        limit = max(int(limit), 1)
        page = claims[offset : offset + limit]
        current = [c for c in page if "current" in c.labels]
        history = [c for c in page if "superseded" in c.labels]
        lines.append(f"## current ({len(current)})")
        lines.extend(line(c) for c in current)
        if history:
            lines.append(f"## superseded history ({len(history)})")
            lines.extend(line(c) for c in history)
        lines.append(
            navigation_line(
                total=len(claims),
                offset=offset,
                shown=len(page),
                unit="claims",
                sections=sections if not wanted else (),
                more=_call_text(
                    "person_profile",
                    alias=alias,
                    identity=identity,
                    section=section,
                    offset=offset + limit,
                    limit=limit,
                ),
                narrow=(
                    _call_text(
                        "person_profile",
                        alias=alias,
                        identity=identity,
                        section=sections[0][0],
                    )
                    if sections and not wanted
                    else ""
                ),
            )
        )
        return "\n".join(lines)

    def source_preamble(self, source) -> str | None:
        """What the source boundary knows and the transcript cannot show: WHO is present,
        and — from the turn structure across the WHOLE library — HOW the turns call them.

        Two separate statements, because they carry different weight. The reported terms have
        library-wide support behind them and are the ones a page may act on; the emerging ones
        are this source's own repetitions and are shown so the model can see a nickname
        forming, explicitly labelled as not yet evidenced. Neither is a binding: `@X 阿宝怎么样`
        names a third person, so every term keeps its full distribution over targets.

        The library view comes from the mirrored projection, which the framework fills by
        awaiting `prepare` at the head of the job (index and compile are separate jobs in
        separate processes, so it starts cold every time). Should that not have happened, the
        reported line is simply absent — this seam never states a count it cannot back.

        Fail-soft, unlike the write-time faces: this states evidence, and stating less of it
        costs a weaker prompt, never a wrong write. What it will NOT do is state another
        user's evidence — a source belonging to somebody other than the prepared job is a
        cross-user read, and it is refused (I1).
        """
        if self._job_user and str(source.raw.user_id) != self._job_user:
            raise RuntimeError(
                f"people: source_preamble was called for user {source.raw.user_id} while "
                f"the job prepared in this process is {self._job_user}. One compile per "
                f"process at a time (core components/__init__.py:component_job)."
            )
        lines: list[str] = []
        mentions = identity_mentions(source.raw)
        present = {normalize_identity(m.identity) for m in mentions}
        if mentions:
            seen: dict[str, str] = {}
            for m in mentions:
                seen.setdefault(m.identity, m.display_name)
            listed = "; ".join(f"{i} — {n}" if n else i for i, n in seen.items())
            lines.append(
                f"Identities present in this source (from the source boundary; a person "
                f"page records the ones that are its subject's in its `identities` field, "
                f"and no two pages may hold the same one): {listed}"
            )

        library = reported_terms(self._mirrored_terms(source.raw.user_id))
        stated: set[str] = set()
        # Only the terms that point at someone in THIS source: the compile task is about this
        # material, and the library's other nicknames are noise inside it. Nothing is
        # subtracted for an earlier round's decline — nothing was stored, and a page written
        # since is excused by the gate rather than by this line.
        pointed = [
            group
            for group in library.values()
            if any(normalize_identity(r.target) in present for r in group)
        ]
        if pointed:
            shown = pointed[:PREAMBLE_REPORTED_MAX]
            tail = len(pointed) - len(shown)
            rendered = [r for group in shown for r in group]
            stated.update(r.term for r in rendered)
            text = render_term_supports(rendered)
            lines.append(
                f"How the library's turns call these people (address terms with library-wide "
                f"support, best-supported target first — a distribution over identities, not "
                f"a binding: a term may name a third person; a term reported for someone "
                f"here must end this round recorded in that page's `aliases` or declined "
                f"with decline_alias — asked once, and closed by writing the page): {text}"
                + (f"; …and {tail} more" if tail else "")
            )

        here = [
            c
            for c in address_evidence(source, min_support=ADDRESS_MIN_SUPPORT)
            if term_key(c.term) not in library
        ]
        if here:
            by_term: dict[str, list[AddressCandidate]] = {}
            for candidate in here:
                by_term.setdefault(term_key(candidate.term), []).append(candidate)
            terms = list(by_term)[:PREAMBLE_EMERGING_MAX]
            tail = len(by_term) - len(terms)
            known = {
                (row.term, row.target): row.sources
                for row in self._mirrored_terms(source.raw.user_id)
            }
            text = "; ".join(
                f'"{term}" → '
                + " · ".join(
                    f"{c.target} ({', '.join(f'{n} {v}' for n, v in (('answered', c.answered), ('co_mention', c.co_mention)) if v)}"
                    f" here; {_sources_phrase(known.get((term, c.target), 1))} so far)"
                    for c in by_term[term]
                )
                for term in terms
            )
            stated.update(terms)
            lines.append(
                f"emerging (repeated in this source, not yet enough support across the "
                f"library to be reported): {text}"
                + (f"; …and {tail} more" if tail else "")
            )

        # Last, and weakest by construction: repeated name-shaped tokens the source boundary
        # cannot account for. No target, no support, no claim that any of them is a person —
        # the two lines above carry evidence, this one carries only the observation that the
        # material keeps saying a word that looks like a name and matches nobody it knows.
        known = set(self.known_names(source.raw.user_id))
        known.update(self._page_names.get(str(source.raw.user_id), set()))
        known.update(name_key(m.display_name) for m in mentions if m.display_name.strip())
        unresolved = unresolved_names(source, known=known, stated=stated)
        if unresolved:
            shown_names = unresolved[:UNRESOLVED_MAX]
            tail = len(unresolved) - len(shown_names)
            lines.append(
                "Names in this source matching no present identity (repeated name-shaped "
                "tokens the source boundary does not account for; no target is implied — a "
                "third-person mention carries no structure to read one from. If the material "
                "shows one of these is how a person here is addressed, that person's page is "
                "where it becomes an alias): "
                + ", ".join(f"{token} ×{count}" for token, count in shown_names)
                + (f"; …and {tail} more" if tail else "")
            )
        return "\n".join(lines) or None

    def recall_tools(self, user_id: str, *, documents=None) -> list[StructuredTool]:
        component = self
        uid = UserId(user_id)

        async def enumerate_identities(
            since: str = "", until: str = "", offset: int = 0, limit: int = ENUMERATE_MAX_LINES
        ) -> str:
            return await component.enumerate(
                uid, since=since, until=until, offset=offset, limit=limit, documents=documents
            )

        async def person_profile(
            alias: str = "",
            identity: str = "",
            section: str = "",
            offset: int = 0,
            limit: int = PROFILE_PAGE_LIMIT,
        ) -> str:
            return await component.person_profile(
                uid,
                alias=alias,
                identity=identity,
                section=section,
                offset=offset,
                limit=limit,
                documents=documents,
            )

        return [
            StructuredTool.from_function(
                coroutine=person_profile,
                name="person_profile",
                description=(
                    "One person's full record from the knowledge base: identities and aliases, "
                    "the claims that hold NOW, then earlier states marked superseded — every "
                    "line with its source citation. alias: a name/nickname/title as written; "
                    "identity: mailto:… / im:… if known. Exact match only. section: one "
                    "section of the record (the response lists them with their counts), to "
                    "read just that part. " + PAGINATED_NOTE
                ),
            ),
            StructuredTool.from_function(
                coroutine=enumerate_identities,
                name="enumerate_identities",
                description=(
                    "The CLOSED set of external people/identities the owner's sources record "
                    "in a date range (ISO days; empty = open). Returns every identity with its "
                    "source count, first..last occurrence, display names, and the person page "
                    "bound to it or `(unbound)`. The set comes from the source boundaries "
                    "(participant lists, addresses, user lists), not from search: within the "
                    "range it is complete, and the unbound residue is part of the answer. "
                    + PAGINATED_NOTE
                ),
            )
        ]


__all__ = [
    "ADDRESS_KINDS",
    "ALIAS_UNDECIDED_MAX",
    "ADDRESS_LIBRARY_MIN_SUPPORT",
    "ADDRESS_MIN_SUPPORT",
    "ALIASES_KEY",
    "IDENTITIES_KEY",
    "PREAMBLE_EMERGING_MAX",
    "PREAMBLE_REPORTED_MAX",
    "REPORT_MIN_CONCENTRATION",
    "REPORT_MIN_SOURCES",
    "REPORT_MIN_SUPPORT",
    "UNRESOLVED_MAX",
    "UNRESOLVED_MIN_COUNT",
    "COMPOUND_SURNAMES",
    "HONORIFIC_PREFIXES",
    "HONORIFIC_SUFFIXES",
    "NAME_MATCH_CANDIDATES",
    "PREFIX_MIN_CHARS",
    "AddressCandidate",
    "AddressTarget",
    "Decision",
    "NameMatch",
    "IdentityMention",
    "IdentitySummary",
    "PeopleComponent",
    "TermSupport",
    "accumulate_term_rows",
    "CoSpeaking",
    "address_evidence",
    "address_terms_by_target",
    "identity_mentions",
    "source_speakers",
    "is_reported",
    "merge_address_candidates",
    "identity_display_name",
    "match_tier",
    "name_keys",
    "name_parts",
    "name_shaped_tokens",
    "name_tokens",
    "split_cjk_name",
    "strip_honorific",
    "normalize_identity",
    "rejects_address_term",
    "render_address_candidates",
    "render_term_supports",
    "reported_terms",
    "split_csv",
    "summarize_identities",
    "term_key",
    "term_rows",
    "term_support_from_row",
    "unresolved_names",
]

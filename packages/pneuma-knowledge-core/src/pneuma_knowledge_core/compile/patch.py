"""PatchDraft: in-memory compile staging area.

A base snapshot file table + accumulated edit ops → a produced files dict, committed
atomically by the runner. Every edit op is claim-level (architecture.md §8): there is
NO whole-file rewrite operation — the model cannot replace a document body wholesale,
so it cannot drop a claim anchor by transcription. Anchors and document ids are all
system-assigned (discipline 1: mechanism over persuasion).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..domain.canonical import CanonicalDocument
from ..domain.ids import DocumentId, extract_anchors
from ..prompts import prompt
from .anchor_ops import (
    AnchorToolError,
    append_block_text,
    assign_document_anchors,
    edit_claim_text,
    insert_block_verbatim,
    refuse_text_machinery,
    remove_claim_block,
    supersede_claim_text,
)
from .supersession import superseded_index
from .documents import (
    DOC_ID_KEY,
    TITLE_KEY,
    Connection,
    Overview,
    normalize_frontmatter,
    render_document,
    render_overview,
    remove_overview_region,
    set_overview_region,
    with_derived_title,
)
from .overview import (
    OVERVIEW_BUDGET_CHARS,
    ledger_anchors,
    normalize_grounding_references,
    overview_anchors,
    overview_write_problems,
)
from ..components import registered_components

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"

#: Frontmatter the SYSTEM owns. `set_fields` refuses all four: a document's identity is not
#: content the model may overwrite (discipline 1 — mechanism, not persuasion). Three of them
#: are ASSIGNED at creation; `title` is DERIVED, re-read from the document's `# ` heading on
#: every write, so the name in the frontmatter is the name on the page by construction.
RESERVED_FRONTMATTER = (DOC_ID_KEY, "type", "slug", TITLE_KEY)


def _template_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{slug\})", template)
    body = "".join(_SLUG if p == "{slug}" else re.escape(p) for p in parts)
    return re.compile(f"^{body}$")


def path_allowed(path: str, path_templates: list[str]) -> bool:
    """True iff `path` matches one of the skill's path templates (path ownership).

    This is the WRITE ownership predicate: what `create_document` will accept. It deliberately
    does NOT recognize a document's history directory (see `history_volume_owner`) — a rollover
    volume must be unreachable from the compile tool face.
    """
    return any(_template_regex(t).match(path) for t in path_templates)


def _bare_grounding(overview: Overview) -> Overview:
    """Every slot's dressed-up ledger reference reduced to the bare `c:xxxx` the gate reads.

    Applied at the single write path rather than asked for in the tool description: the
    overview's grounding grammar is one bare anchor, and `[cite: c:1a2b3c4d]` is the same
    reference wearing the source-locator's brackets. Connection relations go through it too —
    a relation line is ordinary overview prose and grounds the same way.
    """
    return Overview(
        definition=normalize_grounding_references(overview.definition),
        summary=normalize_grounding_references(overview.summary),
        introduction=normalize_grounding_references(overview.introduction),
        connections=tuple(
            Connection(
                path=connection.path,
                relation=normalize_grounding_references(connection.relation),
            )
            for connection in overview.connections
        ),
    )


#: A rollover volume's filename inside a document's history directory: `a01.md`, `a02.md`, …
#: The naming itself belongs to `compile.rollover`; the GRAMMAR lives here because path
#: ownership is one concern and must be stated in one place.
_VOLUME_FILE_RE = re.compile(r"^a(\d{2,})\.md$")


def history_dir(document_path: str) -> str:
    """A document's history directory: its own path with `.md` dropped.

    `work/products/aurora-planner.md` → `work/products/aurora-planner/`. Rollover volumes live
    there, so the archive travels with the document it belongs to and needs no slug of its own.
    """
    return document_path.removesuffix(".md")


def history_volume_owner(path: str, path_templates: list[str]) -> str | None:
    """The document that owns `path` as one of its rollover volumes, or None.

    A mechanical derivation, not a second ownership table: `<owned document>/aNN.md` belongs to
    `<owned document>.md`. It exists because a volume is a real canonical document — it is read
    off git, projected into L3, and therefore present in every later compile's draft — while
    being deliberately OUTSIDE the write templates so that no compile tool can create one.
    Only the groom channel writes here.
    """
    directory, _, filename = path.rpartition("/")
    if not directory or _VOLUME_FILE_RE.match(filename) is None:
        return None
    owner = f"{directory}.md"
    return owner if path_allowed(owner, path_templates) else None


def assign_document_id(path: str) -> DocumentId:
    """Content-addressed document id: derived from the path, never model-supplied.

    Public because the rollover channel mints one for an archive volume through the same
    function the compile channel uses — two derivations of a document's identity would be
    two ids for one path.
    """
    return DocumentId(hashlib.sha256(f"doc:{path}".encode("utf-8")).hexdigest()[:12])


#: Historical private spelling, kept so existing call sites read unchanged.
_assign_document_id = assign_document_id


@dataclass
class DraftDoc:
    path: str
    doc_id: DocumentId
    frontmatter: dict
    body: str


def raw_file(doc: "DraftDoc") -> str:
    """One draft document serialized exactly as it stands — no derivation applied."""
    return render_document(doc.frontmatter, doc.body)


def touched_this_round(doc: "DraftDoc", base: "DraftDoc | None") -> bool:
    """Did this round WRITE this document? The one predicate every "the round touched it"
    rule is judged by — `PatchDraft._changed_this_round` below, and every component gate
    check (`components/__init__.py`).

    A page is touched when its body OR its frontmatter differs from what it held at the head
    of the round, and a page that has no base at all (created this round) is touched by
    definition. Comparing only one half is how a rule meant to apply to every write comes to
    apply to half of them: a claim appended to a page whose frontmatter nobody edited is a
    write like any other, and the page answers for what it declares the moment it is written.

    Judged over the UNDERIVED serialization on both sides, so the answer is about what the
    round did and never about what the derivation would do to a page nobody touched.
    """
    if base is None:
        return True
    return raw_file(doc) != raw_file(base)


@dataclass
class PatchDraft:
    """Working copy of the canonical file table plus claim-level mutations."""

    path_templates: list[str]
    _base: dict[str, DraftDoc] = field(default_factory=dict)
    _working: dict[str, DraftDoc] = field(default_factory=dict)
    #: The paths this round has actually LOOKED AT (`read_document`, and the document a
    #: `create_document` just wrote). The two whole-region writes — the overview and the
    #: structured fields — refuse a path that is not in here: both replace what stands
    #: rather than adding to it, so "keep, merge, rewrite or drop" is only a judgement if
    #: the previous state was observed. A mechanism, not a reminder in the prompt.
    _read: set[str] = field(default_factory=set)
    #: The overview's character ceiling, carried so the TOOL FACE refuses by the same number
    #: the gate would use. Two ceilings for one region would mean a deployment that raised
    #: the knob still got refused at the write, or one that lowered it still reached the gate.
    overview_budget_chars: int = OVERVIEW_BUDGET_CHARS

    @classmethod
    def from_canonical(
        cls,
        docs: list[CanonicalDocument],
        path_templates: list[str],
        *,
        overview_budget_chars: int = OVERVIEW_BUDGET_CHARS,
    ) -> "PatchDraft":
        base = {
            d.path: DraftDoc(
                path=d.path,
                doc_id=d.doc_id,
                frontmatter=dict(d.frontmatter),
                body=d.body,
            )
            for d in docs
        }
        working = {
            p: DraftDoc(d.path, d.doc_id, dict(d.frontmatter), d.body)
            for p, d in base.items()
        }
        return cls(
            path_templates=list(path_templates),
            _base=base,
            _working=working,
            overview_budget_chars=overview_budget_chars,
        )

    # --- read -----------------------------------------------------------------

    def list_paths(self) -> list[str]:
        return sorted(self._working)

    def read(self, path: str) -> DraftDoc:
        doc = self._working.get(path)
        if doc is None:
            raise AnchorToolError(prompt("compile.patch.read_missing", path=path))
        return doc

    def mark_read(self, path: str) -> None:
        """Record that this round has seen `path` as it stands.

        Called by the READ tool face (and by `create_document`, whose author has the new
        document in hand by definition) — never by `read()`, which every mutator calls
        internally and which would therefore let a write vouch for itself.
        """
        self._read.add(path)

    def _refuse_unread(self, path: str, op: str) -> None:
        if path in self._read:
            return
        raise AnchorToolError(prompt("compile.overview.refuse_unread", op=op, path=path))

    # --- claim-level mutations ------------------------------------------------

    def _refuse_frozen_volume(self, path: str, op: str) -> None:
        """Refuse, EARLY and teachably, any mutation aimed at a rollover volume.

        A volume sits in the working set like any other document (it must: the gate and the
        projection read it), so before this guard the first thing telling a model "frozen"
        was gate 5b — after the whole round was spent. The refusal happens here, at the one
        place every claim mutation passes through, using the same ownership derivation as
        the gate (`history_volume_owner`), and it names the corrective action: the active
        page the volume was cut out of. The gate's 5b check stays as the final arbiter for
        anything that reaches a draft without going through these tools.
        """
        owner = history_volume_owner(path, self.path_templates)
        if owner is not None:
            raise AnchorToolError(
                prompt("compile.patch.volume_frozen", op=op, path=path, owner=owner)
            )

    def create_document(self, path: str, frontmatter: dict, body: str) -> DraftDoc:
        if not path_allowed(path, self.path_templates):
            raise AnchorToolError(
                prompt(
                    "compile.patch.create_path_not_allowed",
                    path=path,
                    templates=", ".join(self.path_templates),
                )
            )
        if path in self._working:
            raise AnchorToolError(
                prompt("compile.patch.create_exists", path=path)
            )
        refuse_text_machinery("create_document", body)
        doc_id = _assign_document_id(path)
        anchored = assign_document_anchors(body, path)
        # Normalize first so a legacy id key handed in by a caller is folded away rather
        # than persisted next to the system-assigned one; the id itself is never caller-set.
        fm = normalize_frontmatter(frontmatter)
        fm[DOC_ID_KEY] = str(doc_id)
        # A model-supplied `title` is REPLACED here rather than refused, exactly as a
        # model-supplied doc_id is: the contract has asked for one for months, and refusing
        # a whole create over a field the system was always going to derive would spend a
        # round teaching nothing. `set_fields` refuses it, because there the field IS the
        # call.
        fm = with_derived_title(fm, anchored)
        doc = DraftDoc(path=path, doc_id=doc_id, frontmatter=fm, body=anchored)
        self._working[path] = doc
        # Whoever just wrote a document has, by definition, seen everything in it.
        self.mark_read(path)
        return doc

    def _refuse_superseded(self, anchor_id: str, op: str) -> None:
        """Refuse, at the tool face, any rewrite of a claim that has a successor.

        A superseded claim is frozen history — the same status a rollover volume has, for
        the same reason: it is the record of what held before, and the current state lives
        in its successor. The refusal names that successor so the corrective action is one
        step away. The gate's supersession check stays behind this as the final arbiter.
        """
        anchor_id = anchor_id.removeprefix("c-").removeprefix("c:")
        hit = superseded_index(self.new_bodies()).get(anchor_id)
        if hit is not None:
            successor_path, successor = hit
            raise AnchorToolError(
                prompt(
                    "compile.patch.claim_superseded",
                    op=op,
                    anchor_id=anchor_id,
                    successor=successor,
                    path=successor_path,
                )
            )

    def edit_claim(self, path: str, anchor_id: str, new_text: str) -> DraftDoc:
        self._refuse_frozen_volume(path, "edit_claim")
        self._refuse_superseded(anchor_id, "edit_claim")
        refuse_text_machinery("edit_claim", new_text)
        doc = self.read(path)
        doc.body = edit_claim_text(doc.body, anchor_id, new_text)
        return doc

    def supersede_claim(self, path: str, anchor_id: str, new_text: str) -> tuple[DraftDoc, str]:
        """Record that `new_text` is the current state of the fact `anchor_id` stated.

        The old claim stays byte-for-byte and becomes frozen; the new claim is inserted
        right after it with a system anchor and a `supersedes` marker. Returns the document
        and the new anchor. See compile/supersession.py for what is derived from this.
        """
        self._refuse_frozen_volume(path, "supersede_claim")
        self._refuse_superseded(anchor_id, "supersede_claim")
        refuse_text_machinery("supersede_claim", new_text)
        doc = self.read(path)
        doc.body, new_anchor = supersede_claim_text(
            doc.body, anchor_id, new_text, document_path=path
        )
        return doc, new_anchor

    # --- the overview: the one region written whole -----------------------------

    def rewrite_overview(
        self, path: str, overview: Overview, fields: dict | None = None
    ) -> DraftDoc:
        """Replace `path`'s whole overview — the four prose slots and the structured
        `fields` beside them — with the model's judgement over what stood there.

        This is the ONLY whole-region write in the compile tool face, and it is safe for the
        one reason the claim-level rule exists to protect: the region holds no permanent
        identity. Its blocks get fresh system anchors on every call, its old anchors are
        allowed to vanish (the gate exempts exactly this set from anchor continuity), and the
        LEDGER below is not touched — the splice runs between the system's own markers, so
        not one claim byte can move.

        The overview is a SNAPSHOT, not a changelog: nothing in it only grows. The structured
        fields ride the same call for exactly that reason — `identities` and `aliases` are
        the machine-readable half of the same picture, and a picture written whole is a
        picture whose wrong entry is gone after the next rewrite instead of forever. They go
        through the same door `set_fields` uses (system-reserved names refused, every enabled
        component given its say), so one call has one authority, not two.

        Four outcomes, and the call shape says which: leave it alone (do not call), merge or
        rewrite (call with the whole new region), drop it (call with every slot empty and no
        fields — the region is removed and the document goes back to being its claims).
        Slots-empty WITH fields is a fields-only write and leaves the region standing.
        """
        self._refuse_frozen_volume(path, "rewrite_overview")
        self._refuse_unread(path, "rewrite_overview")
        doc = self.read(path)
        incoming = self._checked_fields(path, "rewrite_overview", fields)
        if overview.is_empty():
            if not incoming:
                doc.body = remove_overview_region(doc.body)
                return doc
            doc.frontmatter.update(incoming)
            return doc
        overview = _bare_grounding(overview)
        region = render_overview(overview, document_path=path)
        # Anchor uniqueness is repository-wide, so the collision seed is every anchor in the
        # working set — minus this document's outgoing region, whose ids are being retired.
        taken = {
            anchor
            for other in self._working.values()
            for anchor in extract_anchors(other.body)
        } - overview_anchors(doc.body)
        # Compute the whole candidate first, judge THAT, and only then assign: the region the
        # checks measure is byte-for-byte the region the gate would measure, and a refusal
        # leaves the document exactly as it stood.
        candidate = set_overview_region(
            doc.body, assign_document_anchors(region, path, existing=taken)
        )
        self._refuse_unwritable_overview(path, candidate)
        doc.body = candidate
        doc.frontmatter.update(incoming)
        return doc

    def _refuse_unwritable_overview(self, path: str, candidate: str) -> None:
        """Refuse, EARLY and teachably, an overview that the gate would reject anyway.

        The overview's rules used to be heard for the first time at the gate — after the
        round was spent — so every miss cost a repair round and often the compile. They are
        the same rules, judged here on the candidate region with the same helpers the gate
        uses (`compile.overview.overview_write_problems`), and the refusal names EVERY
        failing block at once: a model that fixes one rule per round is a model that learns
        the region three calls at a time.

        The whole call is refused and nothing is written — a partly-written head would be a
        head that says something the ledger does not carry, which is the one thing the
        region may never do. The gate's `check_overviews` stays as the final arbiter for
        anything that reaches a draft without passing through this tool.
        """
        ledger = {
            anchor
            for other_path, other in self._working.items()
            for anchor in ledger_anchors(
                candidate if other_path == path else other.body
            )
        }
        problems = overview_write_problems(
            path,
            candidate,
            ledger=ledger,
            documents=set(self._working),
            budget=self.overview_budget_chars,
        )
        if problems:
            raise AnchorToolError(
                prompt(
                    "compile.overview.refuse_header",
                    path=path,
                    problems="\n".join(f"- {problem}" for problem in problems),
                )
            )

    def set_fields(self, path: str, fields: dict) -> DraftDoc:
        """Set or overwrite frontmatter fields on an existing document — written WHOLE.

        A structured field is a snapshot of what is true now, exactly like the prose slots
        beside it: a value that disappears from the call disappears from the document. That
        is what makes a wrong one repairable at all.

        The SYSTEM's own three (`doc_id`, `type`, `slug`) are refused: they are assigned at
        creation and are identity, not content. Everything else is offered to the enabled
        index components first (`validate_fields`), which is where a value that is a FACT
        about the library — an identity another page already binds, a name that is somebody
        else's — is refused before the round is spent. Nothing is written when any of them
        objects: a half-written frontmatter is a document saying something no one decided.
        """
        doc = self.read(path)
        self._refuse_frozen_volume(path, "set_fields")
        self._refuse_unread(path, "set_fields")
        doc.frontmatter.update(self._checked_fields(path, "set_fields", fields))
        return doc

    def _checked_fields(self, path: str, op: str, fields: dict | None) -> dict:
        """Normalize the incoming frontmatter and judge it — the one door every write face
        uses, so a rule can never hold at one of them and not the other."""
        incoming = normalize_frontmatter(dict(fields or {}))
        if not incoming:
            return {}
        for key in incoming:
            if key in RESERVED_FRONTMATTER:
                raise AnchorToolError(
                    prompt(
                        "compile.patch.set_fields_reserved",
                        field=key,
                        reserved=", ".join(RESERVED_FRONTMATTER),
                    )
                )
        problems: list[str] = []
        for component in registered_components():
            check = getattr(component, "validate_fields", None)
            if check is None:
                continue
            problems.extend(
                str(problem)
                for problem in (check(path, dict(incoming), self._working) or [])
            )
        if problems:
            raise AnchorToolError(
                prompt(
                    "compile.patch.fields_refused",
                    op=op,
                    path=path,
                    problems="\n".join(f"- {problem}" for problem in problems),
                )
            )
        return incoming

    def append_block(self, path: str, heading: str, text: str) -> DraftDoc:
        self._refuse_frozen_volume(path, "append_block")
        refuse_text_machinery("append_block", text)
        doc = self.read(path)
        doc.body = append_block_text(doc.body, heading, text, document_path=path)
        return doc

    # --- evolve-only merge channel (move / delete) ----------------------------
    # Only the evolve tool face registers these; the daily compile `_build_tools` never
    # exposes them, so compile keeps its zero-deletion discipline byte-for-byte.

    def move_claim(
        self, from_path: str, anchor_id: str, to_path: str, heading: str
    ) -> DraftDoc:
        """Move a whole anchored claim block from `from_path` to the end of `to_path`'s
        `heading` section — VERBATIM, anchor unchanged. The block is removed from the source
        (a re-section within the same document is allowed). The target must already exist;
        the model must `create_document` it first."""
        self._refuse_frozen_volume(from_path, "move_claim")
        self._refuse_frozen_volume(to_path, "move_claim")
        src = self.read(from_path)  # refuses if source missing / anchor missing
        if to_path not in self._working:
            raise AnchorToolError(
                prompt("compile.patch.move_target_missing", to_path=to_path)
            )
        block, remaining = remove_claim_block(src.body, anchor_id)
        if from_path == to_path:
            # Same-document re-section: remove then re-insert on the one working body.
            src.body = insert_block_verbatim(remaining, heading, block)
            return src
        src.body = remaining
        dst = self._working[to_path]
        dst.body = insert_block_verbatim(dst.body, heading, block)
        return dst

    def delete_claim(self, path: str, anchor_id: str) -> DraftDoc:
        """Remove a whole anchored claim block (the evolve-only merge outcome). The anchor
        disappears — `run_evolve_gate` surfaces it in the dropped-anchors list rather than
        rejecting it (a redundant claim merged away)."""
        self._refuse_frozen_volume(path, "delete_claim")
        # A predecessor named by a supersedes marker may not be merged away: the successor
        # would dangle, every later compile's gate would reject the repository, and no daily
        # tool can repair a system-kept marker — a deadlock. Refuse here, at the one channel
        # that can delete; the evolve gate holds the same line as final arbiter.
        anchor_key = anchor_id.removeprefix("c-").removeprefix("c:")
        hit = superseded_index(self.new_bodies()).get(anchor_key)
        if hit is not None:
            successor_path, successor = hit
            raise AnchorToolError(
                prompt(
                    "compile.patch.delete_supersession_target",
                    anchor_id=anchor_key,
                    successor=successor,
                    path=successor_path,
                )
            )
        doc = self.read(path)
        _, doc.body = remove_claim_block(doc.body, anchor_id)
        return doc

    # --- outputs --------------------------------------------------------------

    def base_bodies(self) -> dict[str, str]:
        return {p: d.body for p, d in self._base.items()}

    def base_documents(self) -> dict[str, DraftDoc]:
        """The base file table, frontmatter included (component gate checks compare a
        document's declared fields against what it declared before this round)."""
        return dict(self._base)

    def new_bodies(self) -> dict[str, str]:
        return {p: d.body for p, d in self._working.items()}

    def documents(self) -> dict[str, DraftDoc]:
        return dict(self._working)

    def _raw_file(self, doc: DraftDoc) -> str:
        """A document serialized exactly as it stands — no derivation applied."""
        return raw_file(doc)

    def _changed_this_round(self, path: str) -> bool:
        """Did this round write `path` at all? (A new document counts as written.)

        The shared predicate, so the file table's notion of "changed" and a component gate
        check's notion of "touched" can never drift apart.
        """
        return touched_this_round(self._working[path], self._base.get(path))

    def to_files(self) -> dict[str, str]:
        """path → serialized markdown file (frontmatter fence + body).

        The derived frontmatter — `title`, read off the document's `# ` heading — is applied
        to the documents this round CHANGED and to nothing else. A commit carries the whole
        file table, so deriving over all of it would mean one dirty page dragging every stale
        title in the library into that commit: a knowledge edit and a mass rewrite in one
        indistinguishable diff. Deriving over the changed set makes a title correction ride
        the next ordinary write of the page it corrects, and leaves every untouched file
        byte-identical.
        """
        out: dict[str, str] = {}
        for path, doc in self._working.items():
            if self._changed_this_round(path):
                out[path] = render_document(
                    with_derived_title(doc.frontmatter, doc.body), doc.body
                )
            else:
                out[path] = self._raw_file(doc)
        return out

    def is_dirty(self) -> bool:
        """Did this round change anything a commit would carry?

        The comparison is over the SERIALIZED files — frontmatter fence included, rendered
        by the same function on both sides — because that is exactly what `to_files` hands
        the commit. A body-only comparison called a round whose ONLY write was `set_fields`
        a no-op and threw the write away: an identity corrected or an alias recorded changes
        no prose at all, and the structured fields are as canonical as the claims beside
        them. Writing the same values back is still a no-op, because the same values render
        the same bytes.

        The derived `title` cannot make a clean library dirty either: `to_files` derives only
        over what this round changed, so a document nobody wrote renders on both sides from
        the same frontmatter and the same body.
        """
        base = {p: self._raw_file(d) for p, d in self._base.items()}
        return self.to_files() != base

"""Fold budget and state contract (pinned upstream implementation)."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone

BUDGET = 64
WEIGHT_ORDER = ("critical", "high", "normal", "low", "trace")
KINDS = ("needs-you", "in-progress", "done", "fyi")
ID_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")
BUSINESS_FIELDS = (
    "title", "summary", "weight", "share_override", "share", "kind", "due_at",
    "stale_after", "sources", "parent_id", "status", "merged_into", "children",
)
PATCH_FIELDS = ("title", "summary", "weight", "kind", "reason", "due_at", "stale_after")


class FoldError(Exception):
    """Fold budget and state contract (pinned upstream implementation)."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.details}


def fail(code: str, message: str, **details):
    raise FoldError(code, message, **details)


def derive_share(weight: str, budget: int = BUDGET) -> int:
    """Fold budget and state contract (pinned upstream implementation)."""
    table = {
        "critical": 3 * budget // 8,
        "high": 3 * budget // 16,
        "normal": 3 * budget // 32,
        "low": 3 * budget // 64,
        "trace": 1,
    }
    if weight not in table:
        fail("invalid_field", f"unknown weight {weight!r}", field="weight", value=weight)
    return max(1, table[weight])


def parse_time(value, field: str = "now") -> datetime:
    if not isinstance(value, str):
        fail("invalid_time", f"{field} must be an explicit ISO timestamp", field=field, value=value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("invalid_time", f"{field} must be an explicit ISO timestamp", field=field, value=value)
    if parsed.tzinfo is None:
        fail("invalid_time", f"{field} must carry a timezone offset", field=field, value=value)
    return parsed


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def equal(a, b) -> bool:
    return canonical(a) == canonical(b)


def require_text(value, field: str, max_len: int | None = None, **details):
    if not isinstance(value, str) or not value.strip() or (max_len is not None and len(value) > max_len):
        limit = f" and at most {max_len} characters" if max_len else ""
        fail("invalid_field", f"{field} must be nonempty{limit}", field=field, value=value, **details)


def initial_snapshot(budget: int = BUDGET) -> dict:
    return {
        "budget": budget, "revision": "r0", "event_seq": 0,
        "items": {}, "annotations": {}, "annotation_counter": 0,
        "last_checked_at": None, "last_checked_by": {},
        "events": [], "receipts": {},
    }


def next_revision(revision: str) -> str:
    return f"r{int(revision[1:]) + 1}"


def children_of(snapshot: dict, parent, active_only: bool = True) -> list[dict]:
    return [
        item for item in snapshot["items"].values()
        if item["parent_id"] == parent and (not active_only or item["status"] == "active")
    ]


def descendants(snapshot: dict, item_id: str, active_only: bool = False) -> list[str]:
    result: list[str] = []

    def visit(parent: str):
        for child in children_of(snapshot, parent, False):
            if not active_only or child["status"] == "active":
                result.append(child["id"])
            visit(child["id"])

    visit(item_id)
    return result


def business_view(snapshot: dict, item: dict) -> dict:
    view = {}
    for field in BUSINESS_FIELDS:
        if field == "children":
            view[field] = sorted(child["id"] for child in children_of(snapshot, item["id"]))
        else:
            view[field] = item.get(field)
    return view


def parse_relation(declaration: dict) -> dict:
    relation = declaration.get("relation", "new")
    if relation is None:
        fail("unsupported_relation", "relation cannot be null", item=declaration.get("id"))
    if relation in ("new", "withdraw"):
        return {"type": relation}
    if not isinstance(relation, str):
        fail("unsupported_relation", "relation must be a supported string", item=declaration.get("id"))
    if relation.startswith("supersedes:"):
        return {"type": "supersedes", "target": relation[len("supersedes:"):].strip()}
    match = re.match(r"^merges:\s*\[(.*)\]$", relation)
    if match:
        ids = [part.strip().strip("\"'") for part in match.group(1).split(",")]
        ids = [part for part in ids if part]
        if len(ids) < 2 or len(set(ids)) != len(ids):
            fail("invalid_merge", "merge needs at least two distinct source IDs", ids=ids)
        return {"type": "merges", "ids": ids}
    fail("unsupported_relation", f"unsupported relation {relation!r}", relation=relation,
         item=declaration.get("id"))


def known_item(snapshot: dict, item_id: str) -> dict:
    item = snapshot["items"].get(item_id)
    if item is None:
        fail("item_not_found", f"unknown item {item_id}", item=item_id)
    return item


def writable_item(snapshot: dict, item_id: str) -> dict:
    item = known_item(snapshot, item_id)
    if item["status"] == "merged":
        fail("item_merged", f"{item_id} has a successor", item=item_id, merged_into=item["merged_into"])
    return item


def normalize_sources(sources, item_id: str) -> list[dict]:
    if sources is None:
        return []
    if not isinstance(sources, list):
        fail("invalid_field", "sources must be an array or null", field="sources", item=item_id)
    result = []
    for source in sources:
        if not isinstance(source, dict):
            fail("invalid_field", "each source must be an object", field="sources", item=item_id)
        require_text(source.get("channel"), "sources.channel", item=item_id)
        require_text(source.get("ref"), "sources.ref", item=item_id)
        if source.get("observed_at") is not None:
            parse_time(source["observed_at"], "observed_at")
        result.append(copy.deepcopy(source))
    return result


def dedupe(values: list) -> list:
    seen: set[str] = set()
    result = []
    for value in values:
        key = canonical(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def apply_fields(item: dict, declaration: dict, budget: int):
    for field in PATCH_FIELDS:
        if field in declaration:
            item[field] = copy.deepcopy(declaration[field])
    if "sources" in declaration:
        item["sources"] = normalize_sources(declaration["sources"], item["id"])
    if "share" in declaration:
        share = declaration["share"]
        if share is not None and (not isinstance(share, int) or isinstance(share, bool) or share < 1):
            fail("invalid_field", "share must be a positive integer or null", field="share", item=item["id"])
        item["share_override"] = share
    if item["weight"] not in WEIGHT_ORDER:
        fail("invalid_field", f"{item['id']} has an unknown weight", field="weight", item=item["id"],
             value=item["weight"])
    if item["kind"] not in KINDS:
        fail("invalid_field", f"{item['id']} has an unknown kind", field="kind", item=item["id"],
             value=item["kind"])
    item["share"] = item["share_override"] if item["share_override"] is not None else derive_share(item["weight"], budget)
    item["status"] = "active"
    item["merged_into"] = None


def validate_state(snapshot: dict):
    budget = snapshot["budget"]
    for item in snapshot["items"].values():
        require_text(item.get("title"), "title", 24, item=item["id"])
        summary = item.get("summary")
        if summary is not None and (not isinstance(summary, str) or len(summary) > 60):
            fail("invalid_field", f"summary on {item['id']} must be a string of at most 60 characters",
                 field="summary", item=item["id"])
        for field in ("due_at", "stale_after"):
            if item.get(field) is not None:
                parse_time(item[field], field)
        seen = {item["id"]}
        parent = item["parent_id"]
        while parent is not None:
            if parent in seen:
                fail("cyclic_parent", f"cycle involving {item['id']}", item=item["id"])
            seen.add(parent)
            ancestor = known_item(snapshot, parent)
            if item["status"] == "active" and ancestor["status"] != "active":
                fail("inactive_parent", f"parent {parent} of {item['id']} is not active",
                     item=item["id"], parent=parent)
            parent = ancestor["parent_id"]
        if item["status"] == "active" and children_of(snapshot, item["id"]) and not (summary or "").strip():
            fail("invalid_field", f"parent {item['id']} needs a summary", field="summary", item=item["id"])
    layers = [None] + list(snapshot["items"].keys())
    for parent in layers:
        items = children_of(snapshot, parent)
        used = sum(item["share"] for item in items)
        if used > budget:
            layer = parent if parent is not None else "root"
            fail("budget_exceeded", f"layer {layer} declares {used} / {budget}",
                 constraint="layer_budget", layer=layer, budget=budget, declared=used,
                 over=used - budget, shares={item["id"]: item["share"] for item in items})


def canonical_request(command: str, actor: str, **payload) -> dict:
    return {"command": command, "actor": actor, **payload}


def check_duplicate(snapshot: dict, batch_id: str, request: dict):
    previous = snapshot["receipts"].get(batch_id)
    if previous is None:
        return None
    differing = [field for field in request if not equal(request[field], previous["request"].get(field))]
    if differing:
        fail("batch_id_conflict", f"batch {batch_id} was already committed with different content",
             batch_id=batch_id, differing_fields=differing,
             original_receipt=copy.deepcopy(previous["receipt"]))
    receipt = copy.deepcopy(previous["receipt"])
    receipt["batch_status"] = "already_committed"
    receipt["events_appended"] = 0
    return receipt


def commit(snapshot: dict, batch: dict, actor: str, now: str) -> tuple[dict, dict]:
    """Fold budget and state contract (pinned upstream implementation)."""
    parse_time(now)
    if not isinstance(batch, dict):
        fail("invalid_batch", "commit accepts a JSON object with batch_id")
    batch_id = batch.get("batch_id")
    require_text(batch_id, "batch_id", 128)
    require_text(actor, "actor")
    declarations = batch.get("declarations", [])
    acknowledges = batch.get("acknowledges", [])
    if declarations is None:
        declarations = []
    if acknowledges is None:
        acknowledges = []
    if not isinstance(declarations, list) or not isinstance(acknowledges, list):
        fail("invalid_batch", "declarations and acknowledges must be arrays")
    request = canonical_request("commit", actor, declarations=copy.deepcopy(declarations),
                                acknowledges=copy.deepcopy(acknowledges))
    previous = check_duplicate(snapshot, batch_id, request)
    if previous is not None:
        return snapshot, previous

    budget = snapshot["budget"]
    candidate = copy.deepcopy(snapshot)
    entries: list[dict] = []
    declared: set[str] = set()

    def collect(items, parent, nested):
        for declaration in items:
            if not isinstance(declaration, dict):
                fail("invalid_field", "each declaration must be an object", field="declarations")
            item_id = declaration.get("id")
            if not isinstance(item_id, str) or not ID_PATTERN.match(item_id):
                fail("invalid_field", f"invalid declaration id {item_id!r}", field="id", id=item_id)
            if item_id in declared:
                fail("duplicate_declaration", f"multiple declarations for {item_id}", item=item_id)
            declared.add(item_id)
            relation = parse_relation(declaration)
            if relation["type"] != "withdraw":
                if declaration.get("weight") not in WEIGHT_ORDER:
                    fail("invalid_field", f"{item_id} requires a valid weight", field="weight", item=item_id,
                         value=declaration.get("weight"))
                if declaration.get("kind") not in KINDS:
                    fail("invalid_field", f"{item_id} requires a valid kind", field="kind", item=item_id,
                         value=declaration.get("kind"))
            entries.append({"declaration": declaration, "relation": relation, "parent": parent, "nested": nested})
            if "children" in declaration:
                children = declaration["children"]
                if children is not None and not isinstance(children, list):
                    fail("invalid_field", "children must be an array or null", field="children", item=item_id)
                collect(children or [], item_id, True)

    collect(declarations, None, False)

    withdrawals = {entry["declaration"]["id"] for entry in entries if entry["relation"]["type"] == "withdraw"}
    merged_sources: set[str] = set()
    ops: list[dict] = []
    restored: set[str] = set()
    placed: set[str] = set()

    for entry in entries:
        declaration, relation, parent, nested = (entry["declaration"], entry["relation"], entry["parent"], entry["nested"])
        item_id = declaration["id"]
        if relation["type"] == "withdraw":
            writable_item(snapshot, item_id)
            require_text(declaration.get("reason"), "reason", item=item_id)
            continue
        if relation["type"] == "supersedes":
            if relation["target"] != item_id:
                fail("identity_mismatch", "supersedes must keep the same ID", item=item_id, target=relation["target"])
            original = writable_item(snapshot, item_id)
            if nested and original["parent_id"] != parent:
                fail("unsupported_move", "children cannot move an existing item to another layer",
                     item=item_id, parent=original["parent_id"], requested_parent=parent)
            item = candidate["items"][item_id]
            downgrade = WEIGHT_ORDER.index(declaration["weight"]) > WEIGHT_ORDER.index(original["weight"])
            share_changed = "share" in declaration and not equal(declaration["share"], original["share_override"])
            if downgrade or share_changed:
                require_text(declaration.get("reason"), "reason", item=item_id)
            if original["status"] == "withdrawn":
                restored.add(item_id)
        else:
            if item_id in candidate["items"]:
                fail("item_exists", f"ID {item_id} already exists", item=item_id)
            item = {
                "id": item_id, "title": None, "summary": None, "weight": declaration["weight"],
                "kind": declaration["kind"], "share_override": None, "share": None, "status": "active",
                "parent_id": parent, "reason": None, "due_at": None, "stale_after": None,
                "sources": [], "annotations": [], "created_at": now, "updated_at": now,
                "merged_into": None, "withdrawn_at": None,
            }
            candidate["items"][item_id] = item
            placed.add(item_id)
        if declaration.get("share") is not None:
            require_text(declaration.get("reason"), "reason", item=item_id)
        apply_fields(item, declaration, budget)
        item["withdrawn_at"] = None
        if relation["type"] == "merges":
            sources = [writable_item(snapshot, source_id) for source_id in relation["ids"]]
            if any(source["status"] != "active" for source in sources):
                fail("inactive_merge_source", "merge sources must be active", ids=relation["ids"])
            if any(source["parent_id"] != sources[0]["parent_id"] for source in sources):
                fail("merge_layer_mismatch", "merge sources must be in the same layer", ids=relation["ids"])
            if nested and parent != sources[0]["parent_id"]:
                fail("unsupported_move", "merge cannot move between layers", ids=relation["ids"])
            if any(children_of(snapshot, source["id"], False) for source in sources) or declaration.get("children"):
                fail("unsupported_merge_structure",
                     "merge sources and result must be leaves without current or historical subtrees",
                     ids=relation["ids"])
            for source in sources:
                if source["id"] in declared or source["id"] in merged_sources:
                    fail("duplicate_declaration", f"merge source {source['id']} is modified more than once",
                         item=source["id"])
                merged_sources.add(source["id"])
                candidate["items"][source["id"]]["status"] = "merged"
                candidate["items"][source["id"]]["merged_into"] = item_id
            item["parent_id"] = sources[0]["parent_id"]
            item["sources"] = dedupe([src for source in sources for src in source["sources"]] + item["sources"])
            inherited = []
            for source in sources:
                for annotation_id in source["annotations"]:
                    if annotation_id not in inherited:
                        inherited.append(annotation_id)
            item["annotations"] = inherited
            for annotation_id in inherited:
                candidate["annotations"][annotation_id]["item"] = item_id

    for item_id in withdrawals:
        reason = next(e["declaration"]["reason"] for e in entries if e["declaration"]["id"] == item_id)
        affected = []
        for affected_id in [item_id] + descendants(candidate, item_id):
            item = candidate["items"][affected_id]
            if item["status"] == "active":
                item["status"] = "withdrawn"
                item["withdrawn_at"] = now
                affected.append(affected_id)
        candidate["items"][item_id]["reason"] = reason

    for entry in entries:
        declaration, relation = entry["declaration"], entry["relation"]
        if "children" not in declaration or relation["type"] == "withdraw":
            continue
        item_id = declaration["id"]
        target = sorted(
            child["id"] for child in (declaration["children"] or [])
            if parse_relation(child)["type"] != "withdraw"
        )
        omitted = [
            child for child in children_of(snapshot, item_id)
            if child["id"] not in target and child["id"] not in withdrawals
        ]
        if omitted:
            fail("explicit_withdraw_required",
                 f"these children of {item_id} would leave the layer; add withdraw for each or keep them",
                 parent=item_id, omitted_children=[child["id"] for child in omitted],
                 affected_ids=[cid for child in omitted for cid in [child["id"]] + descendants(snapshot, child["id"], True)])
        actual = sorted(child["id"] for child in children_of(candidate, item_id))
        if target != actual:
            fail("invalid_children_target", f"final children differ from the target list for {item_id}",
                 parent=item_id, target=target, actual=actual)

    validate_state(candidate)

    new_acknowledges = []
    for annotation_id in dict.fromkeys(acknowledges):
        annotation = candidate["annotations"].get(annotation_id)
        if annotation is None:
            fail("annotation_not_found", f"unknown annotation {annotation_id}", annotation=annotation_id)
        if annotation["status"] == "saved":
            new_acknowledges.append(annotation_id)

    changed_ids = []
    for item in candidate["items"].values():
        old = snapshot["items"].get(item["id"])
        if old is None or not equal(business_view(snapshot, old), business_view(candidate, item)):
            changed_ids.append(item["id"])
            item["updated_at"] = now
        else:
            item["updated_at"] = old["updated_at"]
            item["reason"] = old["reason"]
            item["withdrawn_at"] = old.get("withdrawn_at")

    record_type = "commit" if changed_ids else "acknowledge" if new_acknowledges else "checked"
    if record_type != "checked":
        candidate["revision"] = next_revision(snapshot["revision"])
    for annotation_id in new_acknowledges:
        candidate["annotations"][annotation_id]["status"] = "acknowledged"
        candidate["annotations"][annotation_id]["acknowledged_revision"] = candidate["revision"]
    if record_type == "checked":
        candidate["last_checked_at"] = now
        candidate["last_checked_by"][actor] = now

    changed = set(changed_ids)
    for entry in entries:
        declaration, relation = entry["declaration"], entry["relation"]
        item_id = declaration["id"]
        if item_id not in changed:
            continue
        item = candidate["items"][item_id]
        old = snapshot["items"].get(item_id)
        if relation["type"] == "withdraw":
            ops.append({"op": "withdraw", "item": item_id, "parent": item["parent_id"], "reason": item["reason"],
                        "affected": [i for i in [item_id] + descendants(candidate, item_id)
                                     if candidate["items"][i]["withdrawn_at"] == now]})
        elif relation["type"] == "merges":
            ops.append({"op": "merge", "item": item_id, "parent": item["parent_id"], "merged": relation["ids"],
                        "share": item["share"], "weight": item["weight"], "kind": item["kind"]})
        elif item_id in placed:
            ops.append({"op": "place", "item": item_id, "parent": item["parent_id"], "share": item["share"],
                        "weight": item["weight"], "kind": item["kind"]})
        elif item_id in restored:
            ops.append({"op": "restore", "item": item_id, "parent": item["parent_id"], "share": item["share"],
                        "weight": item["weight"], "kind": item["kind"], "reason": item["reason"]})
        else:
            before = business_view(snapshot, old)
            after = business_view(candidate, item)
            fields = [field for field in BUSINESS_FIELDS if not equal(before[field], after[field])]
            ops.append({"op": "supersede", "item": item_id, "from": old["share"], "to": item["share"],
                        "fields": fields, "reason": item["reason"]})
    structural = sorted(changed - {op["item"] for op in ops})
    for item_id in structural:
        item = candidate["items"][item_id]
        old = snapshot["items"].get(item_id)
        if item["status"] == "withdrawn" and old and old["status"] == "active":
            continue
        if item["status"] == "merged":
            continue
        before = business_view(snapshot, old) if old else {}
        after = business_view(candidate, item)
        fields = [field for field in BUSINESS_FIELDS if not equal(before.get(field), after[field])]
        ops.append({"op": "structure", "item": item_id, "fields": fields})

    candidate["event_seq"] += 1
    receipt = {
        "accepted": True, "batch_status": "committed", "batch_id": batch_id, "actor": actor, "now": now,
        "event_seq": candidate["event_seq"], "revision": candidate["revision"], "type": record_type,
        "events_appended": 1, "changes": copy.deepcopy(ops), "changed_ids": changed_ids,
        "acknowledges": new_acknowledges,
    }
    candidate["events"].append({
        "event_seq": candidate["event_seq"], "batch_id": batch_id, "type": record_type, "actor": actor,
        "now": now, "revision": candidate["revision"], "changes": copy.deepcopy(ops),
        "acknowledges": new_acknowledges,
        "request": request,
    })
    candidate["receipts"][batch_id] = {"request": request, "receipt": copy.deepcopy(receipt)}
    return candidate, receipt


def annotate(snapshot: dict, batch_id: str, item_id: str, text: str, actor: str = "user",
             now: str | None = None) -> tuple[dict, dict]:
    """Fold budget and state contract (pinned upstream implementation)."""
    parse_time(now)
    require_text(batch_id, "batch_id", 128)
    require_text(actor, "actor")
    require_text(text, "text")
    request = canonical_request("annotate", actor, item=item_id, text=text)
    previous = check_duplicate(snapshot, batch_id, request)
    if previous is not None:
        return snapshot, previous
    writable_item(snapshot, item_id)
    candidate = copy.deepcopy(snapshot)
    candidate["annotation_counter"] += 1
    annotation_id = f"ann-{candidate['annotation_counter']}"
    stored = {"id": annotation_id, "item": item_id, "author": actor, "text": text, "created_at": now,
              "status": "saved", "acknowledged_revision": None}
    candidate["annotations"][annotation_id] = stored
    candidate["items"][item_id]["annotations"].append(annotation_id)
    candidate["event_seq"] += 1
    change = {"op": "annotation", "item": item_id, "annotation": copy.deepcopy(stored)}
    receipt = {
        "accepted": True, "batch_status": "committed", "batch_id": batch_id, "actor": actor, "now": now,
        "event_seq": candidate["event_seq"], "revision": candidate["revision"], "type": "annotation",
        "events_appended": 1, "annotation_id": annotation_id, "annotation_status": "saved",
    }
    candidate["events"].append({
        "event_seq": candidate["event_seq"], "batch_id": batch_id, "type": "annotation", "actor": actor,
        "now": now, "revision": candidate["revision"], "changes": [change], "acknowledges": [],
        "request": request,
    })
    candidate["receipts"][batch_id] = {"request": request, "receipt": copy.deepcopy(receipt)}
    return candidate, receipt


def humanize(seconds: float | None) -> str | None:
    """Fold budget and state contract (pinned upstream implementation)."""
    if seconds is None:
        return None
    past = seconds < 0
    total = int(abs(seconds) // 60)
    days, rem = divmod(total, 24 * 60)
    hours, minutes = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes and not days:
        parts.append(f"{minutes} 分钟")
    if not parts:
        parts.append("0 分钟")
    text = " ".join(parts[:2])
    return f"已过 {text}" if past else text


def rank_items(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: (
        -item["share"], 0 if item["kind"] == "needs-you" else 1,
        -parse_time(item["updated_at"], "updated_at").timestamp(), item["id"],
    ))


def project_state(snapshot: dict, now: str) -> dict:
    """Fold budget and state contract (pinned upstream implementation)."""
    moment = parse_time(now)

    def since(value):
        if value is None:
            return None
        return (moment - parse_time(value)).total_seconds()

    def item_view(item: dict, rank):
        layer_view = layer(item["id"])
        view = {key: copy.deepcopy(value) for key, value in item.items()}
        view["rank"] = rank
        view["children"] = layer_view if layer_view["items"] else None
        view["last_seen_at"] = None
        view["since_seen"] = None
        age = since(item["created_at"])
        update = since(item["updated_at"])
        due = -since(item["due_at"]) if item["due_at"] else None
        stale = -since(item["stale_after"]) if item["stale_after"] else None
        view["age"] = humanize(age)
        view["since_update"] = humanize(update)
        view["until_due"] = humanize(due)
        view["until_stale"] = humanize(stale)
        view["age_seconds"] = age
        view["since_update_seconds"] = update
        view["until_due_seconds"] = due
        view["until_stale_seconds"] = stale
        return view

    def layer(parent):
        items = rank_items(children_of(snapshot, parent))
        return {
            "budget": snapshot["budget"], "used": sum(item["share"] for item in items),
            "items": [item_view(item, index + 1) for index, item in enumerate(items)],
        }

    annotations = [copy.deepcopy(annotation) for annotation in snapshot["annotations"].values()]
    withdrawn = [
        {"id": item["id"], "title": item["title"], "parent_id": item["parent_id"], "status": item["status"],
         "merged_into": item.get("merged_into"), "reason": item["reason"], "withdrawn_at": item.get("withdrawn_at"),
         "summary": item["summary"]}
        for item in snapshot["items"].values() if item["status"] != "active"
    ]
    return {
        "revision": snapshot["revision"], "last_event_seq": snapshot["event_seq"], "now": now,
        "budget": snapshot["budget"], "root": layer(None),
        "last_checked_at": snapshot["last_checked_at"], "last_seen_at": None, "since_seen": None,
        "pending_annotations": [annotation for annotation in annotations if annotation["status"] == "saved"],
        "annotation_status": {annotation["id"]: annotation["status"] for annotation in annotations},
        "annotation_bound_to": {
            annotation["id"]: annotation["acknowledged_revision"]
            for annotation in annotations if annotation["acknowledged_revision"]
        },
        "annotations": annotations,
        "not_active": withdrawn,
    }


def history(snapshot: dict, item: str | None = None, batch: str | None = None) -> dict:
    """Fold budget and state contract (pinned upstream implementation)."""
    if batch is not None:
        events = [copy.deepcopy(event) for event in snapshot["events"] if event["batch_id"] == batch]
        receipt = snapshot["receipts"].get(batch, {}).get("receipt")
        return {"batch": batch, "events": events, "receipt": copy.deepcopy(receipt),
                "snapshot_revision": snapshot["revision"]}
    if item is None:
        return {"events": copy.deepcopy(snapshot["events"]), "snapshot_revision": snapshot["revision"]}
    record = snapshot["items"].get(item)
    if record is None:
        fail("item_not_found", f"unknown item {item}", item=item)

    def touches(event: dict) -> bool:
        for change in event["changes"]:
            if change.get("item") == item or item in change.get("affected", []) or item in change.get("merged", []):
                return True
        return False

    events = [copy.deepcopy(event) for event in snapshot["events"] if touches(event)]
    annotations = {aid: copy.deepcopy(snapshot["annotations"][aid]) for aid in record["annotations"]}
    result = {
        "item": item, "events": events, "snapshot_revision": snapshot["revision"],
        "record": copy.deepcopy(record),
        "annotations": list(record["annotations"]),
        "annotation_status": {aid: annotation["status"] for aid, annotation in annotations.items()},
        "annotation_texts": annotations,
    }
    if record["status"] != "active":
        result["parent_at_withdraw"] = record["parent_id"]
        result["summary_at_withdraw"] = record["summary"]
        result["sources_at_withdraw"] = copy.deepcopy(record["sources"])
        result["merged_into"] = record.get("merged_into")
    return result

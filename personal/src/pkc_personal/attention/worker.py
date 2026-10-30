"""Independent poller: committed knowledge -> debounce -> Fold -> attention records."""

from __future__ import annotations
import argparse
import asyncio
import fcntl
import hashlib
import logging
import os
import signal
import time
import uuid
from pathlib import Path
from time import monotonic

from . import kernel
from .evidence import collect, observe, prompt_documents, validate_sources
from .runner import OutputValidationError, judge
from .retrospective import read_landscape
from .store import Preferences, Store, stamp

log = logging.getLogger(__name__)
SYSTEM = (
    Path(__file__).with_name("fold-v2.txt").read_text()
    + "\n\n# Personal edition retrospective purpose and evidence transport\n"
    + Path(__file__).with_name("judgment.md").read_text()
)
SKILL_HASH = hashlib.sha256(SYSTEM.encode()).hexdigest()


def validate_reflection(value, before, documents, previous=None):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("reflection must be an object")
    allowed = {d["ref"] for d in documents}
    for item in before["items"].values():
        allowed.update(s["ref"] for s in item.get("sources", []))
    for block in (previous or {}).values():
        allowed.update(block.get("refs", []))
    result = {}
    for key in ("summary", "direction", "tensions", "next_focus"):
        block = value.get(key)
        if block is None:
            continue
        if (
            not isinstance(block, dict)
            or not isinstance(block.get("text"), str)
            or not block["text"].strip()
            or len(block["text"]) > 1200
        ):
            raise ValueError("reflection blocks require text up to 1200 characters")
        refs = block.get("refs")
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or ref not in allowed for ref in refs)
        ):
            raise ValueError("reflection blocks must cite supplied evidence")
        result[key] = {"text": block["text"], "refs": list(dict.fromkeys(refs))}
    return result


def due(state: dict, preferences: Preferences, now: float) -> str | None:
    requested = state["request_seq"] > state["completed_request_seq"]
    if (
        (not preferences.enabled and not requested)
        or state["running"]
        or now < state["retry_at"]
    ):
        return None
    last = state["last_attempt"]
    if last is not None and now - last < preferences.min_interval_seconds:
        return None
    if requested:
        return "requested"
    if state["pending"]:
        if state["pending_count"] >= preferences.threshold:
            return "threshold"
        if now - state["pending_since"] >= preferences.window_seconds:
            return "window"
    if (
        not state["pending"]
        and state["last_run"] is not None
        and now - state["last_run"] >= preferences.idle_seconds
    ):
        return "review"
    return None


class Worker:
    def __init__(self, library, settings, store: Store, executor=judge):
        self.library, self.settings, self.store, self.executor = (
            library,
            settings,
            store,
            executor,
        )

    async def tick(self, now: float | None = None):
        started = monotonic()
        now = time.time() if now is None else now
        before = self.store.read()
        head, paths, count = await asyncio.to_thread(
            observe, self.library.canonical_dir, before["observed_head"]
        )
        with self.store.transaction() as (_, state):
            state["heartbeat"] = now
            if head != state["observed_head"]:
                for path in state["pending"]:
                    state["pending"][path] = head
                for path in paths:
                    state["pending"][path] = head
                if paths:
                    state["pending_count"] += count
                    if state["pending_since"] is None:
                        state["pending_since"] = now
                state["observed_head"] = head
            reason = due(state, self.store.preferences(), now)
            if not reason:
                return
            state.update(running=True, last_attempt=now)
            before = dict(state)
        try:
            documents = await asyncio.to_thread(
                collect, self.library.canonical_dir, before["pending"]
            )
            new_documents = len(documents)
            landscape = None
            if self.settings is not None:
                try:
                    landscape = await asyncio.wait_for(
                        read_landscape(
                            self.library,
                            self.settings,
                            now,
                            self.store.preferences().horizon_days,
                        ),
                        25,
                    )
                except Exception:
                    # Missing coverage stays unknown; it never becomes a fabricated flat river.
                    landscape = {
                        "days": [],
                        "projects": [],
                        "samples": [],
                        "coverage": {"unavailable": True},
                    }
            documents.extend((landscape or {}).get("samples", []))
            signal = {
                "type": "review" if reason == "review" else "update",
                "reason": reason,
                "received": new_documents,
                "window": {"from": stamp(before["last_run"] or now), "to": stamp(now)},
                "coverage": {
                    "canonical": "committed changes only",
                    "external_channels": "unknown",
                    "remaining_documents": max(
                        0, len(before["pending"]) - new_documents
                    ),
                },
            }
            packet = {
                "now": stamp(now),
                "signal": signal,
                "state": kernel.project_state(before["snapshot"], stamp(now)),
                "previous_reflection": before.get("reflection"),
                "documents": prompt_documents(documents),
                "landscape": {
                    k: v for k, v in (landscape or {}).items() if k != "samples"
                },
                "purpose": "Long-horizon knowledge retrospective and preparation for future focus; not a live notification feed.",
            }
            batch_id = "fold-" + uuid.uuid4().hex
            for attempt in range(3):
                batch = None
                output_error = None
                try:
                    batch = await self.executor(self.library, self.settings, SYSTEM, packet)
                except OutputValidationError as error:
                    output_error = error
                try:
                    if output_error is not None:
                        raise output_error
                    batch["batch_id"] = batch_id
                    snapshot, receipt = kernel.commit(
                        before["snapshot"], batch, "fold", stamp(now)
                    )
                    validate_sources(snapshot, before["snapshot"], documents)
                    reflection = validate_reflection(
                        batch.get("reflection"),
                        before["snapshot"],
                        documents,
                        before.get("reflection"),
                    )
                    break
                except (kernel.FoldError, ValueError) as error:
                    if attempt == 2:
                        raise
                    packet = dict(
                        packet,
                        rejected_batch=batch,
                        validation_error=error.to_dict()
                        if isinstance(error, kernel.FoldError)
                        else str(error),
                    )
            self.store.accept(
                before,
                snapshot,
                receipt,
                signal,
                documents,
                now,
                SKILL_HASH,
                reflection=reflection,
                landscape={
                    k: v for k, v in (landscape or {}).items() if k != "samples"
                },
            )
        except asyncio.CancelledError:
            with self.store.transaction() as (_, state):
                state["running"] = False
            raise
        except Exception as error:
            with self.store.transaction() as (_, state):
                state["failures"] += 1
                state.update(
                    running=False,
                    retry_at=now
                    + (monotonic() - started)
                    + min(21600, 300 * 2 ** min(state["failures"] - 1, 7)),
                    error=f"Attention review failed ({type(error).__name__}); retained previous board, retry scheduled.",
                )
            log.warning("Attention review failed: %s", type(error).__name__)

    async def run(self):
        with self.store.transaction() as (_, state):
            state["running"] = False
        while True:
            try:
                await self.tick()
            except Exception as error:
                log.warning(
                    "Attention observation unavailable: %s", type(error).__name__
                )
                with self.store.transaction() as (_, state):
                    state["error"] = (
                        "Knowledge observation unavailable; previous board retained."
                    )
            await asyncio.sleep(15)


def main():
    from pkc_personal.home import Home
    from pkc_personal.library import Library
    from pneuma_knowledge_service.settings import get_settings

    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True)
    parser.add_argument("--parent", type=int)
    args = parser.parse_args()
    library = Library.load(Home(), args.library)
    store = Store(library.path / "attention")
    with (store.directory / "worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return

        async def serve():
            task = asyncio.create_task(Worker(library, get_settings(), store).run())
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, task.cancel)

            async def parent_watch():
                while True:
                    if args.parent and os.getppid() != args.parent:
                        task.cancel()
                        return
                    await asyncio.sleep(5)

            monitor = asyncio.create_task(parent_watch())
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)

        asyncio.run(serve())


if __name__ == "__main__":
    main()

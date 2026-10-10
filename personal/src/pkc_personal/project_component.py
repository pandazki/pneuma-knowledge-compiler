"""Project identity faces over the edition's kept collection observations.

The source contract stays immutable. This application component supplies the compiler
with the stable repository grouping through the framework's existing source-preamble seam.
"""

from __future__ import annotations

import asyncio
import json

from pneuma_knowledge_core.components import BaseComponent

from pkc_personal import collection
from pkc_personal.library import Library


class ProjectComponent(BaseComponent):
    name = "collection-projects"

    def __init__(self, library: Library):
        self.library = library
        self._prepared: str | None = None
        self._bindings: dict = {}

    def _tenant(self, user_id: str) -> None:
        if str(user_id) != self.library.state.tenant:
            raise ValueError("collection project tenant mismatch")

    async def prepare(self, user_id: str) -> None:
        self._prepared = None
        self._bindings = {}
        self._tenant(user_id)
        # A same-tenant storage failure is fail-soft at the framework seam. Clear the old
        # mirror first, so losing this optional attribution can never expose another job.
        self._prepared = str(user_id)
        self._bindings = await asyncio.to_thread(collection.project_bindings, self.library)

    def source_preamble(self, source) -> str | None:
        self._tenant(source.raw.user_id)
        if self._prepared != str(source.raw.user_id):
            raise ValueError("collection project component was not prepared for this tenant")
        if source.raw.kind != "agent_session":
            return None
        meta = source.raw.meta
        project = meta.get("project") or {}
        key = (meta.get("provider"), meta.get("session_id"), project.get("path"))
        bound = self._bindings.get(key)
        if not bound:
            return None
        # The compiler may alias source IDs per job. Native session identity is preserved
        # in its metadata and avoids caching a job-local s01 handle across jobs.
        facts = {"project_id": bound["project_id"], "name": bound["name"],
                 "repositories": bound["remotes"][:4], "source_project_path": project.get("path"),
                 "observed_devices": list(dict.fromkeys(p["device_id"] for p in bound["locations"]))[:8]}
        return "Collection project identity: " + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))

    async def rebuild(self, user_id: str) -> None:
        self._tenant(user_id)
        await asyncio.to_thread(collection.rebuild_projects, self.library)
        await self.prepare(user_id)

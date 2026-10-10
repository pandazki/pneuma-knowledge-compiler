"""The local console's collection configuration, bound to the engine's own library."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from pkc_personal import collection
from pkc_personal.home import Home, Model
from pkc_personal.library import Library


class CloudRequest(Model):
    url: str
    host_token: str = Field(min_length=1, max_length=4096)


class InviteRequest(Model):
    label: str = Field(min_length=1, max_length=100)
    scope: collection.Scope = Field(default_factory=collection.Scope)
    processor_id: str = collection.PROCESSOR_ID


class DeviceRequest(Model):
    status: str


class LocalRequest(Model):
    enabled: bool
    scope: collection.Scope | None = None


class ProcessorRequest(Model):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    min_owner_turns: int = Field(ge=3)
    min_owner_chars: int = Field(ge=0)
    ack_max_words: int = Field(ge=1)
    max_part_chars: int = Field(ge=1000)


def local_request(request: Request) -> None:
    """Refuse cross-origin browser writes to the loopback credential/configuration face."""
    if request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise HTTPException(403, "collection configuration requires a loopback host")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "collection configuration requires the local console origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "cross-site collection requests are refused")


async def call(function, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


def build_router(home: Home, library: Library) -> APIRouter:
    router = APIRouter(prefix="/home/collection", tags=["collection"], dependencies=[Depends(local_request)])

    @router.get("")
    async def get_collection():
        return await call(collection.document, home, library)

    @router.get("/sources/{source_id}")
    async def source_observations(source_id: str, user_id: str):
        if user_id != library.state.tenant:
            raise HTTPException(404, "collection source not found")
        return await call(collection.source_observations, library, source_id)

    @router.put("/cloud")
    async def set_cloud(request: CloudRequest):
        return await call(collection.set_cloud, library, request.url, request.host_token)

    @router.post("/invitations")
    async def invite(request: InviteRequest):
        return await call(collection.invite, library, **request.model_dump(exclude={"scope"}), scope=request.scope)

    @router.delete("/invitations/{invitation_id}")
    async def revoke(invitation_id: str):
        return await call(collection.revoke_invite, library, invitation_id)

    @router.patch("/devices/{device_id}")
    async def device(device_id: str, request: DeviceRequest):
        return await call(collection.change_device, library, device_id, request.status)

    @router.put("/processors/{processor_id}")
    async def processor(processor_id: str, request: ProcessorRequest):
        if processor_id != collection.PROCESSOR_ID:
            raise HTTPException(404, "unknown processor")
        return await call(collection.set_processor, home, library, request.model_dump(exclude_none=True))

    @router.put("/local")
    async def local(request: LocalRequest):
        return await call(collection.set_local, library, request.enabled, request.scope)

    return router

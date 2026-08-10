"""Materialize image declarations into immutable L0 media objects."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import BlockImage, DerivedMediaText
from pneuma_knowledge_core.ingest.source_contracts import (
    Base64ImageSource,
    ImSource,
    SourceContract,
    UrlImageSource,
)
from pneuma_knowledge_core.ports.media_store import MediaStore


_MAX_REDIRECTS = 3


def matches_declared_image_type(data: bytes, mime_type: str) -> bool:
    """Recognize the supported raster formats without trusting filename or headers."""

    if mime_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


async def _assert_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("remote image URLs must use https")
    port = parsed.port or 443
    infos = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, port, 0, socket.SOCK_STREAM
    )
    if not infos:
        raise ValueError("remote image host did not resolve")
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    if any(not address.is_global for address in addresses):
        raise ValueError("remote image host resolves to a non-public address")


async def _download_image(
    source: UrlImageSource, *, mime_type: str, max_bytes: int
) -> bytes:
    url = str(source.url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        for redirect_count in range(_MAX_REDIRECTS + 1):
            await _assert_public_https(url)
            async with client.stream("GET", url, headers={"Accept": mime_type}) as response:
                if response.is_redirect:
                    if redirect_count == _MAX_REDIRECTS:
                        raise ValueError("remote image exceeded redirect limit")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("remote image redirect has no location")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                declared_length = response.headers.get("content-length")
                if declared_length is not None and int(declared_length) > max_bytes:
                    raise ValueError("remote image exceeds the configured size limit")
                response_type = response.headers.get("content-type", "").split(";", 1)[0]
                if response_type and response_type != mime_type:
                    raise ValueError(
                        f"remote image content type {response_type!r} does not match {mime_type!r}"
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("remote image exceeds the configured size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise RuntimeError("unreachable remote image download state")


async def materialize_contract_images(
    store: MediaStore,
    user_id: UserId,
    contract: SourceContract,
    *,
    max_bytes: int,
) -> dict[str, BlockImage]:
    """Verify and store every native image while preserving supplied derived text."""

    if not isinstance(contract, ImSource):
        return {}
    result: dict[str, BlockImage] = {}
    for conversation in contract.conversations:
        for message in conversation.messages:
            for image in message.images:
                source = image.source
                if isinstance(source, Base64ImageSource):
                    data = base64.b64decode(source.data, validate=True)
                elif isinstance(source, UrlImageSource):
                    data = await _download_image(
                        source, mime_type=image.mime_type, max_bytes=max_bytes
                    )
                else:  # pragma: no cover - discriminated union is closed
                    raise TypeError(f"unsupported image source: {type(source)!r}")
                if len(data) > max_bytes:
                    raise ValueError("image exceeds the configured size limit")
                if not matches_declared_image_type(data, image.mime_type):
                    raise ValueError(
                        f"image {image.image_id!r} does not match declared MIME type "
                        f"{image.mime_type!r}"
                    )
                digest = hashlib.sha256(data).hexdigest()
                if digest != source.sha256:
                    raise ValueError(
                        f"image {image.image_id!r} sha256 does not match fetched bytes"
                    )
                storage_key = await store.put(
                    user_id,
                    data,
                    sha256=digest,
                    mime_type=image.mime_type,
                )
                result[image.image_id] = BlockImage(
                    image_id=image.image_id,
                    mime_type=image.mime_type,
                    sha256=digest,
                    size_bytes=len(data),
                    storage_key=storage_key,
                    derived=[
                        DerivedMediaText.model_validate(item.model_dump())
                        for item in image.derived
                    ],
                    metadata=dict(image.metadata),
                )
    return result

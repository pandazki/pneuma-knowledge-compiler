"""Private S3-compatible MediaStore adapter (RustFS in the local stack)."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId


class S3MediaStore:
    """Store immutable image bytes under opaque, mechanically isolated tenant keys."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        provided_client = client is not None
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=Config(s3={"addressing_style": "path"}),
            )
        self._client = client
        self._bucket_ready = provided_client
        self._bucket_lock = asyncio.Lock()

    @staticmethod
    def _tenant_prefix(user_id: UserId) -> str:
        opaque_tenant = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:32]
        return f"tenants/{opaque_tenant}"

    async def ensure_bucket(self) -> None:
        """Create the private bucket if it does not already exist."""

        if self._bucket_ready:
            return

        def ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self.bucket)
            except Exception as exc:  # S3-compatible clients expose provider-specific errors
                response = getattr(exc, "response", {})
                code = str(response.get("Error", {}).get("Code", ""))
                status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
                    raise
                try:
                    self._client.create_bucket(Bucket=self.bucket)
                except Exception as create_exc:
                    create_response = getattr(create_exc, "response", {})
                    create_code = str(
                        create_response.get("Error", {}).get("Code", "")
                    )
                    if create_code != "BucketAlreadyOwnedByYou":
                        raise

        async with self._bucket_lock:
            if self._bucket_ready:
                return
            await asyncio.to_thread(ensure)
            self._bucket_ready = True

    async def put(
        self,
        user_id: UserId,
        data: bytes,
        *,
        sha256: str,
        mime_type: str,
    ) -> str:
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise ValueError("media sha256 does not match object bytes")
        if mime_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            raise ValueError(f"unsupported image MIME type: {mime_type!r}")
        await self.ensure_bucket()
        prefix = self._tenant_prefix(user_id)
        key = f"{prefix}/images/sha256/{sha256[:2]}/{sha256}"
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=mime_type,
            Metadata={"sha256": sha256},
        )
        return key

    async def get(self, user_id: UserId, storage_key: str) -> bytes:
        prefix = self._tenant_prefix(user_id) + "/"
        if not storage_key.startswith(prefix):
            raise PermissionError("media object does not belong to this tenant")

        def read() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=storage_key)
            body = response["Body"]
            try:
                return body.read()
            finally:
                close = getattr(body, "close", None)
                if close is not None:
                    close()

        return await asyncio.to_thread(read)

    async def delete_user(self, user_id: UserId) -> None:
        """Remove all objects under this tenant's opaque prefix, in bounded batches."""

        await self.ensure_bucket()
        prefix = self._tenant_prefix(user_id) + "/"

        def delete() -> None:
            token: str | None = None
            while True:
                request: dict[str, Any] = {
                    "Bucket": self.bucket,
                    "Prefix": prefix,
                    "MaxKeys": 1000,
                }
                if token is not None:
                    request["ContinuationToken"] = token
                page = self._client.list_objects_v2(**request)
                objects = [
                    {"Key": item["Key"]}
                    for item in page.get("Contents", [])
                    if str(item.get("Key", "")).startswith(prefix)
                ]
                if objects:
                    self._client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                if not page.get("IsTruncated"):
                    break
                token = page.get("NextContinuationToken")
                if not token:
                    raise RuntimeError("truncated S3 listing omitted its continuation token")

        await asyncio.to_thread(delete)

    async def copy_user(
        self,
        user_id: UserId,
        target_user_id: UserId,
        objects: Mapping[str, str],
    ) -> dict[str, str]:
        """Server-side copy immutable objects into a frozen tenant namespace."""

        await self.ensure_bucket()
        source_prefix = self._tenant_prefix(user_id) + "/"
        target_prefix = self._tenant_prefix(target_user_id)
        target_prefix_with_slash = target_prefix + "/"
        mapping: dict[str, str] = {}
        for source_key, digest in objects.items():
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("media manifest contains an invalid sha256")
            target_key = f"{target_prefix}/images/sha256/{digest[:2]}/{digest}"
            if source_key.startswith(target_prefix_with_slash):
                if source_key != target_key:
                    raise PermissionError("media object has an invalid target-tenant key")
                mapping[source_key] = source_key
                continue
            if not source_key.startswith(source_prefix):
                raise PermissionError("media object does not belong to the source tenant")
            await asyncio.to_thread(
                self._client.copy_object,
                Bucket=self.bucket,
                Key=target_key,
                CopySource={"Bucket": self.bucket, "Key": source_key},
                MetadataDirective="COPY",
            )
            mapping[source_key] = target_key
        return mapping

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool when the process exits."""

        close = getattr(self._client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)

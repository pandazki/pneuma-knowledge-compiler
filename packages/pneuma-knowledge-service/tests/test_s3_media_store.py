"""S3 media keys are immutable, content-addressed, and tenant-scoped."""

import hashlib

import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.s3_media import S3MediaStore


class Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.get_calls = 0

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        assert ContentType == "image/png"
        assert Metadata["sha256"] == hashlib.sha256(Body).hexdigest()
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket, Key):
        self.get_calls += 1
        return {"Body": Body(self.objects[(Bucket, Key)])}

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, ContinuationToken=None):
        assert MaxKeys == 1000
        assert ContinuationToken is None
        contents = [
            {"Key": key}
            for bucket, key in self.objects
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def delete_objects(self, *, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop((Bucket, item["Key"]), None)

    def copy_object(self, *, Bucket, Key, CopySource, MetadataDirective):
        assert MetadataDirective == "COPY"
        self.objects[(Bucket, Key)] = self.objects[
            (CopySource["Bucket"], CopySource["Key"])
        ]


class S3Error(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class RacingBucketS3:
    def head_bucket(self, *, Bucket):  # noqa: ARG002
        raise S3Error("NoSuchBucket", 404)

    def create_bucket(self, *, Bucket):  # noqa: ARG002
        raise S3Error("BucketAlreadyOwnedByYou", 409)


async def test_s3_media_store_refuses_cross_tenant_object_keys():
    client = FakeS3()
    store = S3MediaStore(client=client, bucket="private-media")
    data = b"image-bytes"
    digest = hashlib.sha256(data).hexdigest()

    key = await store.put(
        UserId("tenant-a"), data, sha256=digest, mime_type="image/png"
    )
    assert "tenant-a" not in key
    assert await store.get(UserId("tenant-a"), key) == data

    copied = await store.copy_user(
        UserId("tenant-a"), UserId("tenant-b"), {key: digest}
    )
    assert copied[key] != key
    assert await store.get(UserId("tenant-b"), copied[key]) == data

    with pytest.raises(PermissionError):
        await store.get(UserId("tenant-b"), key)
    assert client.get_calls == 2

    await store.delete_user(UserId("tenant-a"))
    assert list(client.objects) == [("private-media", copied[key])]


async def test_bucket_creation_is_idempotent_across_api_and_worker_processes():
    store = S3MediaStore(client=RacingBucketS3(), bucket="private-media")
    store._bucket_ready = False

    await store.ensure_bucket()

    assert store._bucket_ready

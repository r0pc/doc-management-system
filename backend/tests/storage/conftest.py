"""Shared fixtures + fakes for the storage contract suite.

``FakeS3Client`` is a dict-backed stub implementing the surface
``app.storage.s3.S3Client`` expects; it records every call so contract tests
can assert on wire-level details (buckets, headers, TTLs) without network.
"""

import hashlib
import io
import re
import uuid
from pathlib import Path
from typing import Final

import pytest
from botocore.exceptions import ClientError  # test-only: fabricates 404s, no network

from app.storage.base import ByteStream
from app.storage.local import LocalStorage
from app.storage.s3 import (
    S3DeleteResponse,
    S3GetResponse,
    S3HeadResponse,
    S3PutResponse,
    S3Storage,
)

TENANT_ID: Final = uuid.UUID(int=1)
UPLOAD_ID: Final = uuid.UUID(int=2)
SHA_A: Final = hashlib.sha256(b"document-a").hexdigest()
SHA_B: Final = hashlib.sha256(b"document-b").hexdigest()
LOCAL_SECRET: Final = b"unit-test-signing-key"

_RANGE_HEADER_RE: Final = re.compile(r"bytes=(\d+)-(\d+)")


def _slice_by_range(data: bytes, header: str) -> bytes:
    """Apply an S3-style inclusive ``bytes=a-b`` header to a payload."""
    match = _RANGE_HEADER_RE.fullmatch(header)
    if match is None:
        msg = f"unrecognised Range header: {header!r}"
        raise ValueError(msg)
    start, end = int(match.group(1)), int(match.group(2))
    return data[start : end + 1]


class FakeS3Client:
    """Dict-backed S3 client stub; every call is recorded for assertions.

    Method signatures mirror ``app.storage.s3.S3Client`` (boto3 PascalCase
    wire names, hence the per-line N803 opt-outs).
    """

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _record(self, operation: str, **kwargs: object) -> None:
        self.calls.append((operation, kwargs))

    def calls_to(self, operation: str) -> list[dict[str, object]]:
        """All recorded kwarg dicts for one operation, in call order."""
        return [kwargs for name, kwargs in self.calls if name == operation]

    def seed(self, bucket: str, key: str, data: bytes) -> None:
        """Pre-place an object as if uploaded out-of-band."""
        self.objects[(bucket, key)] = data

    def head_object(self, *, Bucket: str, Key: str) -> S3HeadResponse:  # noqa: N803
        self._record("head_object", Bucket=Bucket, Key=Key)
        if (Bucket, Key) not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def get_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Range: str | None = None,  # noqa: N803
    ) -> S3GetResponse:
        self._record("get_object", Bucket=Bucket, Key=Key, Range=Range)
        data = self.objects.get((Bucket, Key))
        if data is None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        payload = data if Range is None else _slice_by_range(data, Range)
        return {"Body": io.BytesIO(payload)}

    def put_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Body: ByteStream,  # noqa: N803
        ContentType: str | None = None,  # noqa: N803
    ) -> S3PutResponse:
        self._record("put_object", Bucket=Bucket, Key=Key, ContentType=ContentType)
        self.objects[(Bucket, Key)] = Body.read()
        return {"ETag": f'"fake-{len(self.calls)}"'}

    def delete_object(self, *, Bucket: str, Key: str) -> S3DeleteResponse:  # noqa: N803
        self._record("delete_object", Bucket=Bucket, Key=Key)
        self.objects.pop((Bucket, Key), None)
        return {}

    def generate_presigned_url(
        self,
        ClientMethod: str,  # noqa: N803
        Params: dict[str, str],  # noqa: N803
        ExpiresIn: int,  # noqa: N803
    ) -> str:
        self._record(
            "generate_presigned_url", ClientMethod=ClientMethod, Params=Params, ExpiresIn=ExpiresIn
        )
        bucket = Params.get("Bucket", "")
        key = Params.get("Key", "")
        return f"https://fake.s3.local/{bucket}/{key}?method={ClientMethod}&expires_in={ExpiresIn}"

    def generate_presigned_post(
        self,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Fields: dict[str, str],  # noqa: N803
        Conditions: list[dict[str, str] | list[str | int]],  # noqa: N803
        ExpiresIn: int,  # noqa: N803
    ) -> dict[str, object]:
        self._record(
            "generate_presigned_post",
            Bucket=Bucket,
            Key=Key,
            Fields=Fields,
            Conditions=Conditions,
            ExpiresIn=ExpiresIn,
        )
        return {
            "url": f"https://fake.s3.local/{Bucket}/{Key}",
            "fields": Fields,
        }


@pytest.fixture
def local_secret() -> bytes:
    return LOCAL_SECRET


@pytest.fixture
def local_storage(tmp_path: Path, local_secret: bytes) -> LocalStorage:
    return LocalStorage(tmp_path / "blobs", signing_secret=local_secret)


@pytest.fixture
def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def s3_storage(fake_s3: FakeS3Client) -> S3Storage:
    return S3Storage(fake_s3)

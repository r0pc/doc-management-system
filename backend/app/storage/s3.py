"""MinIO/S3 backend built on an INJECTED boto3-compatible client.

Constructor injection keeps this module free of any boto3 constructor call and
lets tests substitute a dict-backed fake. Only ``ClientError`` is imported from
botocore, for 404 detection in the immutability pre-check (#16).
"""

from __future__ import annotations

from typing import Any, BinaryIO, Final, Protocol, TypedDict

# botocore ships no py.typed/stubs and pyproject edits are out of scope this
# wave; this narrow ignore is the documented exception (mypy strict otherwise).
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.storage.base import ByteStream, PresignedUpload, PrimaryBlobGuard, clamp_presign_ttl
from app.storage.keys import DEFAULT_BUCKET_PREFIX, bucket_name, key_kind


class S3HeadResponse(TypedDict, total=False):
    ContentLength: int
    ContentType: str


class S3GetResponse(TypedDict):
    Body: BinaryIO


class S3PutResponse(TypedDict, total=False):
    ETag: str


class S3DeleteResponse(TypedDict, total=False):
    DeleteMarker: bool


class S3Client(Protocol):
    """Structural surface of the boto3 S3 client this backend actually uses.

    Parameter names mirror boto3's PascalCase wire API verbatim — renaming them
    would break keyword compatibility, so each carries a targeted N803 opt-out.
    """

    def head_object(self, *, Bucket: str, Key: str) -> S3HeadResponse: ...  # noqa: N803

    def get_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Range: str | None = None,  # noqa: N803
    ) -> S3GetResponse: ...

    def put_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Body: ByteStream,  # noqa: N803
        ContentType: str | None = None,  # noqa: N803
    ) -> S3PutResponse: ...

    def delete_object(self, *, Bucket: str, Key: str) -> S3DeleteResponse: ...  # noqa: N803

    def generate_presigned_url(
        self,
        ClientMethod: str,  # noqa: N803
        Params: dict[str, str],  # noqa: N803
        ExpiresIn: int,  # noqa: N803
    ) -> str: ...

    def generate_presigned_post(
        self,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Fields: dict[str, str],  # noqa: N803
        Conditions: list[dict[str, str] | list[str | int]],  # noqa: N803
        ExpiresIn: int,  # noqa: N803
    ) -> dict[str, Any]: ...


_NOT_FOUND_CODES: Final[frozenset[str]] = frozenset({"404", "NoSuchKey", "NotFound"})


def _is_not_found(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    code = error.get("Code", "") if isinstance(error, dict) else ""
    return code in _NOT_FOUND_CODES


class S3Storage(PrimaryBlobGuard):
    """MinIO/S3 storage. One bucket per kind: ``<prefix>quarantine|primary|derived``."""

    def __init__(self, client: S3Client, bucket_prefix: str = DEFAULT_BUCKET_PREFIX) -> None:
        self._client = client
        self.bucket_prefix = bucket_prefix

    def _bucket_for(self, key: str) -> str:
        kind = key_kind(key, prefix=self.bucket_prefix)
        if kind is None:
            msg = f"key carries no known kind prefix: {key!r}"
            raise ValueError(msg)
        return bucket_name(kind, prefix=self.bucket_prefix)

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> str:
        return self.guarded_put(key, data, content_type=content_type)

    def stat(self, key: str) -> ObjectStat | None:
        try:
            head = self._client.head_object(Bucket=self._bucket_for(key), Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise
        return ObjectStat(size_bytes=int(head["ContentLength"]))

    def _open_existing(self, key: str) -> BinaryIO | None:
        bucket = self._bucket_for(key)
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise
        return self._client.get_object(Bucket=bucket, Key=key)["Body"]

    def _write_object(self, key: str, data: ByteStream, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket_for(key), Key=key, Body=data, ContentType=content_type
        )

    def open(self, key: str, *, byte_range: tuple[int, int] | None = None) -> BinaryIO:
        bucket = self._bucket_for(key)
        if byte_range is None:
            response = self._client.get_object(Bucket=bucket, Key=key)
        else:
            start, end = byte_range
            if start < 0 or end < start:
                msg = f"invalid byte_range: {byte_range!r}"
                raise ValueError(msg)
            response = self._client.get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")
        return response["Body"]

    def presign(self, key: str, ttl: int, *, filename: str) -> str:
        """Presigned GET with pinned attachment disposition; ttl clamped 60..120."""
        return self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self._bucket_for(key),
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=clamp_presign_ttl(ttl),
        )

    def presign_put(
        self, key: str, ttl: int, *, content_type: str, max_bytes: int
    ) -> PresignedUpload:
        """Presigned direct upload with a storage-enforced size ceiling.

        A presigned PUT URL cannot express a size limit, so this issues a
        presigned POST policy instead: content-length-range is evaluated by the
        storage service, which is the only enforcement a client cannot bypass.
        """
        signed = self._client.generate_presigned_post(
            Bucket=self._bucket_for(key),
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=clamp_presign_ttl(ttl, max_ttl=900),
        )
        return PresignedUpload(url=signed["url"], fields=signed["fields"])

    def delete(self, key: str) -> None:
        self.require_mutable(key)
        self._client.delete_object(Bucket=self._bucket_for(key), Key=key)

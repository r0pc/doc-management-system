"""The presigned upload credential must carry a size ceiling.

Without it the only enforcement is a client-supplied integer and a JS check,
so any client can PUT an object of any size into the quarantine bucket.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.storage.s3 import S3Storage


def _storage() -> tuple[S3Storage, MagicMock]:
    client = MagicMock()
    client.generate_presigned_post.return_value = {"url": "http://minio/b", "fields": {}}
    return S3Storage(client, bucket_prefix="docs-"), client


def test_presign_put_pins_a_content_length_range() -> None:
    storage, client = _storage()
    storage.presign_put("docs-quarantine/t/d", 120, content_type="application/pdf", max_bytes=1024)
    conditions = client.generate_presigned_post.call_args.kwargs["Conditions"]
    assert ["content-length-range", 1, 1024] in conditions


def test_presign_put_requires_max_bytes() -> None:
    storage, _ = _storage()
    try:
        storage.presign_put("k", 120, content_type="application/pdf")  # type: ignore[call-arg]
    except TypeError:
        return
    raise AssertionError("max_bytes must be required, not optional")

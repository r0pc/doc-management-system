"""A download credential must not authorise an upload.

presign signed key:expires only, and one verifier served both routes, so a GET
URL was a valid PUT credential for the same key.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest

from app.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path, signing_secret="s" * 32, bucket_prefix="docs-")


def _sig_and_expiry(url: str) -> tuple[str, int]:
    query = parse_qs(urlparse(url).query)
    return query["sig"][0], int(query["expires"][0])


def test_get_credential_does_not_verify_for_put(storage: LocalStorage) -> None:
    url = storage.presign("docs-primary/t/ab/abc", 120, filename="x.pdf", method="GET")
    sig, expires = _sig_and_expiry(url)
    assert storage.verify_presign("docs-primary/t/ab/abc", expires, sig, method="GET")
    assert not storage.verify_presign("docs-primary/t/ab/abc", expires, sig, method="PUT")


def test_put_credential_does_not_verify_for_get(storage: LocalStorage) -> None:
    url = storage.presign("docs-quarantine/t/d", 120, filename="x.pdf", method="PUT")
    sig, expires = _sig_and_expiry(url)
    assert storage.verify_presign("docs-quarantine/t/d", expires, sig, method="PUT")
    assert not storage.verify_presign("docs-quarantine/t/d", expires, sig, method="GET")


def test_expired_credential_is_rejected(storage: LocalStorage) -> None:
    url = storage.presign("docs-primary/t/ab/abc", 120, filename="x.pdf", method="GET")
    sig, expires = _sig_and_expiry(url)
    assert not storage.verify_presign(
        "docs-primary/t/ab/abc", expires, sig, method="GET", now=time.time() + 10_000
    )

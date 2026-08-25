"""Contract tests for content-addressed key builders (pure functions)."""

import hashlib
import uuid

import pytest

from app.storage.keys import (
    DEFAULT_BUCKET_PREFIX,
    bucket_name,
    derived_key,
    key_kind,
    primary_key,
    quarantine_key,
)

TENANT_ID = uuid.UUID(int=1)
UPLOAD_ID = uuid.UUID(int=2)
SHA = hashlib.sha256(b"payload").hexdigest()


def test_quarantine_key_embeds_tenant_and_upload():
    assert quarantine_key(TENANT_ID, UPLOAD_ID) == f"docs-quarantine/{TENANT_ID}/{UPLOAD_ID}"


def test_primary_key_shards_by_first_two_hex_chars():
    assert primary_key(TENANT_ID, SHA) == f"docs-primary/{TENANT_ID}/{SHA[:2]}/{SHA}"


def test_derived_key_names_artifact_under_sha():
    assert derived_key(SHA, "text.txt") == f"docs-derived/{SHA}/text.txt"


def test_bucket_name_prefixes_kind():
    assert bucket_name("primary") == "docs-primary"
    assert bucket_name("quarantine") == "docs-quarantine"
    assert bucket_name("derived") == "docs-derived"


def test_custom_prefix_propagates_to_keys_and_buckets():
    assert (
        quarantine_key(TENANT_ID, UPLOAD_ID, prefix="acme-")
        == f"acme-quarantine/{TENANT_ID}/{UPLOAD_ID}"
    )
    assert (
        primary_key(TENANT_ID, SHA, prefix="acme-") == f"acme-primary/{TENANT_ID}/{SHA[:2]}/{SHA}"
    )
    assert bucket_name("primary", prefix="acme-") == "acme-primary"
    assert DEFAULT_BUCKET_PREFIX == "docs-"


@pytest.mark.parametrize("bad", ["", "abc", "Z" * 64, "g" * 64, SHA[:-1]])
def test_primary_key_rejects_non_canonical_sha256(bad):
    with pytest.raises(ValueError):
        primary_key(TENANT_ID, bad)


def test_derived_key_rejects_non_canonical_sha256():
    with pytest.raises(ValueError):
        derived_key("nothex", "text.txt")


def test_key_kind_classifies_known_prefixes():
    assert key_kind(primary_key(TENANT_ID, SHA)) == "primary"
    assert key_kind(quarantine_key(TENANT_ID, UPLOAD_ID)) == "quarantine"
    assert key_kind(derived_key(SHA, "embed.bin")) == "derived"


def test_key_kind_unknown_prefix_returns_none():
    assert key_kind("foreign/thing") is None

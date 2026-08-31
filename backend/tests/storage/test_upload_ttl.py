"""Upload URLs have a separate TTL ceiling from download URLs."""

from __future__ import annotations

from app.config import Settings


def test_upload_ttl_setting_exists() -> None:
    settings = Settings()
    assert settings.upload_presign_ttl_seconds == 900


def test_upload_ttl_is_clamped_higher(s3_storage, fake_s3) -> None:
    s3_storage.presign_put("docs-quarantine/t/k", 600, content_type="text/plain", max_bytes=100)
    assert fake_s3.calls_to("generate_presigned_post")[0]["ExpiresIn"] == 600


def test_local_upload_ttl_is_clamped_higher(local_storage, monkeypatch) -> None:
    import time

    monkeypatch.setattr(time, "time", lambda: 1000.0)
    url = local_storage.presign("docs-quarantine/t/k", 600, filename="f.txt", method="PUT")
    assert "expires=1600" in url

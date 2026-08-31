"""clamd's StreamMaxLength must not be below the upload cap.

Below it, every file in the gap aborts the INSTREAM exchange and burns three
retries before failing — a size limit enforced by timeout instead of by 413.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLAMD_CONF = _REPO_ROOT / "docker" / "clamav" / "clamd.conf"

_SUFFIX = {"K": 1024, "M": 1024**2, "G": 1024**3}


def _parse_size(text: str) -> int:
    match = re.fullmatch(r"(\d+)([KMG]?)", text.strip(), re.IGNORECASE)
    assert match, f"unparseable size: {text!r}"
    return int(match.group(1)) * _SUFFIX.get(match.group(2).upper(), 1)


def _directive(name: str) -> str:
    for line in _CLAMD_CONF.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name} "):
            return stripped.split(None, 1)[1]
    raise AssertionError(f"{name} not set in {_CLAMD_CONF}")


def _dev_settings() -> Settings:
    # Settings(env="dev") alone fails validation (DEV_JWT_SECRET is required in
    # dev); match the construction pattern used elsewhere under tests/.
    return Settings(env="dev", dev_jwt_secret="s3cret-for-tests")  # noqa: S106


def test_stream_max_length_covers_the_upload_cap() -> None:
    cap = _dev_settings().upload_max_bytes
    assert _parse_size(_directive("StreamMaxLength")) >= cap


def test_max_file_size_covers_the_upload_cap() -> None:
    cap = _dev_settings().upload_max_bytes
    assert _parse_size(_directive("MaxFileSize")) >= cap

"""Shell scripts used as container entrypoints must be executable in git.

This is a Windows-invisible failure. `core.fileMode=false` on a Windows clone
makes git ignore the local execute bit entirely, and Docker Desktop applies its
own 0755 to files it copies in — so a script committed as 100644 runs fine on a
Windows host and dies on Linux with

    service "migrate" didn't complete successfully: exit 126

126 is "found but not executable". Compose invokes these with the exec form
(`entrypoint: ["./scripts/entrypoint-api.sh"]`), so the kernel, not a shell,
decides — and it refuses a non-executable file.

Asserting on git's recorded mode rather than the filesystem is deliberate: the
filesystem bit is meaningless on Windows, but the index mode is what actually
ships to CI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Scripts referenced as a container entrypoint or run directly.
EXECUTABLE_SCRIPTS = [
    "backend/scripts/entrypoint-api.sh",
    "backend/scripts/e2e.sh",
    "scripts/e2e.sh",
]

_GIT_EXEC_MODE = "100755"


def _git_mode(path: str) -> str:
    # S603/S607 suppressed deliberately: `path` comes from the module-level
    # EXECUTABLE_SCRIPTS constant, never from input, and `--` terminates option
    # parsing so a path can never be read as a flag. Resolving git by absolute
    # path would make the test non-portable across the dev hosts and CI.
    result = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-s", "--", path],  # noqa: S607
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    if not result.stdout.strip():
        pytest.skip(f"{path} is not tracked by git")
    return result.stdout.split()[0]


@pytest.mark.parametrize("script", EXECUTABLE_SCRIPTS)
def test_entrypoint_scripts_are_executable_in_git(script: str) -> None:
    mode = _git_mode(script)
    assert mode == _GIT_EXEC_MODE, (
        f"{script} is committed as {mode}, not {_GIT_EXEC_MODE}. On Linux this "
        f"is exit 126 ('found but not executable') the moment compose uses it "
        f"as an entrypoint. Fix with: git update-index --chmod=+x {script}"
    )


def test_dockerfile_chmods_the_scripts_it_copies() -> None:
    """Defence in depth for the next script added from a Windows clone.

    The git mode above is the real fix, but it is easy to lose: a new file
    added on Windows arrives as 644 and nothing local complains. A chmod in
    the image build means the container works regardless.
    """
    dockerfile = (_REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "chmod +x ./scripts" in dockerfile or "chmod -R +x ./scripts" in dockerfile, (
        "backend/Dockerfile copies ./scripts but never makes them executable, "
        "so it depends entirely on the git mode being right"
    )

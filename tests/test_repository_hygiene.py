"""Repository hygiene checks that help prevent accidental PII commits."""

from pathlib import Path
import subprocess

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RAW_EMAIL_SUFFIXES = {".eml", ".msg", ".mbox", ".pst"}


def _tracked_files() -> list[Path]:
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("git metadata unavailable")

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def test_repository_does_not_track_raw_email_exports() -> None:
    tracked_sensitive_files = sorted(
        path.as_posix()
        for path in _tracked_files()
        if path.suffix.lower() in _RAW_EMAIL_SUFFIXES
    )
    assert tracked_sensitive_files == []

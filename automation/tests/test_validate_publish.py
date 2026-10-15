from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_publish import validate_publish_dir


def _write(data_dir: Path, jobs: list[dict], valid: int) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    (data_dir / "manifest.json").write_text(
        json.dumps({"counts": {"valid": valid}, "data_version": "v-test"}),
        encoding="utf-8",
    )


def test_publish_check_accepts_matching_counts(tmp_path: Path):
    data = tmp_path / "data"
    _write(data, [{"title": "医疗AI"}], 1)

    message = validate_publish_dir(data)

    assert "1" in message
    assert "v-test" in message


def test_publish_check_rejects_empty_jobs(tmp_path: Path):
    data = tmp_path / "data"
    _write(data, [], 0)

    with pytest.raises(SystemExit, match="空岗位"):
        validate_publish_dir(data)


def test_publish_check_rejects_manifest_mismatch(tmp_path: Path):
    data = tmp_path / "data"
    _write(data, [{"title": "医疗AI"}], 2)

    with pytest.raises(SystemExit, match="数量不一致"):
        validate_publish_dir(data)

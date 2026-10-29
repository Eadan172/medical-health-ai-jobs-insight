"""Publication gate for a local run before the daily report is mailed.

``automation/scripts/run-local.ps1`` calls this after the pipeline writes
``web/public/data``, then restores the tracked example placeholders. GitHub
Actions must not commit that directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def validate_publish_dir(data_dir: Path) -> str:
    """Return a success line, or raise ``SystemExit`` when the data must not be pushed."""

    jobs_path = data_dir / "jobs.json"
    manifest_path = data_dir / "manifest.json"
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not jobs:
        raise SystemExit("拒绝提交空岗位列表")
    valid = (manifest.get("counts") or {}).get("valid")
    if valid != len(jobs):
        raise SystemExit(f"manifest 与 jobs.json 数量不一致: valid={valid} jobs={len(jobs)}")
    return f"数据校验通过：{len(jobs)} 条，版本 {manifest.get('data_version')}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    data_dir = root / "web" / "public" / "data" if (root / "web" / "public" / "data").is_dir() else root
    try:
        print(validate_publish_dir(data_dir))
    except SystemExit as exc:
        message = exc.code if isinstance(exc.code, str) else "数据校验失败"
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Mail settings can come from .env.local without overriding the process."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "send_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("send_report_env", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_mail_env_fills_missing_keys_only(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text("MAIL163_SMTP_USER=from-file@163.com\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text(
        "MAIL163_SMTP_AUTH_CODE=auth-code\nJOBSINSIGHT_REPORT_TO=me@example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL163_SMTP_USER", "already@163.com")
    monkeypatch.delenv("MAIL163_SMTP_AUTH_CODE", raising=False)
    monkeypatch.delenv("JOBSINSIGHT_REPORT_TO", raising=False)

    _load().load_mail_env(tmp_path)

    assert os.environ["MAIL163_SMTP_USER"] == "already@163.com"
    assert os.environ["MAIL163_SMTP_AUTH_CODE"] == "auth-code"
    assert os.environ["JOBSINSIGHT_REPORT_TO"] == "me@example.com"

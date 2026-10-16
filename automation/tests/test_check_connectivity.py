"""Offline checks for the connectivity script. No network."""

from __future__ import annotations

import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_connectivity.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_connectivity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_is_stdlib_only_and_has_no_secrets():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import " in text
    for banned in ("requests", "httpx", "playwright", "api_key", "sk-", "Authorization"):
        assert banned not in text
    module = _load()
    names = {item[1] for item in module.TARGETS}
    assert {"DeepSeek API", "OpenAI API", "Gemini API", "hf-mirror BGE-M3", "We Work Remotely RSS"} <= names


def test_verdict_treats_auth_and_not_found_as_reachable():
    module = _load()
    assert module.verdict(None, False) == "不可达"
    assert module.verdict(200, True) == "可达"
    for code in (401, 403, 404, 405, 422, 429):
        assert module.verdict(code, True) == "可达"
    assert module.verdict(500, True) == "可达(服务端错误)"
    assert module.verdict(400, True) == "可达"


def test_load_extra_formats(tmp_path: Path):
    module = _load()
    target = tmp_path / "extra.txt"
    target.write_text(
        "# comment\n\nhttps://example.com/a\n名称,https://example.com/b\n岗位,远程,https://example.com/c\n",
        encoding="utf-8",
    )
    assert module.load_extra(str(target)) == [
        ("自定义", "https://example.com/a", "https://example.com/a"),
        ("自定义", "名称", "https://example.com/b"),
        ("岗位", "远程", "https://example.com/c"),
    ]


def test_one_try_records_http_401_without_credentials():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"nope")

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        module = _load()
        row = module.one_try(f"http://127.0.0.1:{server.server_address[1]}/", 5)
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert row["dns"] is True
    assert row["tcp"] is True
    assert row["http"] == 401
    assert row["err"] == ""

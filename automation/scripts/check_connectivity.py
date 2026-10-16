#!/usr/bin/env python3
"""DNS / TCP / TLS / HTTP connectivity check. Standard library only; no API keys.

Usage:
    python check_connectivity.py [--targets file.txt] [--tries 3] [--timeout 10] [--only qa|jobs]
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

TARGETS = [
    # (group, name, URL)
    ("问答", "ima 首页", "https://ima.qq.com/"),
    ("问答", "ima agent-interface", "https://ima.qq.com/agent-interface"),
    ("问答", "Serper", "https://google.serper.dev/search"),
    ("问答", "SerpApi", "https://serpapi.com/search.json"),
    ("问答", "Tavily", "https://api.tavily.com/search"),
    ("问答", "Gemini API", "https://generativelanguage.googleapis.com/v1beta/models"),
    ("问答", "DeepSeek API", "https://api.deepseek.com/models"),
    ("问答", "OpenAI API", "https://api.openai.com/v1/models"),
    ("问答", "HuggingFace BGE-M3", "https://huggingface.co/BAAI/bge-m3/resolve/main/config.json"),
    ("问答", "hf-mirror BGE-M3", "https://hf-mirror.com/BAAI/bge-m3/resolve/main/config.json"),
    ("岗位", "Greenhouse", "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"),
    ("岗位", "Lever", "https://api.lever.co/v0/postings/palantir?mode=json"),
    ("岗位", "Ashby", "https://api.ashbyhq.com/posting-api/job-board/ramp"),
    ("岗位", "Workable", "https://apply.workable.com/"),
    ("岗位", "Remote OK", "https://remoteok.com/api"),
    ("岗位", "We Work Remotely RSS", "https://weworkremotely.com/remote-jobs.rss"),
    ("岗位", "MyCareersFuture", "https://api.mycareersfuture.gov.sg/v2/jobs?limit=1&page=0"),
    ("岗位", "HRMOS", "https://hrmos.co/"),
    ("岗位", "北森 zhiye(联影智能)", "https://uii-ai.zhiye.com/social/jobs"),
    ("岗位", "腾讯招聘", "https://careers.tencent.com/"),
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) connectivity-check/1.0"
GROUP_NAMES = {"qa": "问答", "jobs": "岗位"}


def one_try(url: str, timeout: float) -> dict[str, object]:
    result: dict[str, object] = {
        "dns": False,
        "tcp": False,
        "tls": False,
        "http": None,
        "ms": None,
        "err": "",
    }
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    started = time.perf_counter()
    if not host:
        result["err"] = "URL 没有主机名"
        result["ms"] = 0
        return result
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        result["dns"] = True
        result["ip"] = addresses[0][4][0]
    except Exception as exc:
        result["err"] = f"DNS: {exc}"
        result["ms"] = round((time.perf_counter() - started) * 1000)
        return result

    sock: socket.socket | None = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        result["tcp"] = True
        if parsed.scheme == "https":
            tls_sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            result["tls"] = True
            sock = None
            tls_sock.close()
        else:
            sock.close()
            sock = None
            result["tls"] = None
    except Exception as exc:
        stage = "TLS" if result["tcp"] else "TCP"
        result["err"] = f"{stage}: {type(exc).__name__}: {exc}"
        result["ms"] = round((time.perf_counter() - started) * 1000)
        return result
    finally:
        if sock is not None:
            sock.close()

    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result["http"] = response.status
            response.read(2048)
    except urllib.error.HTTPError as exc:
        result["http"] = exc.code
    except Exception as exc:
        result["err"] = f"HTTP: {type(exc).__name__}: {exc}"
    result["ms"] = round((time.perf_counter() - started) * 1000)
    return result


def _http_code(value: object) -> int | None:
    return value if isinstance(value, int) else None


def verdict(code: int | None, _tls_ok: bool) -> str:
    """401/403/404/405/422/429 still count as reachable: the host answered."""

    if code is None:
        return "不可达"
    if code < 400 or code in (401, 403, 404, 405, 422, 429):
        return "可达"
    if code >= 500:
        return "可达(服务端错误)"
    return "可达"


def load_extra(path: str) -> list[tuple[str, str, str]]:
    extra: list[tuple[str, str, str]] = []
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) == 1:
                extra.append(("自定义", parts[0], parts[0]))
            elif len(parts) == 2:
                extra.append(("自定义", parts[0], parts[1]))
            else:
                extra.append((parts[0], parts[1], parts[2]))
    return extra


def main() -> None:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="DNS/TCP/TLS/HTTP 连通性测试")
    parser.add_argument("--targets", help="追加目标文件：每行 URL，或 名称,URL，或 分组,名称,URL")
    parser.add_argument("--tries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--only", choices=["qa", "jobs"], help="只测某一组")
    parser.add_argument("--outdir", default=".")
    args = parser.parse_args()

    targets = list(TARGETS)
    if args.only:
        targets = [item for item in targets if item[0] == GROUP_NAMES[args.only]]
    if args.targets:
        targets += load_extra(args.targets)
    if not targets:
        print("没有要测试的目标")
        return

    rows: list[dict[str, object]] = []
    for group, name, url in targets:
        tries = [one_try(url, args.timeout) for _ in range(args.tries)]
        ok = [item for item in tries if item["http"] is not None]
        codes = sorted({str(item["http"]) for item in ok})
        errors = sorted({str(item["err"]) for item in tries if item["err"]})
        row: dict[str, object] = {
            "group": group,
            "name": name,
            "url": url,
            "host": urlparse(url).hostname,
            "ip": next((item.get("ip") for item in tries if item.get("ip")), ""),
            "dns_ok": f"{sum(bool(item['dns']) for item in tries)}/{args.tries}",
            "tls_ok": f"{sum(bool(item['tls']) for item in tries)}/{args.tries}",
            "http_status": "/".join(codes) or "-",
            "http_ok": f"{len(ok)}/{args.tries}",
            "avg_ms": round(sum(int(item["ms"]) for item in ok) / len(ok)) if ok else None,
            "verdict": verdict(_http_code(ok[0]["http"]) if ok else None, True),
            "errors": " | ".join(errors)[:300],
        }
        rows.append(row)
        avg = str(row["avg_ms"] or "-")
        print(
            f"[{group}] {name:<24} DNS {row['dns_ok']} TLS {row['tls_ok']} "
            f"HTTP {str(row['http_status']):<8} {avg:>6}ms  {row['verdict']}  {str(row['errors'])[:80]}",
            flush=True,
        )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, f"connectivity_result_{stamp}.csv")
    json_path = os.path.join(args.outdir, f"connectivity_result_{stamp}.json")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"time": stamp, "tries": args.tries, "timeout_s": args.timeout, "results": rows},
            handle,
            ensure_ascii=False,
            indent=2,
        )
    reachable = sum(row["verdict"] != "不可达" for row in rows)
    print(f"\n可达 {reachable}/{len(rows)}。结果已写入:\n  {csv_path}\n  {json_path}")


if __name__ == "__main__":
    main()

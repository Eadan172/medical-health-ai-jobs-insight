"""Tiny stdlib HTTP helper shared by the LLM providers.

Kept dependency-free on purpose: the automation must be runnable on a bare
Python 3.11+ install (CI runners, cron boxes) without a package install step.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from .base import LLMTransportError

#: Status codes worth retrying: rate limits plus transient server failures.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})

JsonTransport = Callable[[str, Mapping[str, str], Mapping[str, Any], float], dict[str, Any]]


def post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout: float,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # noqa: PERF203 - distinct handling per error
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise LLMTransportError(
            f"HTTP {exc.code} from {url}: {detail}",
            status=exc.code,
            retryable=exc.code in RETRYABLE_STATUS,
        ) from exc
    except urllib.error.URLError as exc:
        raise LLMTransportError(f"cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMTransportError(f"timeout after {timeout}s calling {url}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMTransportError(f"non-JSON response from {url}: {raw[:400]}", retryable=False) from exc

    if not isinstance(parsed, dict):
        raise LLMTransportError(f"unexpected response shape from {url}: {type(parsed).__name__}", retryable=False)
    return parsed

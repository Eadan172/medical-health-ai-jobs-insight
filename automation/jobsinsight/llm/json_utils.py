"""Helpers for coaxing valid JSON out of chat completions."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def strip_code_fence(text: str) -> str:
    match = _FENCE.search(text)
    return match.group(1).strip() if match else text.strip()


def _scan_balanced(text: str, opening: str, closing: str) -> str | None:
    """Return the first balanced ``opening``/``closing`` span, ignoring strings."""

    start = text.find(opening)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def extract_json(text: str) -> Any:
    """Parse the first JSON object or array embedded in ``text``.

    Chat models like to wrap JSON in prose or code fences even when asked not
    to; this recovers the payload instead of failing the whole run.
    """

    candidate = strip_code_fence(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Try whichever delimiter appears first, so a leading array is not mistaken
    # for one of the objects inside it.
    spans = [
        (candidate.find(opening), _scan_balanced(candidate, opening, closing))
        for opening, closing in (("{", "}"), ("[", "]"))
    ]
    for start, span in sorted(spans, key=lambda item: (item[0] < 0, item[0])):
        if start < 0 or not span:
            continue
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"no JSON payload found in model output: {candidate[:200]!r}")

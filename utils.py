import hashlib
import json
import random
import urllib.parse
from typing import Any


def encode_weread_id(value: str | int) -> str:
    """Encode WeRead IDs (from client logic)."""
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        raise TypeError("encode_weread_id expects str or int")
    md5_hex = hashlib.md5(value.encode()).hexdigest()
    prefix = md5_hex[:3]
    if value.isdigit():
        pieces = []
        for i in range(0, len(value), 9):
            chunk = value[i : i + 9]
            pieces.append(format(int(chunk), "x"))
        flag = "3"
    else:
        pieces = ["".join(format(ord(ch), "x") for ch in value)]
        flag = "4"
    out = prefix + flag
    out += "2" + md5_hex[-2:]
    for idx, item in enumerate(pieces):
        length_hex = format(len(item), "x")
        if len(length_hex) == 1:
            length_hex = "0" + length_hex
        out += length_hex + item
        if idx < len(pieces) - 1:
            out += "g"
    if len(out) < 0x14:
        out += md5_hex[: 0x14 - len(out)]
    out += hashlib.md5(out.encode()).hexdigest()[:3]
    return out


def encode_data(data: dict[str, Any]) -> str:
    return "&".join(
        f"{k}={urllib.parse.quote(str(data[k]), safe='')}" for k in sorted(data.keys())
    )


def cal_hash(input_string: str) -> str:
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        _7032f5 = 0x7FFFFFFF & (
            _7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30
        )
        _cc1055 = 0x7FFFFFFF & (
            _cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30
        )
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()


def format_minutes(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def extract_safe_info(res_data: Any) -> dict[str, Any] | None:
    if isinstance(res_data, dict):
        keys = ("errcode", "errmsg", "code", "message", "succ")
        return {k: res_data.get(k) for k in keys if k in res_data}
    return None


def extract_balanced_json(text: str, start_index: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for i in range(start_index, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start_index : i + 1]
    return None


def extract_json_after_marker(text: str, marker: str) -> dict[str, Any] | None:
    idx = text.find(marker)
    if idx == -1:
        return None
    brace_start = text.find("{", idx)
    if brace_start == -1:
        return None
    blob = extract_balanced_json(text, brace_start)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except ValueError:
        return None


def extract_json_after_key(text: str, key: str) -> dict[str, Any] | None:
    idx = text.find(key)
    if idx == -1:
        return None
    colon = text.find(":", idx)
    if colon == -1:
        return None
    brace_start = text.find("{", colon)
    if brace_start == -1:
        return None
    blob = extract_balanced_json(text, brace_start)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except ValueError:
        return None


def extract_initial_state(html: str) -> dict[str, Any] | None:
    for marker in (
        "window.__INITIAL_STATE__",
        "__INITIAL_STATE__",
        "window.__NUXT__",
        "__NUXT__",
    ):
        state_obj = extract_json_after_marker(html, marker)
        if state_obj:
            return state_obj
    return None


def collect_readers(state_obj: dict[str, Any]) -> list[dict[str, Any]]:
    readers: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "reader" in obj and isinstance(obj["reader"], dict):
                readers.append(obj["reader"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(state_obj)
    return readers


def calc_read_step(interval_sec: int, word_count: int) -> int:
    interval = max(1, int(interval_sec))
    speed = random.uniform(3.0, 6.0)
    step = max(50, int(interval * speed))
    if word_count and word_count > 0:
        max_step = max(200, int(word_count * 0.05))
        step = min(step, max_step)
    return step


def advance_chapter_pos(current_pos: int, readable_positions: list[int]) -> int:
    if not readable_positions:
        return current_pos
    for pos in readable_positions:
        if pos > current_pos:
            return pos
    return readable_positions[0]


def build_readable_positions(chapters: list[dict[str, Any]]) -> list[int]:
    readable: list[int] = []
    for i, ch in enumerate(chapters):
        if ch.get("word_count", 0) > 50:
            readable.append(i)
    if readable:
        return readable
    return [i for i, _ in enumerate(chapters)]


def pick_random_chapter(
    chapters: list[dict[str, Any]], readable_positions: list[int]
) -> tuple[int, int, str | None]:
    pos = random.choice(readable_positions) if readable_positions else 0
    chapter = chapters[pos]
    word_count = chapter.get("word_count", 0)
    if word_count and word_count > 0:
        offset = random.randint(10, min(80, max(10, word_count // 50)))
    else:
        offset = 0
    return pos, offset, chapter.get("title")

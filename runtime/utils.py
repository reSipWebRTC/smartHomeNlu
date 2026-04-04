from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional


_LOCATION_WORDS = ("客厅", "卧室", "厨房", "书房", "阳台", "玄关", "全屋")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def extract_location(text: str) -> Optional[str]:
    for token in _LOCATION_WORDS:
        if token in text:
            return token
    return None


def extract_number(text: str) -> Optional[int]:
    match = re.search(r"(-?\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def short_hash(payload: Dict[str, str], size: int = 8) -> str:
    raw = "|".join(f"{k}={payload[k]}" for k in sorted(payload))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:size]


def intent_to_domain(sub_intent: str, slots: Dict[str, str]) -> str:
    device_type = slots.get("device_type")
    if device_type in {"开关", "插座"}:
        return "switch"
    if device_type == "灯" or "brightness" in sub_intent:
        return "light"
    if device_type == "空调" or "temperature" in sub_intent:
        return "climate"
    if device_type == "门锁" or "unlock" in sub_intent:
        return "lock"
    if "scene" in sub_intent or slots.get("scene_name"):
        return "scene"
    if "power" in sub_intent:
        return "light"
    return "homeassistant"

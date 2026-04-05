from __future__ import annotations

import re
from typing import Any, Dict

from .contracts import IntentJson


INTENT_WHITELIST = {"CONTROL", "QUERY", "SCENE", "SYSTEM", "CHITCHAT"}

_SUB_INTENT_ALIASES = {
    "on": "power_on",
    "open": "power_on",
    "turn_on": "power_on",
    "power_on": "power_on",
    "switch_on": "power_on",
    "start": "power_on",
    "off": "power_off",
    "close": "power_off",
    "turn_off": "power_off",
    "power_off": "power_off",
    "switch_off": "power_off",
    "stop": "power_off",
    "temperature": "set_temperature",
    "set_temp": "set_temperature",
    "set_temperature": "set_temperature",
    "adjust_temperature": "set_temperature",
    "temp": "set_temperature",
    "brightness": "adjust_brightness",
    "set_brightness": "adjust_brightness",
    "adjust_brightness": "adjust_brightness",
    "query": "query_status",
    "query_status": "query_status",
    "query_state": "query_status",
    "get_state": "query_status",
    "status": "query_status",
    "state": "query_status",
    "scene": "activate_scene",
    "run_scene": "activate_scene",
    "activate_scene": "activate_scene",
    "backup": "backup",
    "create_backup": "backup",
    "unlock": "unlock",
    "open_lock": "unlock",
    "chitchat": "chitchat",
    "chat": "chitchat",
    "clarify_needed": "clarify_needed",
    "unknown": "unknown",
}

_KEY_ALIASES = {
    "location": "location",
    "loc": "location",
    "room": "location",
    "area": "location",
    "zone": "location",
    "l": "location",
    "device_type": "device_type",
    "device": "device_type",
    "dev": "device_type",
    "d": "device_type",
    "target_device": "device_type",
    "entity_id": "entity_id",
    "entity": "entity_id",
    "scene_name": "scene_name",
    "scene": "scene_name",
    "attr": "attribute",
    "attribute": "attribute",
    "value": "value",
    "val": "value",
    "target": "value",
    "temperature": "value",
    "temp": "value",
    "brightness": "value",
    "level": "value",
    "percent": "value",
    "value_unit": "value_unit",
    "unit": "value_unit",
    "u": "value_unit",
}

_LOCATION_WORDS = ("客厅", "卧室", "厨房", "书房", "阳台", "玄关", "全屋")


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = re.sub(r"\s+", "_", text)
    return text


def canonicalize_sub_intent(sub_intent: str) -> str:
    token = _normalize_token(sub_intent)
    return _SUB_INTENT_ALIASES.get(token, token or "unknown")


def _coerce_number(value: Any) -> tuple[Any, str | None]:
    if isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)):
        return value, None

    text = str(value or "").strip()
    if not text:
        return None, None

    unit: str | None = None
    if "%" in text:
        unit = "%"
    if "℃" in text or "度" in text:
        unit = "℃"

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return text, unit

    num_text = match.group(0)
    if "." in num_text:
        return float(num_text), unit
    return int(num_text), unit


def _canonicalize_location(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for token in _LOCATION_WORDS:
        if token in text:
            return token
    if len(text) < 2:
        return None
    return text


def _canonicalize_device_type(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if any(t in text for t in ("灯", "light", "lamp")):
        return "灯"
    if any(t in text for t in ("空调", "climate", "ac")):
        return "空调"
    if any(t in text for t in ("门锁", "lock")):
        return "门锁"
    if any(t in text for t in ("插座", "socket", "outlet", "plug")):
        return "插座"
    if any(t in text for t in ("开关", "switch")):
        return "开关"
    return str(value).strip() or None


def _canonicalize_attribute(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if any(t in text for t in ("温度", "temperature", "temp")):
        return "温度"
    if any(t in text for t in ("亮度", "brightness")):
        return "亮度"
    if any(t in text for t in ("湿度", "humidity")):
        return "湿度"
    return str(value).strip() or None


def _normalize_slots(raw_slots: Dict[str, Any], sub_intent: str) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if not isinstance(raw_slots, dict):
        return normalized

    pending_unit: str | None = None
    for raw_key, raw_value in raw_slots.items():
        key_norm = _KEY_ALIASES.get(_normalize_token(raw_key), str(raw_key))
        if raw_value is None:
            continue

        if key_norm == "location":
            value = _canonicalize_location(raw_value)
            if value is not None:
                normalized["location"] = value
            continue

        if key_norm == "device_type":
            value = _canonicalize_device_type(raw_value)
            if value is not None:
                normalized["device_type"] = value
            continue

        if key_norm == "attribute":
            value = _canonicalize_attribute(raw_value)
            if value is not None:
                normalized["attribute"] = value
            continue

        if key_norm == "entity_id":
            entity_id = str(raw_value).strip()
            if "." in entity_id:
                normalized["entity_id"] = entity_id
            continue

        if key_norm == "scene_name":
            scene_name = str(raw_value).strip()
            if scene_name:
                normalized["scene_name"] = scene_name
            continue

        if key_norm == "value":
            value, unit = _coerce_number(raw_value)
            if value is not None:
                normalized["value"] = value
            if unit:
                pending_unit = unit
            continue

        if key_norm == "value_unit":
            unit = str(raw_value).strip()
            if unit:
                normalized["value_unit"] = unit
            continue

        value = str(raw_value).strip() if isinstance(raw_value, str) else raw_value
        if value not in ("", None):
            normalized[str(raw_key)] = value

    if pending_unit and "value_unit" not in normalized:
        normalized["value_unit"] = pending_unit

    if sub_intent == "set_temperature":
        normalized.setdefault("attribute", "温度")
        if "value_unit" not in normalized and "value" in normalized:
            normalized["value_unit"] = "℃"
    elif sub_intent == "adjust_brightness":
        normalized.setdefault("attribute", "亮度")
        if "value_unit" not in normalized and isinstance(normalized.get("value"), (int, float)):
            normalized["value_unit"] = "%"

    return normalized


def _infer_intent(intent: str, sub_intent: str) -> str:
    if intent in INTENT_WHITELIST:
        return intent
    if sub_intent in {"query_status"}:
        return "QUERY"
    if sub_intent in {"activate_scene"}:
        return "SCENE"
    if sub_intent in {"backup"}:
        return "SYSTEM"
    if sub_intent in {"chitchat", "unknown", "clarify_needed"}:
        return "CHITCHAT"
    return "CONTROL"


def canonicalize_intent(intent_json: IntentJson) -> IntentJson:
    sub_intent = canonicalize_sub_intent(intent_json.sub_intent)
    intent = _infer_intent(str(intent_json.intent or "").strip().upper(), sub_intent)
    slots = _normalize_slots(intent_json.slots or {}, sub_intent)
    confidence = max(0.0, min(1.0, float(intent_json.confidence)))
    return IntentJson(intent=intent, sub_intent=sub_intent, slots=slots, confidence=confidence)

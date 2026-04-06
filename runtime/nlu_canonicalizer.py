from __future__ import annotations

import re
from typing import Any, Dict

from .contracts import IntentJson
from .hot_words_lexicon import get_hot_words_lexicon


INTENT_WHITELIST = {"CONTROL", "QUERY", "SCENE", "SYSTEM", "CHITCHAT"}
_CANONICAL_SUB_INTENTS = {
    "power_on",
    "power_off",
    "set_temperature",
    "adjust_brightness",
    "query_status",
    "activate_scene",
    "backup",
    "unlock",
    "chitchat",
    "clarify_needed",
    "unknown",
}

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
    "room_name": "location",
    "room_type": "location",
    "room_number": "location",
    "floor": "location",
    "story": "location",
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

_LOCATION_WORDS = ("客厅", "卧室", "厨房", "书房", "阳台", "玄关", "全屋", "小孩房", "儿童房")
_LOCATION_ALIASES = {
    "小孩房间": "小孩房",
    "孩子房间": "小孩房",
    "儿童房间": "小孩房",
    "孩房": "小孩房",
}
_DEVICE_TYPE_STOPWORDS = {
    "系统",
    "设备",
    "东西",
    "那个",
    "这个",
    "它",
    "客厅",
    "卧室",
    "厨房",
    "书房",
    "阳台",
    "玄关",
    "全屋",
    "hall",
    "room",
    "floor",
    "none",
    "unknown",
    "null",
    "power_on",
    "power_off",
    "set_temperature",
    "adjust_brightness",
    "query_status",
    "control",
    "query",
}
_HOT_WORDS = get_hot_words_lexicon()


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = re.sub(r"\s+", "_", text)
    return text


def canonicalize_sub_intent(sub_intent: str) -> str:
    raw = _HOT_WORDS.strip_fillers(str(sub_intent or "").strip())
    token = _normalize_token(raw)
    if not token:
        return "unknown"

    hot_sub_intent = _HOT_WORDS.infer_sub_intent(raw)
    if hot_sub_intent:
        return hot_sub_intent

    # Handle phrase-like sub_intent outputs from fallback LLMs
    if any(word in raw for word in ("打开", "开启")):
        return "power_on"
    if any(word in raw for word in ("关闭", "关掉", "关上")):
        return "power_off"
    if any(word in raw for word in ("温度", "调温", "temperature")):
        return "set_temperature"
    if any(word in raw for word in ("亮度", "brightness")):
        return "adjust_brightness"
    if any(word in raw for word in ("查询", "状态", "query", "status")):
        return "query_status"
    if any(word in raw for word in ("场景", "模式", "scene")):
        return "activate_scene"

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
    text = _HOT_WORDS.strip_fillers(str(value or "").strip())
    text = re.sub(r"[，,。！？!；;\s]+", "", text)
    if not text:
        return None
    for alias, normalized in _LOCATION_ALIASES.items():
        if alias in text:
            return normalized
    for token in _LOCATION_WORDS:
        if token in text:
            return token
    hot_location = _HOT_WORDS.infer_location(text)
    if hot_location:
        return hot_location
    floor_match = re.search(r"([一二三四五六七八九十0-9]+楼)", text)
    if floor_match:
        return floor_match.group(1)
    if len(text) < 2:
        return None
    return text


def _canonicalize_device_type(value: Any) -> str | None:
    text = _HOT_WORDS.strip_fillers(str(value or "").strip()).lower()
    if not text:
        return None
    hot_device = _HOT_WORDS.infer_device_type(text)
    if hot_device:
        return hot_device
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
    if len(text) <= 1:
        return None
    if text in _DEVICE_TYPE_STOPWORDS:
        return None
    if text.endswith("系统"):
        return None
    if re.fullmatch(r"[0-9一二三四五六七八九十]+", text):
        return None
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


def _canonicalize_unit(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if "%" in text or text in {"pct", "percent", "percentage", "百分比"}:
        return "%"
    if any(token in text for token in ("℃", "°c", "celsius", "摄氏", "度", "c")):
        return "℃"
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
            raw_text = str(raw_value).strip()
            value = _canonicalize_device_type(raw_value)
            if value is not None:
                normalized["device_type"] = value
                # Preserve original text for entity search if canonicalized form differs
                if raw_text and raw_text != value:
                    normalized["_original_device_type"] = raw_text
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
            unit = _canonicalize_unit(raw_value)
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


def _infer_sub_intent_by_frame(intent: str, sub_intent: str, slots: Dict[str, Any]) -> str:
    if sub_intent in _CANONICAL_SUB_INTENTS:
        return sub_intent

    raw = str(sub_intent or "").lower()
    attribute = str(slots.get("attribute", "") or "")
    value_unit = str(slots.get("value_unit", "") or "")
    has_value = slots.get("value") not in (None, "")

    if "锁" in raw or "unlock" in raw:
        return "unlock"
    if slots.get("scene_name"):
        return "activate_scene"
    if attribute == "温度" or value_unit == "℃":
        return "set_temperature"
    if attribute == "亮度" or value_unit == "%":
        return "adjust_brightness"
    if str(intent).upper() == "QUERY":
        return "query_status"
    if str(intent).upper() == "SCENE":
        return "activate_scene"
    if str(intent).upper() == "SYSTEM":
        return "backup"
    if str(intent).upper() == "CHITCHAT":
        return "chitchat"
    if str(intent).upper() == "CONTROL":
        if has_value and not slots.get("device_type"):
            return "set_temperature" if value_unit == "℃" else "adjust_brightness" if value_unit == "%" else "unknown"
        if slots.get("entity_id") or slots.get("device_type") or slots.get("location"):
            return "power_on"
    return "unknown"


def _apply_action_slot_rules(sub_intent: str, slots: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(slots)
    if sub_intent == "set_temperature":
        normalized.setdefault("attribute", "温度")
        if "value" in normalized and "value_unit" not in normalized:
            normalized["value_unit"] = "℃"
        normalized.setdefault("device_type", "空调")
        normalized.pop("scene_name", None)
    elif sub_intent == "adjust_brightness":
        normalized.setdefault("attribute", "亮度")
        if "value" in normalized and "value_unit" not in normalized:
            normalized["value_unit"] = "%"
        normalized.setdefault("device_type", "灯")
        normalized.pop("scene_name", None)
    elif sub_intent == "activate_scene":
        normalized.pop("attribute", None)
        normalized.pop("value", None)
        normalized.pop("value_unit", None)
        normalized.pop("device_type", None)
    return normalized


def _infer_intent(intent: str, sub_intent: str) -> str:
    if intent in INTENT_WHITELIST:
        # Keep whitelist, but correct obvious intent/sub_intent mismatch.
        if sub_intent in {"power_on", "power_off", "set_temperature", "adjust_brightness", "unlock"}:
            return "CONTROL"
        if sub_intent in {"activate_scene"}:
            return "SCENE"
        if sub_intent in {"query_status"}:
            return "QUERY"
        if sub_intent in {"backup"}:
            return "SYSTEM"
        if sub_intent in {"chitchat", "unknown", "clarify_needed"}:
            return "CHITCHAT"
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
    raw_intent = str(intent_json.intent or "").strip().upper()
    sub_intent = canonicalize_sub_intent(intent_json.sub_intent)
    slots = _normalize_slots(intent_json.slots or {}, sub_intent)
    sub_intent = _infer_sub_intent_by_frame(raw_intent, sub_intent, slots)
    intent = _infer_intent(raw_intent, sub_intent)
    slots = _apply_action_slot_rules(sub_intent, slots)
    if "device_type" not in slots:
        raw_sub_intent = _HOT_WORDS.strip_fillers(str(intent_json.sub_intent or ""))
        inferred_device = _HOT_WORDS.infer_device_type(raw_sub_intent)
        if inferred_device:
            slots["device_type"] = inferred_device
        if any(token in raw_sub_intent for token in ("灯", "light", "lamp", "空调", "climate", "ac", "插座", "socket", "outlet", "plug", "门锁", "lock", "开关", "switch")):
            inferred_device = _canonicalize_device_type(raw_sub_intent)
            if inferred_device:
                slots["device_type"] = inferred_device
    confidence = max(0.0, min(1.0, float(intent_json.confidence)))
    return IntentJson(
        intent=intent,
        sub_intent=sub_intent,
        slots=slots,
        confidence=confidence,
        multi_commands=intent_json.multi_commands,
    )

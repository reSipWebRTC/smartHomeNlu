from __future__ import annotations

from typing import Any, Dict

from .contracts import IntentJson
from .utils import extract_location, extract_number, normalize_text


def _detect_device_type(raw: str) -> str | None:
    if "插座" in raw:
        return "插座"
    if "灯" in raw:
        return "灯"
    if "空调" in raw:
        return "空调"
    if "门锁" in raw or ("门" in raw and ("解锁" in raw or "开锁" in raw)):
        return "门锁"
    if "开关" in raw:
        return "开关"
    return None


class NluMain:
    def predict(self, text: str, context: Dict[str, Any] | None = None) -> IntentJson:
        raw = text.strip()
        normalized = normalize_text(raw)
        slots: Dict[str, Any] = {}

        location = extract_location(raw)
        if location:
            slots["location"] = location

        device_type = _detect_device_type(raw)
        if device_type:
            slots["device_type"] = device_type

        value = extract_number(raw)
        if value is not None:
            slots["value"] = value
            if "%" in raw:
                slots["value_unit"] = "%"
            if "度" in raw or "℃" in raw:
                slots["value_unit"] = "℃"

        if any(word in normalized for word in ("你好", "天气", "谢谢", "再见")):
            return IntentJson(intent="CHITCHAT", sub_intent="chitchat", slots=slots, confidence=0.55)

        if "备份" in raw:
            return IntentJson(intent="SYSTEM", sub_intent="backup", slots=slots, confidence=0.93)

        if "解锁" in raw or "开锁" in raw:
            slots.setdefault("device_type", "门锁")
            return IntentJson(intent="CONTROL", sub_intent="unlock", slots=slots, confidence=0.9)

        if "模式" in raw and ("打开" in raw or "开启" in raw):
            scene_name = raw.replace("打开", "").replace("开启", "").replace("模式", "").strip()
            if scene_name:
                slots["scene_name"] = f"{scene_name}模式"
            return IntentJson(intent="SCENE", sub_intent="activate_scene", slots=slots, confidence=0.88)

        if any(word in raw for word in ("亮度", "调到", "调成", "调亮", "调暗", "%")) and slots.get("device_type") == "灯":
            slots["attribute"] = "亮度"
            confidence = 0.94 if "value" in slots else 0.72
            return IntentJson(intent="CONTROL", sub_intent="adjust_brightness", slots=slots, confidence=confidence)

        if slots.get("device_type") == "空调" and ("温度" in raw or "调到" in raw or "调低" in raw or "调高" in raw):
            slots["attribute"] = "温度"
            confidence = 0.9 if "value" in slots else 0.7
            return IntentJson(intent="CONTROL", sub_intent="set_temperature", slots=slots, confidence=confidence)

        if any(k in raw for k in ("打开", "开启", "关掉", "关闭", "关上")) and "device_type" in slots:
            if any(k in raw for k in ("关掉", "关闭", "关上")):
                return IntentJson(intent="CONTROL", sub_intent="power_off", slots=slots, confidence=0.9)
            return IntentJson(intent="CONTROL", sub_intent="power_on", slots=slots, confidence=0.9)

        if any(word in raw for word in ("多少", "状态", "几度", "查询")):
            return IntentJson(intent="QUERY", sub_intent="query_status", slots=slots, confidence=0.8)

        return IntentJson(intent="CHITCHAT", sub_intent="unknown", slots=slots, confidence=0.45)

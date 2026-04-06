from __future__ import annotations

from typing import Any, Dict

from .contracts import IntentJson
from .debug_log import compact, get_logger
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


class NluFallback:
    """兜底解析器：保持结构化输出，保证 100% 可解析。"""

    def __init__(self) -> None:
        self._logger = get_logger("nlu_fallback_rule")

    def _emit(self, raw: str, result: IntentJson) -> IntentJson:
        self._logger.debug(
            "predict text=%s intent=%s/%s conf=%.3f slots=%s",
            raw,
            result.intent,
            result.sub_intent,
            float(result.confidence),
            compact(result.slots),
        )
        return result

    def predict(self, text: str, context: Dict[str, Any] | None = None) -> IntentJson:
        raw = text.strip()
        normalized = normalize_text(raw)
        context = context or {}

        slots: Dict[str, Any] = {}

        location = extract_location(raw)
        if location:
            slots["location"] = location
        elif context.get("last_location"):
            slots["location"] = context["last_location"]

        device_type = _detect_device_type(raw)
        if device_type:
            slots["device_type"] = device_type
        elif any(word in raw for word in ("它", "这个", "那个")) and context.get("last_device_type"):
            slots["device_type"] = context["last_device_type"]

        value = extract_number(raw)
        if value is not None:
            slots["value"] = value
            if "%" in raw:
                slots["value_unit"] = "%"
            if "度" in raw or "℃" in raw:
                slots["value_unit"] = "℃"

        if "备份" in raw:
            return self._emit(raw, IntentJson(intent="SYSTEM", sub_intent="backup", slots=slots, confidence=0.86))

        if "解锁" in raw or "开锁" in raw:
            slots.setdefault("device_type", "门锁")
            return self._emit(raw, IntentJson(intent="CONTROL", sub_intent="unlock", slots=slots, confidence=0.82))

        if any(word in raw for word in ("亮度", "调到", "调成", "调亮", "调暗", "%")) and slots.get("device_type") == "灯":
            slots["attribute"] = "亮度"
            conf = 0.84 if "value" in slots else 0.62
            return self._emit(
                raw,
                IntentJson(intent="CONTROL", sub_intent="adjust_brightness", slots=slots, confidence=conf),
            )

        if slots.get("device_type") == "空调" and any(w in raw for w in ("温度", "调到", "调低", "调高")):
            slots["attribute"] = "温度"
            conf = 0.82 if "value" in slots else 0.61
            return self._emit(
                raw,
                IntentJson(intent="CONTROL", sub_intent="set_temperature", slots=slots, confidence=conf),
            )

        if any(k in raw for k in ("打开", "开启", "关掉", "关闭", "关上")) and slots.get("device_type"):
            if any(k in raw for k in ("关掉", "关闭", "关上")):
                return self._emit(raw, IntentJson(intent="CONTROL", sub_intent="power_off", slots=slots, confidence=0.78))
            return self._emit(raw, IntentJson(intent="CONTROL", sub_intent="power_on", slots=slots, confidence=0.78))

        if any(word in normalized for word in ("天气", "你好", "谢谢", "讲笑话")):
            return self._emit(raw, IntentJson(intent="CHITCHAT", sub_intent="chitchat", slots=slots, confidence=0.74))

        # 明显指代但缺少上下文，需澄清
        if any(word in raw for word in ("它", "这个", "那个", "帮我弄一下")) and not slots.get("device_type"):
            return self._emit(
                raw,
                IntentJson(intent="CHITCHAT", sub_intent="clarify_needed", slots=slots, confidence=0.5),
            )

        return self._emit(raw, IntentJson(intent="CHITCHAT", sub_intent="unknown", slots=slots, confidence=0.58))

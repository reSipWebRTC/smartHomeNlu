"""nlu_main.py – 规则层适配器

将 SmartHomeRuleEngine 的 SemanticDecision 输出转换为 runtime 标准的 IntentJson，
保持 nlu_router.py 的调用接口不变。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .contracts import IntentJson
from .debug_log import get_logger
from .nlu_rule_engine import (
    SmartHomeRuleEngine,
    SemanticDecision,
    SemanticCommand,
    SlotValue,
    HotWordsConfig,
    create_default_hot_words,
    load_hot_words_from_file,
)

logger = get_logger("nlu_main_rule")

# ── 映射表 ──────────────────────────────────────────────────────

_INTENT_MAP = {
    "device_control": "CONTROL",
    "state_query": "QUERY",
    "scene_activate": "SCENE",
    "automation_create": "SYSTEM",
    "automation_cancel": "SYSTEM",
    "unknown": "CHITCHAT",
}

_CANONICAL_ACTION_TO_SUB_INTENT = {
    "打开": "power_on",
    "关闭": "power_off",
    "设置为": "set_temperature",
    "调高": "adjust_brightness",
    "调低": "adjust_brightness",
    "调亮": "adjust_brightness",
    "调暗": "adjust_brightness",
    "移动到": "power_on",
}

_PARAM_DISPLAY = {
    "temperature": "温度",
    "brightness": "亮度",
    "color": "颜色",
    "speed": "风速",
    "ratio": "开合",
    "level": "档位",
}


def _sv_normalized(sv: Optional[SlotValue]) -> str:
    """安全取 SlotValue.normalized。"""
    if sv is None:
        return ""
    return sv.normalized or ""


def _sv_raw(sv: Optional[SlotValue]) -> str:
    """安全取 SlotValue.raw。"""
    if sv is None:
        return ""
    return sv.raw or ""


# ── SemanticCommand → sub_intent 推断 ────────────────────────────

def _infer_sub_intent(cmd: SemanticCommand) -> str:
    intent = cmd.intent or ""

    # 场景 / 查询 / 自动化 直接映射
    if intent == "scene_activate":
        return "activate_scene"
    if intent == "state_query":
        return "query_status"
    if intent in ("automation_create", "automation_cancel"):
        return "backup"

    # 从 action.normalized 映射
    action = _sv_normalized(cmd.action)
    if action in _CANONICAL_ACTION_TO_SUB_INTENT:
        sub = _CANONICAL_ACTION_TO_SUB_INTENT[action]
        # 区分温度 vs 亮度
        param = _sv_normalized(cmd.parameter)
        unit = _sv_normalized(cmd.unit)
        if sub == "set_temperature":
            if param == "brightness" or unit == "%":
                return "adjust_brightness"
            return "set_temperature"
        if sub == "adjust_brightness":
            if param == "temperature" or unit in ("度", "℃"):
                return "set_temperature"
            return "adjust_brightness"
        return sub

    # 有设备无动作 → 开
    if _sv_normalized(cmd.device):
        return "power_on"

    return "unknown"


# ── SemanticCommand → slots 提取 ─────────────────────────────────

def _extract_slots(cmd: SemanticCommand) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}

    location = _sv_normalized(cmd.location)
    if location:
        slots["location"] = location

    device = _sv_normalized(cmd.device)
    if device:
        # 场景激活时 device 槽位放的是场景名
        if cmd.intent == "scene_activate":
            slots["scene_name"] = device
        else:
            slots["device_type"] = device

    parameter = _sv_normalized(cmd.parameter)
    if parameter:
        slots["attribute"] = _PARAM_DISPLAY.get(parameter, parameter)

    value_raw = _sv_raw(cmd.value)
    if value_raw:
        try:
            slots["value"] = float(value_raw) if "." in str(value_raw) else int(value_raw)
        except (ValueError, TypeError):
            slots["value"] = value_raw

    unit = _sv_normalized(cmd.unit)
    if unit:
        if unit in ("℃", "度"):
            slots["value_unit"] = "℃"
        elif unit == "%":
            slots["value_unit"] = "%"
        else:
            slots["value_unit"] = unit

    return slots


# ── SemanticDecision → IntentJson ────────────────────────────────

def _single_cmd_to_intent(cmd: SemanticCommand) -> Dict[str, Any]:
    """Convert a single SemanticCommand to an intent dict (for multi_commands)."""
    return {
        "intent": _INTENT_MAP.get(cmd.intent, "CONTROL"),
        "sub_intent": _infer_sub_intent(cmd),
        "slots": _extract_slots(cmd),
        "confidence": max(0.0, min(1.0, cmd.confidence)),
    }


def _decision_to_intent_json(decision: SemanticDecision) -> IntentJson:
    if not decision.commands:
        # 无命令命中
        if decision.implicit_signals:
            return IntentJson(
                intent="SCENE",
                sub_intent="activate_scene",
                slots={},
                confidence=max(0.0, min(1.0, decision.overall_confidence)),
            )
        return IntentJson(
            intent="CHITCHAT",
            sub_intent="unknown",
            slots={},
            confidence=max(0.0, min(1.0, decision.overall_confidence)),
        )

    primary = decision.commands[0]
    intent_str = _INTENT_MAP.get(primary.intent, "CONTROL")
    sub_intent = _infer_sub_intent(primary)
    slots = _extract_slots(primary)

    # 多命令时从后续命令补充缺失槽位，同时构建 multi_commands 列表
    multi_commands: list[Dict[str, Any]] | None = None
    if len(decision.commands) > 1:
        multi_commands = [_single_cmd_to_intent(primary)]
        for extra_cmd in decision.commands[1:]:
            extra_slots = _extract_slots(extra_cmd)
            for key in ("location", "device_type", "scene_name"):
                if key not in slots and key in extra_slots:
                    slots.setdefault(key, extra_slots[key])
            multi_commands.append(_single_cmd_to_intent(extra_cmd))

    confidence = max(0.0, min(1.0, max(primary.confidence, decision.overall_confidence)))
    return IntentJson(
        intent=intent_str,
        sub_intent=sub_intent,
        slots=slots,
        confidence=confidence,
        multi_commands=multi_commands,
    )


# ── NluMain 适配器类 ──────────────────────────────────────────────

def _load_hot_words_config() -> HotWordsConfig:
    """尝试从 hot_words_config.json 加载，失败则回退默认。"""
    config_candidates = [
        Path(__file__).resolve().parent.parent / "hot_words_config.json",
        Path(__file__).resolve().parent / "hot_words_config.json",
    ]
    for path in config_candidates:
        if path.exists():
            logger.info("Loading hot words from %s", path)
            return load_hot_words_from_file(str(path))
    logger.info("hot_words_config.json not found, using default config")
    return create_default_hot_words()


class NluMain:
    """规则层适配器：SmartHomeRuleEngine → IntentJson"""

    def __init__(self) -> None:
        hot_words = _load_hot_words_config()
        self._engine = SmartHomeRuleEngine(hot_words)
        self._logger = logger

    def predict(self, text: str, context: Dict[str, Any] | None = None) -> IntentJson:
        raw = text.strip()
        if not raw:
            return IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.0)

        parse_result = self._engine.parse(raw)
        decision = self._engine.parse_semantic(
            raw,
            parse_result=parse_result,
            source="rule",
        )
        intent_json = _decision_to_intent_json(decision)

        self._logger.debug(
            "predict text=%s intent=%s/%s conf=%.3f slots=%s",
            raw,
            intent_json.intent,
            intent_json.sub_intent,
            float(intent_json.confidence),
            intent_json.slots,
        )
        return intent_json

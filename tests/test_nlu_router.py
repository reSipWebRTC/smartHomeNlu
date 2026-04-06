from __future__ import annotations

from runtime.contracts import IntentJson
from runtime.entity_resolver import EntityResolver
from runtime.event_bus import InMemoryEventBus
from runtime.nlu_router import NluRouter


class _StubModel:
    def __init__(self, result: IntentJson) -> None:
        self._result = result

    def predict(self, text: str, context: dict | None = None) -> IntentJson:
        return self._result


def test_router_prefers_rule_when_rule_is_reliable() -> None:
    router = NluRouter(InMemoryEventBus())
    router.nlu_rule = _StubModel(
        IntentJson(intent="CONTROL", sub_intent="power_on", slots={"device_type": "灯", "location": "客厅"}, confidence=0.95)
    )
    router.nlu_main = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.10)
    )
    router.nlu_fallback = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.10)
    )

    result = router.route(trace_id="trc_test_rule", text="打开客厅灯")

    assert result["route"] == "main"
    assert result["route_stage"] == "rule"
    assert result["model_version"] == "nlu-rule-v1"
    assert result["need_clarify"] is False


def test_router_uses_main_after_rule_failure() -> None:
    router = NluRouter(InMemoryEventBus())
    router.nlu_rule = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.45)
    )
    router.nlu_main = _StubModel(
        IntentJson(intent="CONTROL", sub_intent="power_off", slots={"device_type": "开关"}, confidence=0.86)
    )
    router.main_model_version = "nlu-main-onnx-v1"
    router.nlu_fallback = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.10)
    )

    result = router.route(trace_id="trc_test_main", text="关闭开关")

    assert result["route"] == "main"
    assert result["route_stage"] == "tinybert"
    assert result["model_version"] == "nlu-main-onnx-v1"
    assert result["need_clarify"] is False


def test_router_uses_fallback_when_main_missing_required_slots() -> None:
    router = NluRouter(InMemoryEventBus())
    router.nlu_rule = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.45)
    )
    router.nlu_main = _StubModel(
        IntentJson(intent="CONTROL", sub_intent="power_on", slots={}, confidence=0.99)
    )
    router.main_model_version = "nlu-main-onnx-v1"
    router.nlu_fallback = _StubModel(
        IntentJson(intent="CONTROL", sub_intent="power_on", slots={"device_type": "灯", "location": "卧室"}, confidence=0.90)
    )
    router.fallback_model_version = "nlu-fallback-qwen-v1"

    result = router.route(trace_id="trc_test_qwen", text="打开卧室的灯")

    assert result["route"] == "fallback"
    assert result["route_stage"] == "qwen"
    assert result["model_version"] == "nlu-fallback-qwen-v1"
    assert result["need_clarify"] is False


def test_router_accepts_set_temperature_without_device_type() -> None:
    """set_temperature implies climate domain; device_type is not required."""
    router = NluRouter(InMemoryEventBus())
    router.nlu_rule = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.45)
    )
    router.nlu_main = _StubModel(
        IntentJson(intent="CONTROL", sub_intent="set_temperature", slots={"value": 25, "value_unit": "℃"}, confidence=0.85)
    )
    router.main_model_version = "nlu-main-onnx-v1"

    result = router.route(trace_id="trc_test_set_temp", text="设置室内温度为25度")

    assert result["route"] == "main"
    assert result["route_stage"] == "tinybert"
    assert result["need_clarify"] is False


def test_router_rejects_set_temperature_without_value() -> None:
    router = NluRouter(InMemoryEventBus())
    router.nlu_rule = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.45)
    )
    router.nlu_main = _StubModel(
        IntentJson(intent="CONTROL", sub_intent="set_temperature", slots={"location": "客厅"}, confidence=0.95)
    )
    router.main_model_version = "nlu-main-onnx-v1"
    router.nlu_fallback = _StubModel(
        IntentJson(intent="QUERY", sub_intent="query_status", slots={"location": "客厅", "device_type": "空调"}, confidence=0.9)
    )
    router.fallback_model_version = "nlu-fallback-qwen-v1"

    result = router.route(trace_id="trc_test_set_temp_missing_value", text="把客厅温度调一下")

    assert result["route"] == "fallback"
    assert result["route_stage"] == "qwen"
    assert result["model_version"] == "nlu-fallback-qwen-v1"


def test_router_escalates_rule_when_slots_conflict_with_power_intent() -> None:
    router = NluRouter(InMemoryEventBus())
    router.nlu_rule = _StubModel(
        IntentJson(
            intent="CONTROL",
            sub_intent="power_on",
            slots={"location": "客厅", "device_type": "灯", "value": 26, "value_unit": "℃"},
            confidence=0.95,
        )
    )
    router.nlu_main = _StubModel(
        IntentJson(
            intent="CONTROL",
            sub_intent="set_temperature",
            slots={"location": "小孩房间", "device_type": "空调", "value": 26, "value_unit": "℃"},
            confidence=0.9,
        )
    )
    router.main_model_version = "nlu-main-onnx-v1"
    router.nlu_fallback = _StubModel(
        IntentJson(intent="CHITCHAT", sub_intent="unknown", slots={}, confidence=0.1)
    )

    result = router.route(
        trace_id="trc_test_escalate_rule",
        text="打开客厅灯，并且把小孩房间温度调为26度",
    )

    assert result["route"] == "main"
    assert result["route_stage"] == "tinybert"
    assert result["model_version"] == "nlu-main-onnx-v1"


def test_entity_resolver_domain_only_fallback() -> None:
    """When sub_intent implies domain but no device_type, resolver returns
    top climate entities instead of empty list."""
    bus = InMemoryEventBus()
    entities = [
        {"entity_id": "climate.living_room_ac", "name": "客厅空调", "area": "客厅"},
        {"entity_id": "light.bedroom", "name": "卧室灯", "area": "卧室"},
        {"entity_id": "climate.bedroom_ac", "name": "卧室空调", "area": "卧室"},
    ]
    resolver = EntityResolver(bus, entities=entities)

    # No device_type, vague location — domain_hint="climate" should still
    # find climate entities via domain_only fallback.
    candidates = resolver.resolve(
        trace_id="trc_test",
        slots={"value": 25, "value_unit": "℃", "location": "室"},
        domain_hint="climate",
        top_k=3,
    )

    entity_ids = [c.entity_id for c in candidates]
    assert "climate.living_room_ac" in entity_ids
    assert "climate.bedroom_ac" in entity_ids
    assert "light.bedroom" not in entity_ids

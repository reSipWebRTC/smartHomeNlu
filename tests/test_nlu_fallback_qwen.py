from __future__ import annotations

import json

from runtime.event_bus import InMemoryEventBus
from runtime.nlu_fallback_qwen import NluFallbackQwen
from runtime.nlu_router import NluRouter


def test_nlu_fallback_qwen_parses_structured_json(monkeypatch) -> None:
    model = NluFallbackQwen(max_retry=0)

    payload = {
        "intent": "QUERY",
        "sub_intent": "query_status",
        "slots": {"device_type": "空调", "location": "客厅"},
        "confidence": 0.66,
    }

    monkeypatch.setattr(
        model,
        "_request_remote",
        lambda text, context: {"message": {"content": json.dumps(payload, ensure_ascii=False)}},
    )

    intent = model.predict("客厅空调状态怎么样")

    assert intent.intent == "QUERY"
    assert intent.sub_intent == "query_status"
    assert intent.slots.get("device_type") == "空调"
    assert intent.slots.get("location") == "客厅"
    assert intent.confidence == 0.66


def test_nlu_fallback_qwen_falls_back_to_rule_parser_on_invalid_json(monkeypatch) -> None:
    model = NluFallbackQwen(max_retry=0)

    monkeypatch.setattr(
        model,
        "_request_remote",
        lambda text, context: {"message": {"content": "not-a-json"}},
    )

    intent = model.predict("关闭卧室开关")

    assert intent.intent == "CONTROL"
    assert intent.sub_intent == "power_off"
    assert intent.slots.get("device_type") == "开关"


def test_nlu_fallback_qwen_infers_sub_intent_when_missing(monkeypatch) -> None:
    model = NluFallbackQwen(max_retry=0)

    payload = {
        "intent": "QUERY",
        "sub_intent": "",
        "slots": {"room_number": "二楼"},
        "confidence": 0.95,
    }

    monkeypatch.setattr(
        model,
        "_request_remote",
        lambda text, context: {"message": {"content": json.dumps(payload, ensure_ascii=False)}},
    )

    intent = model.predict("打开二楼的社等")

    assert intent.intent == "QUERY"
    assert intent.sub_intent == "query_status"
    assert intent.slots.get("room_number") == "二楼"


def test_nlu_router_uses_qwen_provider_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SMARTHOME_NLU_FALLBACK_PROVIDER", "qwen_remote")
    router = NluRouter(InMemoryEventBus())

    assert router.fallback_model_version == "nlu-fallback-qwen-v1"
    assert isinstance(router.nlu_fallback, NluFallbackQwen)

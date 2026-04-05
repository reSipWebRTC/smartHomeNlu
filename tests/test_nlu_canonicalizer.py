from __future__ import annotations

from runtime.contracts import IntentJson
from runtime.nlu_canonicalizer import canonicalize_intent


def test_canonicalize_temperature_style_payload() -> None:
    raw = IntentJson(
        intent="control",
        sub_intent="TEMPERATURE",
        slots={
            "device": "AC",
            "location": "室",
            "temperature": "26度",
        },
        confidence=1.2,
    )

    out = canonicalize_intent(raw)

    assert out.intent == "CONTROL"
    assert out.sub_intent == "set_temperature"
    assert out.slots.get("device_type") == "空调"
    assert out.slots.get("value") == 26
    assert out.slots.get("value_unit") == "℃"
    assert "location" not in out.slots
    assert out.confidence == 1.0


def test_canonicalize_power_off_alias() -> None:
    raw = IntentJson(
        intent="CONTROL",
        sub_intent="off",
        slots={"device": "smart plug"},
        confidence=0.7,
    )

    out = canonicalize_intent(raw)

    assert out.sub_intent == "power_off"
    assert out.slots.get("device_type") == "插座"


def test_canonicalize_query_infers_intent() -> None:
    raw = IntentJson(
        intent="",
        sub_intent="status",
        slots={"entity": "climate.living_room_ac"},
        confidence=0.5,
    )

    out = canonicalize_intent(raw)

    assert out.intent == "QUERY"
    assert out.sub_intent == "query_status"
    assert out.slots.get("entity_id") == "climate.living_room_ac"

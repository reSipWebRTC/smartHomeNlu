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


def test_canonicalize_phrase_like_sub_intent_and_location_alias() -> None:
    raw = IntentJson(
        intent="QUERY",
        sub_intent="打开二楼的灯",
        slots={"floor": "二楼"},
        confidence=0.95,
    )

    out = canonicalize_intent(raw)

    assert out.intent == "CONTROL"
    assert out.sub_intent == "power_on"
    assert out.slots.get("location") == "二楼"
    assert out.slots.get("device_type") == "灯"


def test_canonicalize_filters_noisy_device_type() -> None:
    raw = IntentJson(
        intent="CONTROL",
        sub_intent="power_on",
        slots={"device_type": "系统", "location": "客厅"},
        confidence=0.9,
    )

    out = canonicalize_intent(raw)

    assert out.sub_intent == "power_on"
    assert out.slots.get("location") == "客厅"
    assert "device_type" not in out.slots


def test_canonicalize_repairs_noncanonical_sub_intent_by_frame() -> None:
    raw = IntentJson(
        intent="QUERY",
        sub_intent="control",
        slots={"room_number": "二楼"},
        confidence=0.95,
    )

    out = canonicalize_intent(raw)

    assert out.intent == "QUERY"
    assert out.sub_intent == "query_status"
    assert out.slots.get("location") == "二楼"


def test_canonicalize_location_alias_child_room() -> None:
    raw = IntentJson(
        intent="CONTROL",
        sub_intent="set_temperature",
        slots={"location": "孩房", "value": "26度"},
        confidence=0.9,
    )

    out = canonicalize_intent(raw)

    assert out.sub_intent == "set_temperature"
    assert out.slots.get("location") == "小孩房"
    assert out.slots.get("value") == 26
    assert out.slots.get("value_unit") == "℃"
    assert out.slots.get("device_type") == "空调"


def test_canonicalize_hot_words_action_and_device() -> None:
    raw = IntentJson(
        intent="CONTROL",
        sub_intent="点亮",
        slots={"device_type": "射灯", "location": "客厅"},
        confidence=0.93,
    )

    out = canonicalize_intent(raw)

    assert out.intent == "CONTROL"
    assert out.sub_intent == "power_on"
    assert out.slots.get("device_type") == "灯"


def test_canonicalize_hot_words_query_and_location() -> None:
    raw = IntentJson(
        intent="QUERY",
        sub_intent="查看",
        slots={"room_name": "主卫"},
        confidence=0.85,
    )

    out = canonicalize_intent(raw)

    assert out.intent == "QUERY"
    assert out.sub_intent == "query_status"
    assert out.slots.get("location") == "主卫"

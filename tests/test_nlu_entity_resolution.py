from __future__ import annotations

from runtime.entity_resolver import EntityResolver
from runtime.event_bus import InMemoryEventBus
from runtime.nlu_fallback import NluFallback
from runtime.nlu_main import NluMain
from runtime.utils import intent_to_domain


def test_entity_resolver_short_keyword_light_still_resolves() -> None:
    resolver = EntityResolver(
        InMemoryEventBus(),
        entities=[
            {"entity_id": "light.living_room_ceiling", "name": "客厅主照明", "area": "客厅"},
            {"entity_id": "switch.living_room_socket", "name": "客厅智能插座", "area": "客厅"},
        ],
    )

    candidates = resolver.resolve(trace_id="trc_resolve_001", slots={"device_type": "灯"}, top_k=3)

    assert candidates
    assert candidates[0].entity_id.startswith("light.")


def test_entity_resolver_outlet_maps_to_switch_domain() -> None:
    resolver = EntityResolver(
        InMemoryEventBus(),
        entities=[
            {"entity_id": "switch.living_room_socket", "name": "客厅智能排插", "area": "客厅"},
            {"entity_id": "light.living_room_main", "name": "客厅主灯", "area": "客厅"},
        ],
    )

    candidates = resolver.resolve(trace_id="trc_resolve_002", slots={"device_type": "插座", "location": "客厅"}, top_k=3)

    assert candidates
    assert candidates[0].entity_id == "switch.living_room_socket"


def test_nlu_main_supports_outlet_power_on() -> None:
    intent = NluMain().predict("打开客厅插座")

    assert intent.intent == "CONTROL"
    assert intent.sub_intent == "power_on"
    assert intent.slots.get("device_type") == "插座"


def test_nlu_fallback_supports_switch_power_off() -> None:
    intent = NluFallback().predict("关闭卧室开关")

    assert intent.intent == "CONTROL"
    assert intent.sub_intent == "power_off"
    assert intent.slots.get("device_type") == "开关"


def test_intent_to_domain_switch_for_outlet() -> None:
    domain = intent_to_domain("power_on", {"device_type": "插座"})
    assert domain == "switch"


def test_entity_resolver_hot_words_device_type_new_air_maps_to_climate() -> None:
    resolver = EntityResolver(
        InMemoryEventBus(),
        entities=[
            {"entity_id": "climate.living_room_fresh_air", "name": "客厅新风机", "area": "客厅"},
            {"entity_id": "light.living_room_main", "name": "客厅主灯", "area": "客厅"},
        ],
    )

    candidates = resolver.resolve(
        trace_id="trc_resolve_hot_words_001",
        slots={"device_type": "新风", "location": "客厅"},
        top_k=3,
    )

    assert candidates
    assert candidates[0].entity_id == "climate.living_room_fresh_air"

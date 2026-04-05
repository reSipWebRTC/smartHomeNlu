from __future__ import annotations

from runtime.api_gateway import SmartHomeRuntime
from runtime.entity_name_utils import build_entity_aliases, clean_entity_name
from runtime.entity_resolver import EntityResolver
from runtime.event_bus import InMemoryEventBus
from runtime.ha_gateway_adapter import HaGatewayAdapter


def test_clean_entity_name_removes_none_token() -> None:
    assert clean_entity_name("TYZXl鹊起 延长线插座 None", "switch.demo") == "TYZXl鹊起 延长线插座"
    assert clean_entity_name("None", "switch.fallback") == "switch.fallback"


def test_build_aliases_contains_device_terms() -> None:
    aliases = build_entity_aliases(
        name="TYZXl鹊起 延长线插座",
        entity_id="switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none_2",
        area="客厅",
        device_type_terms={"插座": ("插座", "排插", "插排", "插线板", "延长线")},
    )
    assert "延长线插座" in aliases
    assert "插座" in aliases


def test_entity_resolver_supports_weird_socket_name() -> None:
    resolver = EntityResolver(
        InMemoryEventBus(),
        entities=[
            {
                "entity_id": "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none",
                "name": "TYZXl鹊起 延长线插座 None",
                "area": "客厅",
            },
            {
                "entity_id": "light.living_room_main",
                "name": "客厅主灯",
                "area": "客厅",
            },
        ],
    )

    candidates = resolver.resolve(trace_id="trc_resolve_alias_001", slots={"device_type": "插座", "location": "客厅"}, top_k=3)

    assert candidates
    assert candidates[0].entity_id.startswith("switch.")
    assert "延长线插座" in resolver.entities[0].get("aliases", [])


def test_entities_api_disambiguates_same_name_routes() -> None:
    adapter = HaGatewayAdapter(
        entities=[
            {"entity_id": "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none", "name": "TYZXl鹊起 延长线插座 None", "area": ""},
            {"entity_id": "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none_2", "name": "TYZXl鹊起 延长线插座 None", "area": ""},
        ],
    )
    runtime = SmartHomeRuntime(redis_client=None, adapter=adapter)
    resp = runtime.get_api_v1_entities(limit=20, hide_default=False, headers={})
    items = list(resp["data"]["items"])

    assert len(items) == 2
    names = [str(item.get("name", "")) for item in items]
    assert all("None" not in name for name in names)
    assert any("第1路" in name for name in names)
    assert any("第2路" in name for name in names)
    assert all(isinstance(item.get("aliases"), list) for item in items)


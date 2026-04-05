from __future__ import annotations

import json

from runtime.api_gateway import SmartHomeRuntime
from runtime.entity_alias_store import EntityAliasStore
from runtime.ha_gateway_adapter import HaGatewayAdapter


def test_alias_store_apply_name_and_alias_override(tmp_path) -> None:
    alias_file = tmp_path / "entity_aliases.json"
    alias_file.write_text(
        json.dumps(
            {
                "entity_overrides": {
                    "switch.demo_socket": {
                        "name": "客厅排插",
                        "aliases": ["客厅插座一号", "一号插座"],
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    store = EntityAliasStore(path=str(alias_file))
    out = store.apply(
        {
            "entity_id": "switch.demo_socket",
            "name": "Demo Socket None",
            "area": "客厅",
            "aliases": ["旧别名"],
        }
    )

    assert out["name"] == "客厅排插"
    assert "一号插座" in out["aliases"]
    assert "旧别名" in out["aliases"]


def test_runtime_entities_api_applies_persistent_alias_file(monkeypatch, tmp_path) -> None:
    alias_file = tmp_path / "entity_aliases.json"
    alias_file.write_text(
        json.dumps(
            {
                "entity_overrides": {
                    "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none": {
                        "name": "客厅排插",
                        "aliases": ["客厅插座一号"],
                    },
                    "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none_2": {
                        "name": "客厅排插",
                        "aliases": ["客厅插座二号"],
                    },
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SMARTHOME_ENTITY_ALIAS_FILE", str(alias_file))

    adapter = HaGatewayAdapter(
        entities=[
            {
                "entity_id": "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none",
                "name": "TYZXl鹊起 延长线插座 None",
                "area": "",
            },
            {
                "entity_id": "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none_2",
                "name": "TYZXl鹊起 延长线插座 None",
                "area": "",
            },
        ]
    )

    runtime = SmartHomeRuntime(redis_client=None, adapter=adapter)
    resp = runtime.get_api_v1_entities(limit=20, hide_default=False, headers={})
    items = list(resp["data"]["items"])

    assert len(items) == 2
    names = [str(item.get("name", "")) for item in items]
    assert any("客厅排插 第1路" == name for name in names)
    assert any("客厅排插 第2路" == name for name in names)
    alias_text = " ".join(" ".join(item.get("aliases", [])) for item in items)
    assert "客厅插座一号" in alias_text
    assert "客厅插座二号" in alias_text


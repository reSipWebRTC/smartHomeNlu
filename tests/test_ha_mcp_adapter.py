from __future__ import annotations

from typing import Any, Dict, List

import pytest

from runtime import SmartHomeRuntime
from runtime.ha_mcp_adapter import HaMcpAdapter


class StaticRemoteRunner:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload

    def __call__(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self.payload)


class FakeRemoteHaMcp:
    def __init__(self, *, entities: List[Dict[str, Any]] | None = None, timeout_on_service: bool = False) -> None:
        self.entities: Dict[str, Dict[str, Any]] = {
            item["entity_id"]: dict(item)
            for item in (
                entities
                or [
                    {
                        "entity_id": "light.living_room_main",
                        "name": "客厅主灯",
                        "area": "客厅",
                        "state": "off",
                    },
                    {
                        "entity_id": "climate.living_room_ac",
                        "name": "客厅空调",
                        "area": "客厅",
                        "state": "off",
                    },
                ]
            )
        }
        self.timeout_on_service = timeout_on_service
        self.search_calls: List[Dict[str, Any]] = []
        self.service_calls: List[Dict[str, Any]] = []

    def __call__(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "ha_search_entities":
            query = str(params.get("query", "")).strip()
            domain = str(params.get("domain_filter") or "")
            limit = int(params.get("limit", 10))
            self.search_calls.append(dict(params))

            rows: List[Dict[str, Any]] = []
            for entity in self.entities.values():
                entity_id = entity["entity_id"]
                if domain and not entity_id.startswith(f"{domain}."):
                    continue
                haystack = f"{entity.get('name', '')}{entity.get('area', '')}{entity_id}"
                score = 1.0 if query and query in haystack else 0.8
                rows.append(
                    {
                        "entity_id": entity_id,
                        "friendly_name": entity.get("name", entity_id),
                        "area": entity.get("area", ""),
                        "state": entity.get("state", "unknown"),
                        "score": score,
                    }
                )

            return {
                "data": {
                    "success": True,
                    "results": rows[:limit],
                }
            }

        if tool_name == "ha_get_entity":
            entity_id = str(params.get("entity_id", ""))
            entity = self.entities.get(entity_id)
            if not entity:
                return {"data": {"success": False, "error": "Entity not found"}}
            return {
                "data": {
                    "success": True,
                    "entity_entry": {
                        "entity_id": entity_id,
                        "name": entity.get("name", entity_id),
                        "area_id": entity.get("area", ""),
                        "state": entity.get("state", "unknown"),
                    },
                }
            }

        if tool_name == "ha_call_service":
            if self.timeout_on_service:
                raise TimeoutError("simulated timeout")

            entity_id = str(params.get("entity_id", ""))
            entity = self.entities.get(entity_id)
            if not entity:
                return {"data": {"success": False, "error": "Entity not found"}}

            domain = str(params.get("domain", ""))
            service = str(params.get("service", ""))
            self.service_calls.append(dict(params))

            if domain == "light" and service == "turn_on":
                entity["state"] = "on"
            elif domain == "light" and service == "turn_off":
                entity["state"] = "off"
            elif domain == "climate" and service == "set_temperature":
                entity["state"] = "on"

            return {
                "data": {
                    "success": True,
                    "entity_id": entity_id,
                    "verified_state": entity.get("state", "unknown"),
                    "message": "ok",
                }
            }

        return {"data": {"success": False, "error": "Unsupported tool"}}


class ProxyOnlySearchRunner:
    def __init__(self) -> None:
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    def __call__(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((tool_name, dict(params)))
        if tool_name == "ha_search_entities":
            return {
                "data": {
                    "success": False,
                    "error": {
                        "code": "RESOURCE_NOT_FOUND",
                        "message": "Tool 'ha_search_entities' not found. Use ha_search_tools to discover available tools.",
                    },
                }
            }
        if tool_name == "ha_call_read_tool":
            if params.get("name") != "ha_search_entities":
                return {"data": {"success": False, "error": "bad proxy payload"}}
            return {
                "data": {
                    "success": True,
                    "results": [
                        {
                            "entity_id": "light.living_room_main",
                            "friendly_name": "客厅主灯",
                            "area": "客厅",
                            "state": "off",
                            "score": 1.0,
                        }
                    ],
                }
            }
        return {"data": {"success": False, "error": "unsupported"}}


@pytest.mark.parametrize(
    "payload, expected_code, expected_status",
    [
        (
            {
                "data": {
                    "success": False,
                    "error": {
                        "code": "TIMEOUT_OPERATION",
                        "message": "operation timeout",
                    },
                }
            },
            "UPSTREAM_TIMEOUT",
            504,
        ),
        (
            {
                "success": False,
                "error_code": "AUTH_INSUFFICIENT_PERMISSIONS",
                "message": "permission denied",
            },
            "FORBIDDEN",
            403,
        ),
        (
            {
                "data": {
                    "success": False,
                    "error": {
                        "code": "VALIDATION_INVALID_PARAMETER",
                        "message": "invalid parameter",
                    },
                }
            },
            "BAD_REQUEST",
            400,
        ),
    ],
)
def test_remote_error_mapping_via_tool_call(
    payload: Dict[str, Any],
    expected_code: str,
    expected_status: int,
) -> None:
    adapter = HaMcpAdapter(
        mcp_url="http://fake-ha-mcp.local/mcp",
        remote_tool_runner=StaticRemoteRunner(payload),
    )

    resp = adapter.tool_call(
        "ha_call_service",
        {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.demo",
            "data": {},
        },
    )

    assert resp["success"] is False
    assert resp["error_code"] == expected_code
    assert resp["status_code"] == expected_status


def test_remote_search_and_control_flow() -> None:
    remote = FakeRemoteHaMcp()
    adapter = HaMcpAdapter(mcp_url="http://fake-ha-mcp.local/mcp", remote_tool_runner=remote)

    entities = adapter.search_entities(query="客厅灯", domain="light", limit=3)
    assert entities
    assert entities[0]["entity_id"].startswith("light.")

    result = adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id=entities[0]["entity_id"],
        params={"brightness_pct": 60},
    )
    assert result["success"] is True
    assert result["status_code"] == 200
    assert adapter.service_call_count == 1
    assert remote.service_calls


def test_runtime_can_use_mcp_adapter() -> None:
    remote = FakeRemoteHaMcp()
    runtime = SmartHomeRuntime(adapter=HaMcpAdapter(mcp_url="http://fake-ha-mcp.local/mcp", remote_tool_runner=remote))

    resp = runtime.post_api_v1_command(
        {
            "session_id": "sess_mcp_001",
            "user_id": "usr_mcp_001",
            "text": "把客厅灯调到60%",
        }
    )

    assert resp["code"] == "OK"
    assert resp["data"]["status"] == "ok"


def test_mcp_url_normalization_adds_default_mcp_path() -> None:
    adapter = HaMcpAdapter(mcp_url="http://127.0.0.1:8086")
    assert adapter._mcp_url == "http://127.0.0.1:8086/mcp"

    adapter_with_trailing = HaMcpAdapter(mcp_url="http://127.0.0.1:8086/mcp/")
    assert adapter_with_trailing._mcp_url == "http://127.0.0.1:8086/mcp"


def test_search_entities_can_fallback_to_proxy_tool() -> None:
    remote = ProxyOnlySearchRunner()
    adapter = HaMcpAdapter(
        mcp_url="http://fake-ha-mcp.local/mcp",
        remote_tool_runner=remote,
    )

    entities = adapter.search_entities(query="客厅灯", domain="light", limit=3)

    assert entities
    assert entities[0]["entity_id"] == "light.living_room_main"
    assert [item[0] for item in remote.calls] == ["ha_search_entities", "ha_call_read_tool"]


def test_remote_call_retries_once_on_timeout() -> None:
    adapter = HaMcpAdapter(mcp_url="http://fake-ha-mcp.local/mcp", timeout_retries=1)
    calls = {"count": 0}

    def fake_invoke(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"success": False, "error_code": "UPSTREAM_TIMEOUT", "status_code": 504}
        return {
            "data": {
                "success": True,
                "results": [
                    {
                        "entity_id": "light.living_room_main",
                        "friendly_name": "客厅主灯",
                        "area": "客厅",
                        "state": "off",
                        "score": 1.0,
                    }
                ],
            }
        }

    adapter._invoke_remote_tool = fake_invoke  # type: ignore[method-assign]
    entities = adapter.search_entities(query="客厅灯", domain="light", limit=3)

    assert entities
    assert calls["count"] == 2

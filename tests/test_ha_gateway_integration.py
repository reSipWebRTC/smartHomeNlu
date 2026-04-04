from __future__ import annotations

from typing import Any, Dict, List

from runtime import SmartHomeRuntime
from runtime.ha_gateway_adapter import HaGatewayAdapter


class FakeGatewayRunner:
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
                        "attributes": {"friendly_name": "客厅主灯"},
                    },
                    {
                        "entity_id": "climate.living_room_ac",
                        "name": "客厅空调",
                        "area": "客厅",
                        "state": "off",
                        "attributes": {"friendly_name": "客厅空调"},
                    },
                    {
                        "entity_id": "lock.front_door",
                        "name": "前门门锁",
                        "area": "玄关",
                        "state": "locked",
                        "attributes": {"friendly_name": "前门门锁"},
                    },
                ]
            )
        }
        self.timeout_on_service = timeout_on_service
        self.call_service_calls: List[Dict[str, Any]] = []

    def __call__(self, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if message_type == "discover":
            devices = []
            for entity in self.entities.values():
                devices.append(
                    {
                        "entity_id": entity["entity_id"],
                        "name": entity.get("name", entity["entity_id"]),
                        "area": entity.get("area", ""),
                        "state": entity.get("state", "unknown"),
                        "attributes": dict(entity.get("attributes", {})),
                    }
                )
            return {"success": True, "data": {"devices": devices}}

        if message_type == "get_state":
            entity_id = str(payload.get("entity_id", ""))
            entity = self.entities.get(entity_id)
            if not entity:
                return {"success": False, "error": "Entity not found"}

            return {
                "success": True,
                "data": {
                    "state": {
                        "entity_id": entity_id,
                        "state": entity.get("state", "unknown"),
                        "attributes": {
                            **dict(entity.get("attributes", {})),
                            "friendly_name": entity.get("name", entity_id),
                        },
                    }
                },
            }

        if message_type == "call_service":
            if self.timeout_on_service:
                raise TimeoutError("simulated timeout")

            domain = str(payload.get("domain", ""))
            service = str(payload.get("service", ""))
            target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
            entity_id = str(target.get("entity_id", ""))
            self.call_service_calls.append(
                {
                    "domain": domain,
                    "service": service,
                    "entity_id": entity_id,
                    "payload": dict(payload),
                }
            )

            if domain == "backup" and service == "create":
                return {"success": True, "data": {"accepted": True}}

            entity = self.entities.get(entity_id)
            if not entity:
                return {"success": False, "error": "Entity not found"}

            if domain == "light" and service == "turn_on":
                entity["state"] = "on"
            elif domain == "light" and service == "turn_off":
                entity["state"] = "off"
            elif domain == "switch" and service == "turn_on":
                entity["state"] = "on"
            elif domain == "switch" and service == "turn_off":
                entity["state"] = "off"
            elif domain == "climate" and service == "set_temperature":
                entity["state"] = "on"
            elif domain == "lock" and service == "unlock":
                entity["state"] = "unlocked"

            return {"success": True, "data": {"accepted": True}}

        return {"success": False, "error": f"unsupported message type: {message_type}"}


def _runtime(remote: FakeGatewayRunner) -> SmartHomeRuntime:
    adapter = HaGatewayAdapter(gateway_url="ws://fake-ha-gateway/ws", gateway_runner=remote)
    return SmartHomeRuntime(adapter=adapter)


def test_gateway_control_success() -> None:
    runtime = _runtime(FakeGatewayRunner())
    resp = runtime.post_api_v1_command(
        {
            "session_id": "sess_gw_001",
            "user_id": "usr_gw_001",
            "text": "把客厅灯调到60%",
        }
    )

    assert resp["code"] == "OK"
    assert resp["data"]["status"] == "ok"
    assert runtime.adapter.service_call_count == 1


def test_gateway_query_success() -> None:
    runtime = _runtime(FakeGatewayRunner())
    resp = runtime.post_api_v1_command(
        {
            "session_id": "sess_gw_002",
            "user_id": "usr_gw_002",
            "text": "查询客厅空调状态",
        }
    )

    assert resp["code"] == "OK"
    events = runtime.event_bus.events("evt.execution.result.v1")
    assert events[-1]["tool_name"] == "ha_get_entity"
    assert events[-1]["status"] == "success"


def test_gateway_unlock_confirm_flow() -> None:
    runtime = _runtime(FakeGatewayRunner())

    first = runtime.post_api_v1_command(
        {
            "session_id": "sess_gw_003",
            "user_id": "usr_gw_003",
            "user_role": "normal_user",
            "text": "把前门解锁",
        }
    )
    assert first["code"] == "POLICY_CONFIRM_REQUIRED"

    token = first["data"]["confirm_token"]
    second = runtime.post_api_v1_confirm({"confirm_token": token, "accept": True})

    assert second["code"] == "OK"
    assert runtime.adapter.service_call_count == 1


def test_gateway_entity_not_found() -> None:
    runtime = _runtime(
        FakeGatewayRunner(
            entities=[
                {
                    "entity_id": "light.living_room_main",
                    "name": "客厅主灯",
                    "area": "客厅",
                    "state": "off",
                    "attributes": {"friendly_name": "客厅主灯"},
                }
            ]
        )
    )

    resp = runtime.post_api_v1_command(
        {
            "session_id": "sess_gw_004",
            "user_id": "usr_gw_004",
            "text": "查询客厅空调状态",
        }
    )

    assert resp["code"] == "ENTITY_NOT_FOUND"


def test_gateway_upstream_timeout() -> None:
    runtime = _runtime(FakeGatewayRunner(timeout_on_service=True))

    resp = runtime.post_api_v1_command(
        {
            "session_id": "sess_gw_005",
            "user_id": "usr_gw_005",
            "text": "把客厅灯调到40%",
        }
    )

    assert resp["code"] == "UPSTREAM_TIMEOUT"
    assert resp["data"]["status"] == "failed"


def test_gateway_outlet_power_on_routes_to_switch_domain() -> None:
    remote = FakeGatewayRunner(
        entities=[
            {
                "entity_id": "switch.living_room_outlet",
                "name": "客厅智能插座",
                "area": "客厅",
                "state": "off",
                "attributes": {"friendly_name": "客厅智能插座"},
            }
        ]
    )
    runtime = _runtime(remote)

    resp = runtime.post_api_v1_command(
        {
            "session_id": "sess_gw_006",
            "user_id": "usr_gw_006",
            "text": "打开客厅插座",
        }
    )

    assert resp["code"] == "OK"
    assert remote.call_service_calls
    assert remote.call_service_calls[-1]["domain"] == "switch"
    assert remote.call_service_calls[-1]["service"] == "turn_on"

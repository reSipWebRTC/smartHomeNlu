from __future__ import annotations

from typing import Any, Dict, List

from runtime.ha_gateway_adapter import HaGatewayAdapter


class FakeGatewayRunner:
    def __init__(
        self,
        *,
        entities: List[Dict[str, Any]] | None = None,
        timeout_on_service: bool = False,
    ) -> None:
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
                ]
            )
        }
        self.timeout_on_service = timeout_on_service

    def __call__(self, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if message_type == "discover":
            devices = []
            for item in self.entities.values():
                devices.append(
                    {
                        "entity_id": item["entity_id"],
                        "name": item.get("name", item["entity_id"]),
                        "area": item.get("area", ""),
                        "state": item.get("state"),
                        "attributes": dict(item.get("attributes", {})),
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
                raise TimeoutError("simulated gateway timeout")

            domain = str(payload.get("domain", ""))
            service = str(payload.get("service", ""))
            target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
            entity_id = str(target.get("entity_id", ""))

            if domain == "backup" and service == "create":
                return {"success": True, "data": {"accepted": True}}

            entity = self.entities.get(entity_id)
            if not entity:
                return {"success": False, "error": "Entity not found"}

            if domain == "light" and service == "turn_on":
                entity["state"] = "on"
            elif domain == "light" and service == "turn_off":
                entity["state"] = "off"
            elif domain == "climate" and service == "set_temperature":
                entity["state"] = "on"
            elif domain == "lock" and service == "unlock":
                entity["state"] = "unlocked"

            return {"success": True, "data": {"accepted": True}}

        return {"success": False, "error": f"unsupported message type: {message_type}"}


class DelayedStateGatewayRunner(FakeGatewayRunner):
    def __init__(self, *, delay_reads: int = 2) -> None:
        super().__init__()
        self.delay_reads = max(0, int(delay_reads))
        self._pending: Dict[str, Dict[str, Any]] = {}

    def __call__(self, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if message_type == "call_service":
            domain = str(payload.get("domain", ""))
            service = str(payload.get("service", ""))
            target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
            entity_id = str(target.get("entity_id", ""))

            if domain == "light" and service in {"turn_on", "turn_off"} and entity_id in self.entities:
                self._pending[entity_id] = {
                    "state": "on" if service == "turn_on" else "off",
                    "remaining_reads": self.delay_reads,
                }
                return {"success": True, "data": {"accepted": True}}

        if message_type == "get_state":
            entity_id = str(payload.get("entity_id", ""))
            pending = self._pending.get(entity_id)
            if pending:
                remaining_reads = int(pending.get("remaining_reads", 0))
                if remaining_reads <= 0:
                    self.entities[entity_id]["state"] = pending["state"]
                    self._pending.pop(entity_id, None)
                else:
                    pending["remaining_reads"] = remaining_reads - 1

        return super().__call__(message_type, payload)


def test_gateway_search_entities() -> None:
    adapter = HaGatewayAdapter(
        gateway_url="ws://fake-ha-gateway/ws",
        gateway_runner=FakeGatewayRunner(),
    )

    rows = adapter.search_entities(query="客厅灯", domain="light", limit=3)

    assert rows
    assert rows[0]["entity_id"].startswith("light.")
    assert rows[0]["score"] >= 0.35


def test_gateway_call_service_and_get_state() -> None:
    adapter = HaGatewayAdapter(
        gateway_url="ws://fake-ha-gateway/ws",
        gateway_runner=FakeGatewayRunner(),
    )

    resp = adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id="light.living_room_main",
        params={"brightness_pct": 60},
    )

    assert resp["success"] is True
    assert resp["status_code"] == 200
    assert resp["state"] == "on"


def test_gateway_tool_call_get_entity_not_found() -> None:
    adapter = HaGatewayAdapter(
        gateway_url="ws://fake-ha-gateway/ws",
        gateway_runner=FakeGatewayRunner(),
    )

    resp = adapter.tool_call("ha_get_entity", {"entity_id": "light.missing_entity"})

    assert resp["success"] is False
    assert resp["error_code"] == "ENTITY_NOT_FOUND"
    assert resp["status_code"] == 404


def test_gateway_timeout_error_mapping() -> None:
    adapter = HaGatewayAdapter(
        gateway_url="ws://fake-ha-gateway/ws",
        gateway_runner=FakeGatewayRunner(timeout_on_service=True),
    )

    resp = adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id="light.living_room_main",
        params={},
    )

    assert resp["success"] is False
    assert resp["error_code"] == "UPSTREAM_TIMEOUT"
    assert resp["status_code"] == 504


def test_gateway_backup_tool_call() -> None:
    adapter = HaGatewayAdapter(
        gateway_url="ws://fake-ha-gateway/ws",
        gateway_runner=FakeGatewayRunner(),
    )

    resp = adapter.tool_call("ha_backup_create", {"name": "nightly"})

    assert resp["success"] is True
    assert resp["status_code"] == 200
    assert adapter.backup_call_count == 1


def test_gateway_call_service_polls_until_desired_state() -> None:
    adapter = HaGatewayAdapter(
        gateway_url="ws://fake-ha-gateway/ws",
        gateway_runner=DelayedStateGatewayRunner(delay_reads=2),
        state_poll_timeout_sec=0.3,
        state_poll_interval_sec=0.01,
    )

    resp = adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id="light.living_room_main",
        params={},
    )

    assert resp["success"] is True
    assert resp["state"] == "on"
    assert resp["desired_state"] == "on"
    assert resp["applied"] is True


def test_gateway_call_service_reports_not_applied_when_timeout() -> None:
    adapter = HaGatewayAdapter(
        gateway_url="ws://fake-ha-gateway/ws",
        gateway_runner=DelayedStateGatewayRunner(delay_reads=100),
        state_poll_timeout_sec=0.03,
        state_poll_interval_sec=0.01,
    )

    resp = adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id="light.living_room_main",
        params={},
    )

    assert resp["success"] is True
    assert resp["state"] == "off"
    assert resp["desired_state"] == "on"
    assert resp["applied"] is False

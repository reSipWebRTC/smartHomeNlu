from __future__ import annotations

import os
import time
import uuid

import pytest

from runtime import SmartHomeRuntime
from runtime.contracts import IntentJson
from runtime.ha_gateway_adapter import HaGatewayAdapter


LIVE_HA_GATEWAY_ENABLED = os.getenv("LIVE_HA_GATEWAY_TEST") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE_HA_GATEWAY_ENABLED,
    reason="Set LIVE_HA_GATEWAY_TEST=1 to run live ha_gateway smoke tests.",
)

DEFAULT_SWITCH_ENTITY_ID = "switch.tyzxlque_qi_yan_chang_xian_cha_zuo_none"


def _required_gateway_url() -> str:
    gateway_url = (os.getenv("SMARTHOME_HA_GATEWAY_URL") or "").strip()
    if not gateway_url:
        pytest.skip("SMARTHOME_HA_GATEWAY_URL is required for live ha_gateway smoke tests")
    return gateway_url


def _switch_entity_id() -> str:
    return (os.getenv("LIVE_HA_GATEWAY_SWITCH_ENTITY_ID") or "").strip() or DEFAULT_SWITCH_ENTITY_ID


def _runtime() -> tuple[SmartHomeRuntime, HaGatewayAdapter]:
    timeout_sec = float(os.getenv("SMARTHOME_HA_GATEWAY_TIMEOUT_SEC") or "8")
    adapter = HaGatewayAdapter(gateway_url=_required_gateway_url(), timeout_sec=timeout_sec)
    runtime = SmartHomeRuntime(adapter=adapter)
    return runtime, adapter


def _force_main_intent(runtime: SmartHomeRuntime, intent: IntentJson) -> None:
    runtime.router.nlu_main.predict = lambda _text, _context=None: intent  # type: ignore[assignment]


def _wait_state(adapter: HaGatewayAdapter, entity_id: str, expected_state: str, timeout_sec: float = 5.0) -> dict:
    expected = expected_state.lower()
    deadline = time.monotonic() + timeout_sec
    latest: dict = {}

    while time.monotonic() < deadline:
        latest = adapter.tool_call("ha_get_entity", {"entity_id": entity_id})
        if latest.get("success"):
            entity = latest.get("entity")
            if isinstance(entity, dict):
                current = str(entity.get("state", "")).lower()
                if current == expected:
                    return latest
        time.sleep(0.3)

    return latest


def test_live_gateway_runtime_switch_power_cycle() -> None:
    runtime, adapter = _runtime()
    entity_id = _switch_entity_id()

    state_probe = adapter.tool_call("ha_get_entity", {"entity_id": entity_id})
    if not state_probe.get("success"):
        pytest.skip(f"Entity not available: {entity_id}")

    _force_main_intent(
        runtime,
        IntentJson(
            intent="CONTROL",
            sub_intent="power_off",
            slots={"entity_id": entity_id, "device_type": "插座"},
            confidence=0.99,
        ),
    )
    off_resp = runtime.post_api_v1_command(
        {
            "session_id": f"live_gw_off_{uuid.uuid4().hex[:8]}",
            "user_id": "live_gateway_smoke",
            "text": "smoke gateway power off",
        }
    )
    assert off_resp["code"] == "OK"

    off_state = _wait_state(adapter, entity_id, "off")
    assert off_state.get("success") is True
    assert str(off_state["entity"]["state"]).lower() == "off"

    _force_main_intent(
        runtime,
        IntentJson(
            intent="CONTROL",
            sub_intent="power_on",
            slots={"entity_id": entity_id, "device_type": "插座"},
            confidence=0.99,
        ),
    )
    on_resp = runtime.post_api_v1_command(
        {
            "session_id": f"live_gw_on_{uuid.uuid4().hex[:8]}",
            "user_id": "live_gateway_smoke",
            "text": "smoke gateway power on",
        }
    )
    assert on_resp["code"] == "OK"

    on_state = _wait_state(adapter, entity_id, "on")
    assert on_state.get("success") is True
    assert str(on_state["entity"]["state"]).lower() == "on"

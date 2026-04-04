from __future__ import annotations

from runtime.api_gateway import SmartHomeRuntime
from runtime.ha_gateway_adapter import HaGatewayAdapter
from runtime.ha_mcp_adapter import HaMcpAdapter


def _clear_env(monkeypatch) -> None:
    for key in (
        "SMARTHOME_HA_CONTROL_MODE",
        "SMARTHOME_HA_GATEWAY_URL",
        "SMARTHOME_HA_GATEWAY_TIMEOUT_SEC",
        "SMARTHOME_HA_MCP_URL",
        "SMARTHOME_HA_MCP_TOKEN",
        "SMARTHOME_HA_MCP_TIMEOUT_SEC",
    ):
        monkeypatch.delenv(key, raising=False)


def test_auto_prefers_gateway_when_gateway_url_present(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMARTHOME_HA_GATEWAY_URL", "ws://fake-ha-gateway/ws")
    monkeypatch.setenv("SMARTHOME_HA_MCP_URL", "http://fake-ha-mcp.local/mcp")

    runtime = SmartHomeRuntime()

    assert isinstance(runtime.adapter, HaGatewayAdapter)
    assert runtime.adapter.mode == "ha_gateway"


def test_auto_uses_mcp_when_only_mcp_is_present(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMARTHOME_HA_MCP_URL", "http://fake-ha-mcp.local/mcp")

    runtime = SmartHomeRuntime()

    assert isinstance(runtime.adapter, HaMcpAdapter)
    assert runtime.adapter.mode == "ha_mcp"


def test_explicit_mode_can_force_mcp(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMARTHOME_HA_CONTROL_MODE", "ha_mcp")
    monkeypatch.setenv("SMARTHOME_HA_GATEWAY_URL", "ws://fake-ha-gateway/ws")

    runtime = SmartHomeRuntime()

    assert isinstance(runtime.adapter, HaMcpAdapter)

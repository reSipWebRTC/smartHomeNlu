from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import pytest


HA_GATEWAY_DIR = Path(__file__).resolve().parents[1] / "ha_gateway"
if str(HA_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(HA_GATEWAY_DIR))

from protocol.message import Message, MessageType  # noqa: E402
from protocol.websocket import GatewayWebSocketServer  # noqa: E402


@dataclass
class _GatewayCfg:
    host: str = "127.0.0.1"
    port: int = 0


@dataclass
class _Config:
    gateway: _GatewayCfg = field(default_factory=_GatewayCfg)


class _FakeHAWebSocket:
    def __init__(
        self,
        *,
        call_service_results: List[Any] | None = None,
        state_batches: List[List[Dict[str, Any]]] | None = None,
    ) -> None:
        self._call_service_results = list(call_service_results or [])
        self._state_batches = list(state_batches or [])
        self._last_states: List[Dict[str, Any]] = []
        self.call_service_calls: List[Dict[str, Any]] = []
        self.send_command_calls: List[Dict[str, Any]] = []

    async def call_service(
        self,
        *,
        domain: str,
        service: str,
        service_data: Dict[str, Any] | None = None,
        target: Dict[str, Any] | None = None,
        return_response: bool = False,
    ) -> Dict[str, Any]:
        self.call_service_calls.append(
            {
                "domain": domain,
                "service": service,
                "service_data": dict(service_data or {}),
                "target": dict(target or {}),
                "return_response": return_response,
            }
        )

        if self._call_service_results:
            result = self._call_service_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        return {"result": {"context": {"id": "ctx_default"}}}

    async def send_command(self, command_type: str, **kwargs: Any) -> Dict[str, Any]:
        self.send_command_calls.append({"command_type": command_type, "kwargs": kwargs})
        if self._state_batches:
            self._last_states = self._state_batches.pop(0)
        return {"type": "result", "success": True, "result": self._last_states}


@pytest.mark.asyncio
async def test_call_service_defaults_to_no_return_response() -> None:
    ha_ws = _FakeHAWebSocket(call_service_results=[{"result": {"context": {"id": "ctx_1"}}}])
    server = GatewayWebSocketServer(_Config(), ha_ws)

    sent: List[Message] = []

    async def _capture(_: str, msg: Message) -> None:
        sent.append(msg)

    server._send_to_client = _capture  # type: ignore[method-assign]

    message = Message(
        type=MessageType.CALL_SERVICE,
        id="msg_1",
        payload={
            "domain": "switch",
            "service": "turn_off",
            "target": {"entity_id": "switch.demo"},
        },
    )
    await server._handle_call_service("client_1", message)

    assert ha_ws.call_service_calls[0]["return_response"] is False
    assert sent[0].type == MessageType.RESPONSE
    assert sent[0].payload["success"] is True
    assert sent[0].payload["data"]["sent"] is True


@pytest.mark.asyncio
async def test_call_service_fallback_when_return_response_not_supported() -> None:
    ha_ws = _FakeHAWebSocket(
        call_service_results=[
            Exception(
                "Command failed: Validation error: "
                "service_does_not_support_response (code: service_validation_error)"
            ),
            {"result": {"context": {"id": "ctx_2"}}},
        ]
    )
    server = GatewayWebSocketServer(_Config(), ha_ws)

    sent: List[Message] = []

    async def _capture(_: str, msg: Message) -> None:
        sent.append(msg)

    server._send_to_client = _capture  # type: ignore[method-assign]

    message = Message(
        type=MessageType.CALL_SERVICE,
        id="msg_2",
        payload={
            "domain": "switch",
            "service": "turn_off",
            "target": {"entity_id": "switch.demo"},
            "return_response": True,
        },
    )
    await server._handle_call_service("client_1", message)

    assert len(ha_ws.call_service_calls) == 2
    assert ha_ws.call_service_calls[0]["return_response"] is True
    assert ha_ws.call_service_calls[1]["return_response"] is False
    assert sent[0].type == MessageType.RESPONSE
    assert sent[0].payload["success"] is True
    assert sent[0].payload["data"]["fallback_without_return_response"] is True


@pytest.mark.asyncio
async def test_set_state_waits_for_desired_state() -> None:
    ha_ws = _FakeHAWebSocket(
        call_service_results=[{"result": {"context": {"id": "ctx_3"}}}],
        state_batches=[
            [{"entity_id": "switch.demo", "state": "on"}],
            [{"entity_id": "switch.demo", "state": "off"}],
        ],
    )
    server = GatewayWebSocketServer(_Config(), ha_ws)

    sent: List[Message] = []

    async def _capture(_: str, msg: Message) -> None:
        sent.append(msg)

    server._send_to_client = _capture  # type: ignore[method-assign]

    message = Message(
        type=MessageType.SET_STATE,
        id="msg_3",
        payload={"entity_id": "switch.demo", "state": "off"},
    )
    await server._handle_set_state("client_1", message)

    assert ha_ws.call_service_calls[0]["service"] == "turn_off"
    assert sent[0].type == MessageType.RESPONSE
    assert sent[0].payload["success"] is True
    assert sent[0].payload["data"]["desired_state"] == "off"
    assert sent[0].payload["data"]["state"] == "off"
    assert sent[0].payload["data"]["applied"] is True

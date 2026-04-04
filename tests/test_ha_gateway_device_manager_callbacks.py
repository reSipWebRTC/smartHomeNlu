from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import List, Tuple

import pytest


HA_GATEWAY_DIR = Path(__file__).resolve().parents[1] / "ha_gateway"
if str(HA_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(HA_GATEWAY_DIR))

from config import Config  # noqa: E402
from device_manager import DeviceManager  # noqa: E402


@pytest.mark.asyncio
async def test_update_state_awaits_async_callback() -> None:
    manager = DeviceManager(Config())
    calls: List[Tuple[str, str]] = []

    async def on_state(entity_id: str, state) -> None:
        await asyncio.sleep(0)
        calls.append((entity_id, state.state))

    manager.add_state_callback(on_state)

    await manager.update_state(
        "switch.demo",
        {
            "state": "off",
            "attributes": {},
            "last_changed": None,
            "last_updated": None,
        },
    )

    await manager.update_state(
        "switch.demo",
        {
            "state": "on",
            "attributes": {},
            "last_changed": None,
            "last_updated": None,
        },
    )

    assert calls == [("switch.demo", "on")]


@pytest.mark.asyncio
async def test_update_state_awaits_coroutine_returned_by_sync_callback() -> None:
    manager = DeviceManager(Config())
    calls: List[Tuple[str, str]] = []

    def on_state(entity_id: str, state):
        async def _deferred() -> None:
            await asyncio.sleep(0)
            calls.append((entity_id, state.state))

        return _deferred()

    manager.add_state_callback(on_state)

    await manager.update_state(
        "switch.demo",
        {
            "state": "off",
            "attributes": {},
        },
    )

    await manager.update_state(
        "switch.demo",
        {
            "state": "on",
            "attributes": {},
        },
    )

    assert calls == [("switch.demo", "on")]

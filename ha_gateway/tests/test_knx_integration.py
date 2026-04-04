"""Tests for HA Gateway KNX Integration.

Tests cover:
- KNX Gateway connection
- Device registration to KNX
- Address mapping storage
- State synchronization to KNX
- Reverse mapping (KNX address to entity)
- Connection recovery
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import websockets

# Mock the config module before importing knx_integration
with patch('sys.modules', {'config': Mock()}):
    from knx_integration import KNXIntegration


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock()
    config.knx = Mock()
    config.knx.enabled = True
    config.knx.knx_gateway_url = "ws://localhost:8125/ws"
    config.knx.reconnect_interval = 1
    config.knx.max_retries = 3
    config.knx.request_timeout = 5
    config.performance = Mock()
    config.performance.batch_size = 10
    config.performance.batch_delay = 0.1
    return config


@pytest.fixture
def knx_integration(mock_config):
    """Create KNX Integration instance for testing."""
    with patch('knx_integration.websockets'):
        integration = KNXIntegration(mock_config)
        integration.message_counter = 0
        return integration


class TestKNXIntegrationInitialization:
    """Test KNX Integration initialization."""

    @pytest.mark.asyncio
    async def test_initialization(self, knx_integration):
        """Test integration initialization."""
        assert knx_integration.config is not None
        assert knx_integration.knx_gateway_url == "ws://localhost:8125/ws"
        assert knx_integration.connected is False
        assert knx_integration.device_mappings == {}
        assert knx_integration.entity_mappings == {}
        assert knx_integration.knx_to_entity == {}

    @pytest.mark.asyncio
    async def test_initialize_disabled(self, knx_integration):
        """Test initialization when KNX is disabled."""
        knx_integration.config.knx.enabled = False

        await knx_integration.initialize()

        # Should not attempt connection
        assert knx_integration.connected is False


class TestKNXGatewayConnection:
    """Test KNX Gateway connection handling."""

    @pytest.mark.asyncio
    async def test_connect_to_knx_gateway(self, knx_integration):
        """Test connecting to KNX Gateway."""
        mock_websocket = AsyncMock()
        mock_websocket.send = AsyncMock()

        with patch('knx_integration.websockets.connect', return_value=mock_websocket):
            await knx_integration.connect_to_knx_gateway()

            assert knx_integration.connected is True
            assert knx_integration.websocket == mock_websocket

            # Verify hello message was sent
            assert mock_websocket.send.called
            hello_msg = json.loads(mock_websocket.send.call_args.args[0])
            assert hello_msg["type"] == "hello"
            assert hello_msg["payload"]["role"] == "ha_gateway"

    @pytest.mark.asyncio
    async def test_connection_failure(self, knx_integration):
        """Test handling connection failure."""
        with patch('knx_integration.websockets.connect', side_effect=OSError("Connection refused")):
            await knx_integration.connect_to_knx_gateway()

            # Should not be connected after retries
            assert knx_integration.connected is False

    @pytest.mark.asyncio
    async def test_connection_timeout(self, knx_integration):
        """Test handling connection timeout."""
        with patch('knx_integration.websockets.connect', side_effect=asyncio.TimeoutError()):
            await knx_integration.connect_to_knx_gateway()

            assert knx_integration.connected is False


class TestDeviceRegistration:
    """Test device registration to KNX Gateway."""

    @pytest.mark.asyncio
    async def test_request_knx_address_single_entity(self, knx_integration):
        """Test requesting KNX address for device with single entity."""
        knx_integration.connected = True
        knx_integration.websocket = AsyncMock()
        knx_integration.websocket.send = AsyncMock()

        # Create a future for the response
        response_future = asyncio.Future()
        knx_integration.pending_responses["register_0"] = response_future

        device_info = {
            "name": "Living Room Light",
            "type": "light",
            "entities": [
                {
                    "entity_id": "light.living_room",
                    "domain": "light",
                    "name": "Living Room"
                }
            ]
        }

        # Set response to be returned
        response_data = {
            "type": "address_assigned",
            "id": "register_0_response",
            "payload": {
                "device_id": "device_001",
                "success": True,
                "entity_addresses": [
                    {
                        "entity_id": "light.living_room",
                        "entity_type": "light",
                        "physical_address": "1/1/1",
                        "group_addresses": {
                            "control": "1/1/1",
                            "status": "1/1/2",
                            "brightness": "1/1/3"
                        },
                        "dpt_types": {
                            "control": "DPT1.001",
                            "status": "DPT1.001",
                            "brightness": "DPT5.001"
                        }
                    }
                ]
            }
        }
        response_future.set_result(response_data)

        result = await knx_integration.request_knx_address("device_001", device_info)

        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_request_knx_address_multiple_entities(self, knx_integration):
        """Test requesting KNX address for device with multiple entities."""
        knx_integration.connected = True
        knx_integration.websocket = AsyncMock()
        knx_integration.websocket.send = AsyncMock()

        response_future = asyncio.Future()
        knx_integration.pending_responses["register_0"] = response_future

        device_info = {
            "name": "Multi-Light Device",
            "type": "light",
            "entities": [
                {"entity_id": "light.main", "domain": "light", "name": "Main"},
                {"entity_id": "light.aux", "domain": "light", "name": "Aux"},
                {"entity_id": "switch.power", "domain": "switch", "name": "Power"}
            ]
        }

        response_data = {
            "type": "address_assigned",
            "id": "register_0_response",
            "payload": {
                "device_id": "device_multi",
                "success": True,
                "entity_addresses": [
                    {
                        "entity_id": "light.main",
                        "entity_type": "light",
                        "physical_address": "1/1/1",
                        "group_addresses": {"control": "1/1/1"},
                        "dpt_types": {"control": "DPT1.001"}
                    },
                    {
                        "entity_id": "light.aux",
                        "entity_type": "light",
                        "physical_address": "1/1/2",
                        "group_addresses": {"control": "1/1/2"},
                        "dpt_types": {"control": "DPT1.001"}
                    },
                    {
                        "entity_id": "switch.power",
                        "entity_type": "switch",
                        "physical_address": "1/1/3",
                        "group_addresses": {"control": "1/1/3"},
                        "dpt_types": {"control": "DPT1.001"}
                    }
                ],
                "entity_count": 3
            }
        }
        response_future.set_result(response_data)

        result = await knx_integration.request_knx_address("device_multi", device_info)

        assert result is not None
        assert result["entity_count"] == 3

    @pytest.mark.asyncio
    async def test_request_knx_address_not_connected(self, knx_integration):
        """Test requesting address when not connected."""
        knx_integration.connected = False

        result = await knx_integration.request_knx_address("device_001", {})

        assert result is None


class TestAddressAssignmentHandling:
    """Test handling of address assignment responses."""

    @pytest.mark.asyncio
    async def test_handle_address_assigned_entity_mode(self, knx_integration):
        """Test handling address assignment in entity mode."""
        data = {
            "type": "address_assigned",
            "id": "register_0_response",
            "payload": {
                "device_id": "device_001",
                "success": True,
                "entity_addresses": [
                    {
                        "entity_id": "light.living_room",
                        "entity_type": "light",
                        "physical_address": "1/1/1",
                        "group_addresses": {
                            "control": "1/1/1",
                            "status": "1/1/2"
                        },
                        "dpt_types": {
                            "control": "DPT1.001",
                            "status": "DPT1.001"
                        }
                    }
                ],
                "timestamp": 1234567890.0
            }
        }

        await knx_integration._handle_address_assigned(data)

        # Verify entity mapping was stored
        assert "light.living_room" in knx_integration.entity_mappings
        mapping = knx_integration.entity_mappings["light.living_room"]
        assert mapping["device_id"] == "device_001"
        assert mapping["physical_address"] == "1/1/1"
        assert mapping["entity_type"] == "light"

        # Verify reverse mapping
        assert knx_integration.knx_to_entity["1/1/1"] == "light.living_room"
        assert knx_integration.knx_to_entity["1/1/2"] == "light.living_room"

    @pytest.mark.asyncio
    async def test_handle_address_assigned_legacy_mode(self, knx_integration):
        """Test handling address assignment in legacy mode."""
        data = {
            "type": "address_assigned",
            "id": "register_0_response",
            "payload": {
                "device_id": "device_001",
                "success": True,
                "address_info": {
                    "physical_address": "1/1/1",
                    "group_addresses": {
                        "control": "1/1/1",
                        "status": "1/1/2"
                    },
                    "dpt_types": {
                        "control": "DPT1.001",
                        "status": "DPT1.001"
                    }
                },
                "timestamp": 1234567890.0
            }
        }

        await knx_integration._handle_address_assigned(data)

        # Verify device mapping was stored
        assert "device_001" in knx_integration.device_mappings
        mapping = knx_integration.device_mappings["device_001"]
        assert mapping["physical_address"] == "1/1/1"


class TestStateSynchronization:
    """Test state synchronization to KNX."""

    @pytest.mark.asyncio
    async def test_sync_to_knx(self, knx_integration):
        """Test syncing state to KNX."""
        knx_integration.connected = True

        result = await knx_integration.sync_to_knx("device_001", {"power": "on"})

        assert result is True
        assert not knx_integration.sync_queue.empty()

    @pytest.mark.asyncio
    async def test_sync_to_knx_not_connected(self, knx_integration):
        """Test syncing when not connected."""
        knx_integration.connected = False

        result = await knx_integration.sync_to_knx("device_001", {"power": "on"})

        assert result is False

    @pytest.mark.asyncio
    async def test_process_sync_queue(self, knx_integration):
        """Test processing sync queue."""
        knx_integration.connected = True
        knx_integration.websocket = AsyncMock()
        knx_integration.websocket.send = AsyncMock()

        # Add items to queue
        await knx_integration.sync_queue.put({
            "device_id": "device_001",
            "state": {"power": "on"},
            "timestamp": 1234567890.0
        })

        # Process queue
        await knx_integration._send_sync_batch([
            {"device_id": "device_001", "state": {"power": "on"}, "timestamp": 1234567890.0}
        ])

        # Verify message was sent
        assert knx_integration.websocket.send.called


class TestReverseMapping:
    """Test reverse mapping lookups."""

    @pytest.mark.asyncio
    async def test_get_entity_from_knx(self, knx_integration):
        """Test getting entity ID from KNX address."""
        knx_integration.knx_to_entity = {
            "1/1/1": "light.living_room",
            "1/1/2": "light.bedroom"
        }

        entity_id = knx_integration.get_entity_from_knx("1/1/1")
        assert entity_id == "light.living_room"

        entity_id = knx_integration.get_entity_from_knx("nonexistent")
        assert entity_id is None

    @pytest.mark.asyncio
    async def test_get_device_from_knx_entity(self, knx_integration):
        """Test getting device ID from KNX address via entity."""
        knx_integration.entity_mappings = {
            "light.living_room": {
                "device_id": "device_001",
                "physical_address": "1/1/1",
                "entity_type": "light"
            }
        }
        knx_integration.knx_to_entity = {
            "1/1/1": "light.living_room"
        }

        device_id = knx_integration.get_device_from_knx("1/1/1")
        assert device_id == "device_001"

    @pytest.mark.asyncio
    async def test_get_entity_knx_mapping(self, knx_integration):
        """Test getting entity KNX mapping."""
        knx_integration.entity_mappings = {
            "light.living_room": {
                "device_id": "device_001",
                "physical_address": "1/1/1",
                "entity_type": "light",
                "group_addresses": {"control": "1/1/1"}
            }
        }

        mapping = knx_integration.get_entity_knx_mapping("light.living_room")
        assert mapping is not None
        assert mapping["device_id"] == "device_001"
        assert mapping["physical_address"] == "1/1/1"

        mapping = knx_integration.get_entity_knx_mapping("nonexistent")
        assert mapping is None

    @pytest.mark.asyncio
    async def test_get_device_entities_knx_mapping(self, knx_integration):
        """Test getting all entity mappings for a device."""
        knx_integration.entity_mappings = {
            "light.living_room_main": {
                "device_id": "device_001",
                "entity_type": "light"
            },
            "light.living_room_aux": {
                "device_id": "device_001",
                "entity_type": "light"
            },
            "light.bedroom": {
                "device_id": "device_002",
                "entity_type": "light"
            }
        }

        mappings = knx_integration.get_device_entities_knx_mapping("device_001")

        assert len(mappings) == 2
        assert "light.living_room_main" in mappings
        assert "light.living_room_aux" in mappings
        assert "light.bedroom" not in mappings


class TestMessageHandling:
    """Test KNX message handling."""

    @pytest.mark.asyncio
    async def test_handle_knx_state_update(self, knx_integration):
        """Test handling KNX state update."""
        data = {
            "type": "knx_state_update",
            "id": "knx_1",
            "payload": {
                "device_id": "device_001",
                "knx_address": "1/1/1",
                "value": True
            }
        }

        # Should not raise
        await knx_integration._handle_knx_state_update(data)

    @pytest.mark.asyncio
    async def test_handle_error_message(self, knx_integration):
        """Test handling error message from KNX Gateway."""
        data = {
            "type": "error",
            "id": "register_0_response",
            "payload": {
                "error_code": "ALLOCATION_FAILED",
                "error_message": "Address pool exhausted"
            }
        }

        # Set up pending response
        future = asyncio.Future()
        knx_integration.pending_responses["register_0"] = future

        # Handle error
        await knx_integration._handle_knx_message(data)

        # Future should have exception set
        assert future.done()
        assert future.exception() is not None


class TestConnectionRecovery:
    """Test connection recovery logic."""

    @pytest.mark.asyncio
    async def test_reconnect_after_connection_closed(self, knx_integration):
        """Test reconnection after connection closed."""
        knx_integration.connected = True

        # Mock the reconnect
        with patch.object(knx_integration, 'connect_to_knx_gateway', AsyncMock()):
            await knx_integration._reconnect()

            # Should attempt to reconnect
            assert knx_integration.connect_to_knx_gateway.called


class TestStopAndCleanup:
    """Test stopping and cleanup."""

    @pytest.mark.asyncio
    async def test_stop_integration(self, knx_integration):
        """Test stopping the integration."""
        knx_integration.sync_task = Mock()
        knx_integration.sync_task.cancel = Mock()

        mock_websocket = AsyncMock()
        mock_websocket.close = AsyncMock()
        knx_integration.websocket = mock_websocket
        knx_integration.connected = True

        await knx_integration.stop()

        assert knx_integration.connected is False
        assert knx_integration.sync_task.cancel.called or knx_integration.sync_task is None
        assert mock_websocket.close.called

    @pytest.mark.asyncio
    async def test_stop_with_sync_task(self, knx_integration):
        """Test stopping with active sync task."""
        # Create a real async task
        async def dummy_sync():
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise

        knx_integration.sync_task = asyncio.create_task(dummy_sync())

        mock_websocket = AsyncMock()
        mock_websocket.close = AsyncMock()
        knx_integration.websocket = mock_websocket
        knx_integration.connected = True

        await knx_integration.stop()

        assert knx_integration.connected is False


class TestResponseWaiting:
    """Test waiting for responses."""

    @pytest.mark.asyncio
    async def test_wait_for_response_success(self, knx_integration):
        """Test successfully waiting for response."""
        response_data = {"type": "test", "payload": {"success": True}}

        # Run wait_for_response in background
        task = asyncio.create_task(knx_integration._wait_for_response("msg_1"))

        # Simulate response arriving
        await asyncio.sleep(0.01)
        future = knx_integration.pending_responses.get("msg_1")
        if future:
            future.set_result(response_data)

        # Wait for result
        result = await task
        assert result == response_data

    @pytest.mark.asyncio
    async def test_wait_for_response_timeout(self, knx_integration):
        """Test timeout when waiting for response."""
        with pytest.raises(asyncio.TimeoutError):
            await knx_integration._wait_for_response("msg_1", timeout=0.1)

        # Should clean up pending response
        assert "msg_1" not in knx_integration.pending_responses

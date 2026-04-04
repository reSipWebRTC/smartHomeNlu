"""Tests for protocol message handling."""

import pytest
from ha_gateway.protocol.message import (
    Message,
    MessageType,
    create_response,
    create_error,
    create_state_update,
    DeviceState,
    DeviceInfo
)


class TestMessage:
    """Test message handling."""

    def test_message_creation(self):
        """Test creating messages."""
        msg = Message(type=MessageType.DISCOVER, id="test_1")
        assert msg.type == MessageType.DISCOVER
        assert msg.id == "test_1"
        assert msg.payload == {}

    def test_message_serialization(self):
        """Test message JSON serialization."""
        msg = Message(type=MessageType.GET_STATE, id="test_1", payload={"entity_id": "light.bedroom"})
        json_str = msg.json
        assert "type" in json_str
        assert "id" in json_str
        assert "payload" in json_str

        # Test deserialization
        loaded_msg = Message.from_json(json_str)
        assert loaded_msg.type == MessageType.GET_STATE
        assert loaded_msg.id == "test_1"
        assert loaded_msg.payload["entity_id"] == "light.bedroom"

    def test_create_response(self):
        """Test creating response messages."""
        original = Message(type=MessageType.GET_STATE, id="test_1")
        response = create_response(original, success=True, data={"state": "on"})
        assert response.type == MessageType.RESPONSE
        assert response.id == original.id
        assert response.payload["success"] is True
        assert response.payload["data"]["state"] == "on"

    def test_create_error(self):
        """Test creating error messages."""
        original = Message(type=MessageType.GET_STATE, id="test_1")
        error = create_error(original, "Entity not found")
        assert error.type == MessageType.ERROR
        assert error.id == original.id
        assert error.payload["error"] == "Entity not found"

    def test_create_state_update(self):
        """Test creating state update messages."""
        state = DeviceState(
            entity_id="light.bedroom",
            domain="light",
            state="on",
            attributes={"brightness": 255}
        )
        update = create_state_update("light.bedroom", state.to_dict())
        assert update.type == MessageType.STATE_UPDATE
        assert update.payload["entity_id"] == "light.bedroom"
        assert update.payload["state"]["state"] == "on"


class TestDeviceState:
    """Test device state representation."""

    def test_device_state_creation(self):
        """Test creating device state."""
        state = DeviceState(
            entity_id="light.bedroom",
            domain="light",
            state="on",
            attributes={"brightness": 255}
        )
        assert state.entity_id == "light.bedroom"
        assert state.domain == "light"
        assert state.state == "on"
        assert state.attributes["brightness"] == 255

    def test_device_state_serialization(self):
        """Test device state serialization."""
        state = DeviceState(
            entity_id="light.bedroom",
            domain="light",
            state="on",
            attributes={"brightness": 255}
        )
        data = state.to_dict()
        assert data["entity_id"] == "light.bedroom"
        assert data["attributes"]["brightness"] == 255


class TestDeviceInfo:
    """Test device information representation."""

    def test_device_info_creation(self):
        """Test creating device info."""
        state = DeviceState(
            entity_id="light.bedroom",
            domain="light",
            state="on",
            attributes={"brightness": 255}
        )
        device = DeviceInfo(
            entity_id="light.bedroom",
            name="Bedroom Light",
            domain="light",
            state=state
        )
        assert device.entity_id == "light.bedroom"
        assert device.name == "Bedroom Light"
        assert device.domain == "light"
        assert device.state.state == "on"

    def test_device_info_serialization(self):
        """Test device info serialization."""
        state = DeviceState(
            entity_id="light.bedroom",
            domain="light",
            state="on",
            attributes={"brightness": 255}
        )
        device = DeviceInfo(
            entity_id="light.bedroom",
            name="Bedroom Light",
            domain="light",
            state=state
        )
        data = device.to_dict()
        assert data["entity_id"] == "light.bedroom"
        assert data["state"]["state"] == "on"
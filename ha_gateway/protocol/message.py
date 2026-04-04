"""Message format and handling for Home Assistant Gateway."""

import json
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Union, List
from enum import Enum


class MessageType(Enum):
    """Message types for the gateway protocol."""
    # Client to gateway
    DISCOVER = "discover"
    GET_STATE = "get_state"
    SET_STATE = "set_state"
    CALL_SERVICE = "call_service"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"

    # Device management
    LIST_DEVICES = "list_devices"
    GET_DEVICE = "get_device"
    CONTROL_DEVICE = "control_device"
    SUBSCRIBE_DEVICE = "subscribe_device"
    UNSUBSCRIBE_DEVICE = "unsubscribe_device"

    # Gateway to client
    STATE_UPDATE = "state_update"
    EVENT = "event"
    RESPONSE = "response"
    ERROR = "error"
    DISCOVER_DEVICES = "discover_devices"
    DEVICE_LIST = "device_list"
    DEVICE_STATE_UPDATE = "device_state_update"

    # Home Assistant to gateway
    HA_STATE_CHANGED = "ha_state_changed"
    HA_EVENT = "ha_event"

    # KNX Gateway integration
    KNX_CONTROL = "knx_control"


@dataclass
class Message:
    """Base message class."""
    type: MessageType
    id: str
    payload: Dict[str, Any] = None

    def __post_init__(self):
        if self.payload is None:
            self.payload = {}
        if isinstance(self.type, str):
            self.type = MessageType(self.type)

    @property
    def json(self) -> str:
        """Convert message to JSON string."""
        data = {
            "type": self.type.value,
            "id": self.id,
            "payload": self.payload
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        """Create message from JSON string."""
        data = json.loads(json_str)
        return cls(
            type=MessageType(data["type"]),
            id=data["id"],
            payload=data.get("payload", {})
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary."""
        return {
            "type": self.type.value,
            "id": self.id,
            "payload": self.payload
        }


def create_message(message_type: MessageType, payload: Optional[Dict[str, Any]] = None) -> Message:
    """Create a new message with a unique ID."""
    return Message(type=message_type, id=str(uuid.uuid4()), payload=payload or {})


@dataclass
class DeviceState:
    """Device state information."""
    entity_id: str
    domain: str
    state: str
    attributes: Dict[str, Any] = None
    last_changed: Optional[str] = None
    last_updated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class DeviceInfo:
    """Device information."""
    entity_id: str
    name: str
    domain: str
    device_class: Optional[str] = None
    capabilities: Dict[str, Any] = None
    state: DeviceState = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        if self.state:
            data["state"] = self.state.to_dict()
        return data


@dataclass
class ServiceCall:
    """Service call information."""
    domain: str
    service: str
    target: Dict[str, Any] = None
    service_data: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


def create_response(message: Message, success: bool = True, data: Any = None, error: str = None) -> Message:
    """Create a response message."""
    return Message(
        type=MessageType.RESPONSE,
        id=message.id,
        payload={
            "success": success,
            "data": data,
            "error": error
        }
    )


def create_error(message: Message, error: str) -> Message:
    """Create an error message."""
    return Message(
        type=MessageType.ERROR,
        id=message.id,
        payload={"error": error}
    )


def create_state_update(entity_id: str, state: Dict[str, Any]) -> Message:
    """Create a state update message."""
    return Message(
        type=MessageType.STATE_UPDATE,
        id=str(uuid.uuid4()),
        payload={"entity_id": entity_id, "state": state}
    )


def create_device_list(devices: List[Dict[str, Any]]) -> Message:
    """Create a device list message."""
    return Message(
        type=MessageType.DEVICE_LIST,
        id=str(uuid.uuid4()),
        payload={"devices": devices}
    )


def create_device_state_update(device_id: str, device_state: Dict[str, Any]) -> Message:
    """Create a device state update message."""
    return Message(
        type=MessageType.DEVICE_STATE_UPDATE,
        id=str(uuid.uuid4()),
        payload={"device_id": device_id, "state": device_state}
    )
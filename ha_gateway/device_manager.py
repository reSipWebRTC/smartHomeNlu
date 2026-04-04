"""Device management for Home Assistant Gateway."""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime

from protocol.message import DeviceInfo, DeviceState, MessageType
from config import Config


logger = logging.getLogger(__name__)


@dataclass
class Device:
    """Device representation."""
    entity_id: str
    name: str
    domain: str
    device_class: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    state: Optional[DeviceState] = None
    last_updated: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "domain": self.domain,
            "device_class": self.device_class,
            "capabilities": self.capabilities,
            "state": self.state.to_dict() if self.state else None,
            "last_updated": self.last_updated.isoformat(),
            "metadata": self.metadata
        }


class DeviceManager:
    """Manages Home Assistant devices and their states."""

    def __init__(self, config: Config):
        self.config = config
        self.devices: Dict[str, Device] = {}
        self.state_callbacks: List[Callable[[str, DeviceState], Any]] = []
        self._update_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the device manager."""
        logger.info("Initializing device manager")

    async def refresh_devices(self) -> None:
        """Refresh all device states from Home Assistant."""
        # This will be implemented with the HA WebSocket connection
        pass

    async def update_state(self, entity_id: str, state_data: Dict[str, Any]) -> None:
        """Update device state."""
        async with self._update_lock:
            if entity_id not in self.devices:
                await self._create_device_from_state(entity_id, state_data)

            device = self.devices[entity_id]
            old_state = device.state.state if device.state else None

            # Update device state
            device.state = DeviceState(
                entity_id=entity_id,
                domain=entity_id.split(".")[0],
                state=state_data["state"],
                attributes=state_data.get("attributes", {}),
                last_changed=state_data.get("last_changed"),
                last_updated=state_data.get("last_updated")
            )

            device.last_updated = datetime.now()

            # Notify callbacks if state changed
            if old_state != state_data["state"]:
                for callback in self.state_callbacks:
                    try:
                        callback_result = callback(entity_id, device.state)
                        if asyncio.iscoroutine(callback_result):
                            await callback_result
                    except Exception as e:
                        logger.error(f"Error in state callback: {e}")

    async def _create_device_from_state(self, entity_id: str, state_data: Dict[str, Any]) -> None:
        """Create device from state data."""
        domain = entity_id.split(".")[0]
        attributes = state_data.get("attributes", {})

        device = Device(
            entity_id=entity_id,
            name=attributes.get("friendly_name", entity_id),
            domain=domain,
            device_class=attributes.get("device_class"),
            state=DeviceState(
                entity_id=entity_id,
                domain=domain,
                state=state_data["state"],
                attributes=attributes,
                last_changed=state_data.get("last_changed"),
                last_updated=state_data.get("last_updated")
            ),
            last_updated=datetime.now()
        )

        # Detect capabilities
        device.capabilities = self._detect_capabilities(domain, attributes)

        # Add metadata
        device.metadata = {
            "manufacturer": attributes.get("manufacturer"),
            "model": attributes.get("model"),
            "sw_version": attributes.get("sw_version"),
            "via_device": attributes.get("via_device"),
            "area_id": attributes.get("area_id"),
            "device_id": attributes.get("device_id")
        }

        self.devices[entity_id] = device
        logger.debug(f"Created device: {entity_id}")

    def _detect_capabilities(self, domain: str, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """Detect device capabilities based on domain and attributes."""
        capabilities = {"domain": domain}

        if domain == "light":
            capabilities.update({
                "brightness": attributes.get("brightness") is not None,
                "color": "color_mode" in attributes,
                "color_temp": "color_temp" in attributes or "color_temp" in attributes,
                "xy_color": "xy_color" in attributes,
                "hs_color": "hs_color" in attributes,
                "rgb_color": "rgb_color" in attributes,
                "effect": "effect" in attributes,
                "transition": True
            })
        elif domain == "switch":
            capabilities.update({
                "default": True
            })
        elif domain == "sensor":
            capabilities.update({
                "unit_of_measurement": attributes.get("unit_of_measurement"),
                "state_class": attributes.get("state_class"),
                "device_class": attributes.get("device_class")
            })
        elif domain == "binary_sensor":
            capabilities.update({
                "device_class": attributes.get("device_class")
            })
        elif domain == "climate":
            capabilities.update({
                "temperature": True,
                "humidity": attributes.get("humidity") is not None,
                "mode": True,
                "fan_mode": "fan_mode" in attributes,
                "swing_mode": "swing_mode" in attributes,
                "preset_mode": "preset_mode" in attributes
            })
        elif domain == "cover":
            capabilities.update({
                "position": attributes.get("position") is not None,
                "tilt": attributes.get("tilt_position") is not None,
                "current_position": True,
                "current_tilt_position": attributes.get("tilt_position") is not None
            })
        elif domain == "media_player":
            capabilities.update({
                "volume": attributes.get("volume_level") is not None,
                "muted": "is_volume_muted" in attributes,
                "source": "source" in attributes,
                "media_title": attributes.get("media_title") is not None,
                "media_artist": attributes.get("media_artist") is not None,
                "album_name": attributes.get("media_album_name") is not None,
                "duration": attributes.get("media_duration") is not None,
                "position": attributes.get("media_position") is not None,
                "position_updated_at": attributes.get("media_position_updated_at") is not None
            })

        return capabilities

    def get_device(self, entity_id: str) -> Optional[Device]:
        """Get device by entity ID."""
        return self.devices.get(entity_id)

    def get_devices(self, domain: Optional[str] = None) -> List[Device]:
        """Get all devices, optionally filtered by domain."""
        if domain:
            return [d for d in self.devices.values() if d.domain == domain]
        return list(self.devices.values())

    def get_devices_by_capability(self, capability: str) -> List[Device]:
        """Get devices by capability."""
        return [d for d in self.devices.values() if d.capabilities.get(capability)]

    async def call_service(self, entity_id: str, service: str, **kwargs) -> bool:
        """Call service on device."""
        if entity_id not in self.devices:
            logger.error(f"Device not found: {entity_id}")
            return False

        device = self.devices[entity_id]
        logger.info(f"Calling {device.domain}.{service} on {entity_id}")

        # This will be implemented with the HA WebSocket connection
        # For now, just log the service call
        logger.debug(f"Service parameters: {kwargs}")

        return True

    def add_state_callback(self, callback: Callable[[str, DeviceState], Any]) -> None:
        """Add state change callback."""
        self.state_callbacks.append(callback)

    def remove_state_callback(self, callback: Callable[[str, DeviceState], Any]) -> None:
        """Remove state change callback."""
        if callback in self.state_callbacks:
            self.state_callbacks.remove(callback)

    def get_device_summary(self) -> Dict[str, Any]:
        """Get summary of all devices."""
        return {
            "total": len(self.devices),
            "by_domain": {},
            "by_capability": {}
        }

    async def cleanup_stale_devices(self, max_age_seconds: int = 3600) -> None:
        """Remove stale devices that haven't been updated recently."""
        now = datetime.now()
        stale_threshold = now.timestamp() - max_age_seconds

        stale_devices = []
        for entity_id, device in self.devices.items():
            if device.last_updated.timestamp() < stale_threshold:
                stale_devices.append(entity_id)

        if stale_devices:
            logger.info(f"Removing {len(stale_devices)} stale devices")
            for entity_id in stale_devices:
                del self.devices[entity_id]

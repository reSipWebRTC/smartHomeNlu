"""Device manager for Home Assistant Gateway.

This module manages devices and their relationships with entities.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from collections import defaultdict

from device_models import (
    Device, Entity, EntityType, DeviceType, DeviceCapabilities, DeviceState
)


logger = logging.getLogger(__name__)


@dataclass
class DeviceGroupingRule:
    """Device grouping rule."""
    by_device_id: bool = True
    by_via_device: bool = True
    by_naming_pattern: bool = True
    naming_pattern: str = r"(.+?)_[^_]+$"


class DeviceManager:
    """Manages Home Assistant devices and their entities.

    The DeviceManager:
    - Discovers and groups entities into devices
    - Manages device states
    - Provides control interfaces
    - Maps entities to devices
    """

    def __init__(self, config=None, ha_ws=None):
        self.config = config
        self.ha_ws = ha_ws  # Home Assistant WebSocket client for fetching device info
        self.devices: Dict[str, Device] = {}
        self.entity_to_device: Dict[str, str] = {}  # entity_id -> device_id
        self.area_to_devices: Dict[str, List[str]] = defaultdict(list)
        self.state_callbacks: List[Callable[[str, Device], None]] = []
        self._lock = asyncio.Lock()
        self._grouping_rule = DeviceGroupingRule()

    async def initialize(self) -> None:
        """Initialize device manager."""
        logger.info("Initializing device manager")

    async def start(self) -> None:
        """Start device manager."""
        logger.info("Starting device manager")

    async def stop(self) -> None:
        """Stop device manager."""
        logger.info("Stopping device manager")

    def set_grouping_rule(self, rule: DeviceGroupingRule) -> None:
        """Set device grouping rule."""
        self._grouping_rule = rule
        logger.info(f"Updated grouping rule: {rule}")

    async def discover_devices(self, states: List[Dict[str, Any]]) -> List[Device]:
        """Discover devices from entity states.

        Args:
            states: List of entity states from Home Assistant

        Returns:
            List of discovered devices
        """
        logger.info(f"Discovering devices from {len(states)} entities")

        # Clear existing mappings
        self.devices.clear()
        self.entity_to_device.clear()
        self.area_to_devices.clear()

        # Filter out unwanted entities (non-physical devices)
        filtered_states = [s for s in states if self._should_include_entity(s)]
        excluded_count = len(states) - len(filtered_states)
        if excluded_count > 0:
            logger.info(f"Filtered out {excluded_count} non-physical entities")
            logger.debug(f"Remaining entities: {len(filtered_states)}")

        # Group entities by device
        entity_groups = self._group_entities_by_device(filtered_states)

        # Create devices from groups
        for device_id, entity_states in entity_groups.items():
            device = await self._create_device_from_states(device_id, entity_states)
            if device:
                self.devices[device_id] = device
                # Update mappings
                for entity_id in device.entity_ids:
                    self.entity_to_device[entity_id] = device_id
                if device.area_id:
                    self.area_to_devices[device.area_id].append(device_id)

        logger.info(f"Discovered {len(self.devices)} devices")

        # Print device list
        self._print_device_list()

        # Trigger device change callbacks for all discovered devices
        # This allows integrations like KNX to register newly discovered devices
        logger.info(f"Triggering device change callbacks for {len(self.devices)} devices (callbacks: {len(self.state_callbacks)})")
        for device_id, device in self.devices.items():
            logger.info(f"Processing device: {device_id} (type: {device.device_type})")
            for idx, callback in enumerate(self.state_callbacks):
                try:
                    logger.info(f"  Calling callback {idx}: {callback.__name__ if hasattr(callback, '__name__') else 'unknown'}")
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device_id, device)
                    else:
                        callback(device_id, device)
                    logger.info(f"  Callback {idx} completed")
                except Exception as e:
                    logger.error(f"Error in device discovery callback for {device_id}: {e}")

        return list(self.devices.values())

    def _group_entities_by_device(self, states: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """Group entities by device.

        Grouping priority:
        1. By device_id
        2. By via_device
        3. By naming pattern
        """
        groups = defaultdict(list)

        # Debug: log cuco entities
        cuco_entities = [s for s in states if "cuco_v3_359a" in s.get("entity_id", "")]
        logger.debug(f"Found {len(cuco_entities)} cuco entities")
        for state in cuco_entities:
            entity_id = state.get("entity_id")
            attributes = state.get("attributes", {})
            device_id = attributes.get("device_id")
            via_device = attributes.get("via_device")
            logger.debug(f"  Entity: {entity_id}, device_id: {device_id}, via_device: {via_device}")

        for state in states:
            entity_id = state.get("entity_id")
            if not entity_id:
                continue

            attributes = state.get("attributes", {})
            device_id = attributes.get("device_id")

            # Strategy 1: Group by device_id
            if device_id and self._grouping_rule.by_device_id:
                logger.debug(f"Grouping {entity_id} by device_id: {device_id}")
                groups[device_id].append(state)
                continue

            # Strategy 2: Group by via_device
            via_device = attributes.get("via_device")
            if via_device and self._grouping_rule.by_via_device:
                if isinstance(via_device, str):
                    logger.debug(f"Grouping {entity_id} by via_device (str): {via_device}")
                    groups[via_device].append(state)
                elif isinstance(via_device, dict):
                    via_id = via_device.get("id", "unknown")
                    logger.debug(f"Grouping {entity_id} by via_device (dict): {via_id}")
                    groups[via_id].append(state)
                continue

            # Strategy 3: Group by naming pattern
            if self._grouping_rule.by_naming_pattern:
                base_id = self._extract_base_from_entity_id(entity_id)
                if base_id:
                    logger.debug(f"Grouping {entity_id} by naming pattern: {base_id}")
                    groups[base_id].append(state)
                    continue

            # Fallback: entity is its own device
            logger.debug(f"Using fallback for {entity_id} (own device)")
            groups[entity_id].append(state)

        # Log grouping summary
        logger.debug(f"Entity grouping summary:")
        logger.debug(f"  Total entities processed: {len(states)}")
        logger.debug(f"  Total groups created: {len(groups)}")

        return dict(groups)

    def _extract_base_from_entity_id(self, entity_id: str) -> Optional[str]:
        """Extract base device ID from entity ID using pattern.

        First try to extract device_id from entity attributes if available.
        Otherwise, use the naming pattern on the entity ID (without domain prefix).
        """
        # Extract the entity ID without domain prefix
        # e.g., "sensor.cuco_v3_359a_power" -> "cuco_v3_359a_power"
        parts = entity_id.split(".")
        if len(parts) < 2:
            return None

        entity_name = parts[-1]  # Get the last part (entity name without domain)

        # Try multiple patterns to extract base device ID
        # Priority 1: Try to find a pattern like <brand>_<model>_<id>_<suffix>
        #            and extract <brand>_<model>_<id>
        try:
            # Pattern 1: Match entities like "cuco_v3_359a_*" -> "cuco_v3_359a"
            # This uses a pattern to find the last number sequence followed by underscore
            import re
            match = re.match(r'(.+_\d+)', entity_name)
            if match:
                base = match.group(1)
                logger.debug(f"  Extracted base '{base}' from '{entity_name}' using numeric pattern")
                return base
        except Exception:
            pass

        # Priority 2: Use the naming pattern from config
        try:
            match = re.match(self._grouping_rule.naming_pattern, entity_name)
            if match:
                base = match.group(1)
                logger.debug(f"  Extracted base '{base}' from '{entity_name}' using config pattern")
                return base
        except Exception:
            pass

        # Priority 3: Split by last underscore
        try:
            if "_" in entity_name:
                base = entity_name.rsplit("_", 1)[0]
                logger.debug(f"  Extracted base '{base}' from '{entity_name}' using rsplit")
                return base
        except Exception:
            pass

        return None

    def _should_include_entity(self, state: Dict[str, Any]) -> bool:
        """Check if an entity should be included in device discovery.

        Filters out non-physical devices like:
        - Sun (sensor.sun_*)
        - HACS (update.hacs_*)
        - Backup (event.backup_*, sensor.backup_*)
        - Person (person.*)
        - Zone (zone.*)
        - MQTT bridges and automations
        - System integrations (google_translate, shopping_list, conversation)

        Args:
            state: Entity state from Home Assistant

        Returns:
            True if entity should be included, False otherwise
        """
        entity_id = state.get("entity_id", "")
        attributes = state.get("attributes", {})

        # Exclude by entity_id patterns
        exclude_patterns = [
            r"^sensor\.sun_",           # Sun sensors (sun_next_dawn, etc.)
            r"^sun\.",                  # Sun entities
            r"^person\.",               # Person entities
            r"^zone\.",                 # Zone entities
            r"^sensor\.backup_",        # Backup sensors
            r"^event\.backup_",         # Backup events
            r"^update\.hacs_",          # HACS updates
            r"^automation\.mqtt",       # MQTT automations
            r"^automation\.mqttwang",   # MQTT gateway automations (Chinese)
            r"^script\.mqtt_bridge",    # MQTT bridge scripts
            r"^script\.mqttwang",       # MQTT gateway scripts (Chinese)
            r"^sensor\.mqtt_bridge",    # MQTT bridge sensors
            r"^sensor\.mqttwang",       # MQTT gateway sensors (Chinese)
            r"^tts\.",                  # TTS entities
            r"^conversation\.",         # Conversation entities
            r"^todo\.",                 # Todo lists
            r"^input_boolean\.",        # Input booleans (often helpers)
        ]

        for pattern in exclude_patterns:
            if re.match(pattern, entity_id):
                logger.debug(f"Excluding entity {entity_id} (matches pattern: {pattern})")
                return False

        # Exclude by device_id patterns
        device_id = attributes.get("device_id", "")
        if device_id:
            exclude_device_patterns = [
                r"^home$",                   # Home Assistant core
                r"^zone\.",                  # Zone devices
                r"^person\.",                # Person devices
                r"^mqtt_bridge",             # MQTT bridge
                r"^mqttwang_qiao",           # MQTT gateway (Chinese)
                r"^google_translate_",       # Google Translate
                r"^shopping_list_",          # Shopping lists
            ]

            for pattern in exclude_device_patterns:
                if re.match(pattern, device_id):
                    logger.debug(f"Excluding entity {entity_id} (device_id {device_id} matches pattern: {pattern})")
                    return False

        # Exclude by device name patterns
        device_name = attributes.get("device", "") or attributes.get("friendly_name", "")
        if device_name:
            # Filter out generic system devices
            exclude_names = ["home assistant", "home", "sun", "none", "hacs update", "backup"]
            if device_name.lower() in exclude_names:
                logger.debug(f"Excluding entity {entity_id} (device name: {device_name})")
                return False

        # Exclude unknown device types that are likely system entities
        # (This is checked later, but we can do an early filter here)

        return True

    async def _create_device_from_states(self, device_id: str, states: List[Dict]) -> Optional[Device]:
        """Create device from entity states."""
        if not states:
            return None

        # Use first state as primary reference
        primary_state = states[0]
        entity_id = primary_state.get("entity_id")
        attributes = primary_state.get("attributes", {})

        # Determine device type from entities
        device_type = self._determine_device_type(states)

        # Get device info from device registry (preferred) or fallback to entity attributes
        if self.ha_ws:
            # Try to get device name from device registry
            device_name = self.ha_ws.get_device_name(device_id)
            if device_name:
                name = device_name
                logger.debug(f"Using device name from registry: {device_name} for device {device_id}")
            else:
                # Fallback to entity's friendly_name
                name = attributes.get("friendly_name", device_id)
                logger.debug(f"Using entity friendly_name as device name: {name} for device {device_id}")

            # Get model and manufacturer from device registry
            model, manufacturer = self.ha_ws.get_device_model_info(device_id)
            if not model:
                model = attributes.get("model")
            if not manufacturer:
                manufacturer = attributes.get("manufacturer")
        else:
            # No ha_ws available, use entity attributes
            name = attributes.get("friendly_name", device_id)
            model = attributes.get("model")
            manufacturer = attributes.get("manufacturer")

        area_id = attributes.get("area_id")
        via_device = attributes.get("via_device")

        # Handle via_device as dict or string
        via_device_id = None
        if isinstance(via_device, str):
            via_device_id = via_device
        elif isinstance(via_device, dict):
            via_device_id = via_device.get("id")

        # Create device
        device = Device(
            device_id=device_id,
            name=name,
            device_type=device_type,
            model=model,
            manufacturer=manufacturer,
            area_id=area_id,
            via_device_id=via_device_id
        )

        # Find primary entity
        primary_entity_id = self._find_primary_entity(states)
        device.primary_entity_id = primary_entity_id

        # Create entities
        for state in states:
            entity = self._create_entity_from_state(state, device)
            if entity:
                device.add_entity(entity)

        # Initialize device state
        await self._aggregate_device_state(device)

        # Map entity capabilities to device capabilities
        self._map_entity_capabilities_to_device(device)

        # Update metadata
        device.metadata = {
            "via_device": via_device,
            "via_device_id": via_device_id,
            "entity_count": len(device.entities),
            "primary_entity_count": len(device.control_entities),
            "sensor_count": len(device.sensor_entities)
        }

        return device

    def _map_entity_capabilities_to_device(self, device: Device) -> None:
        """Map entity capabilities to device capabilities."""
        for entity in device.entities:
            entity_caps = entity.capabilities
            if isinstance(entity_caps, dict):
                # Map dictionary capabilities to DeviceCapabilities
                if entity_caps.get("default") or entity_caps.get("power_control"):
                    device.capabilities.power_control = True
                if entity_caps.get("brightness"):
                    device.capabilities.brightness_control = True
                if entity_caps.get("color"):
                    device.capabilities.color_control = True
                if entity_caps.get("color_temp"):
                    device.capabilities.color_temp_control = True
                if entity.domain == "climate":
                    device.capabilities.temperature_control = True
                    device.capabilities.humidity_control = True
                    device.capabilities.mode_control = True
                if entity_caps.get("position") and entity.domain in ["cover", "fan"]:
                    device.capabilities.position_control = True
                if entity.domain == "lock":
                    device.capabilities.lock_control = True
                if entity.device_class in ["temperature", "heat", "cold"]:
                    device.capabilities.temperature_sensing = True
                if entity.device_class in ["humidity", "moisture"]:
                    device.capabilities.humidity_sensing = True
                if entity.device_class == "pressure":
                    device.capabilities.pressure_sensing = True
                if entity.device_class == "illuminance":
                    device.capabilities.illuminance_sensing = True

    def _determine_device_type(self, states: List[Dict]) -> DeviceType:
        """Determine device type from entities."""
        # Priority based on domain presence
        for state in states:
            entity_id = state.get("entity_id")
            if entity_id:
                domain = entity_id.split(".")[0]
                if domain == "light":
                    return DeviceType.LIGHT
                elif domain == "switch":
                    return DeviceType.SWITCH
                elif domain == "climate":
                    return DeviceType.CLIMATE
                elif domain == "cover":
                    return DeviceType.COVER
                elif domain == "fan":
                    return DeviceType.FAN
                elif domain == "lock":
                    return DeviceType.LOCK
                elif domain == "media_player":
                    return DeviceType.MEDIA_PLAYER

        # Check sensor types
        sensor_domains = [s.get("entity_id", "").split(".")[0] for s in states]
        if all(d in ["sensor", "binary_sensor"] for d in sensor_domains):
            return DeviceType.SENSOR

        return DeviceType.UNKNOWN

    def _find_primary_entity(self, states: List[Dict]) -> Optional[str]:
        """Find primary entity for control."""
        # Priority order for primary entity selection
        domain_priority = [
            "light", "switch", "climate", "cover", "fan", "lock", "media_player"
        ]

        for domain in domain_priority:
            for state in states:
                entity_id = state.get("entity_id")
                if entity_id and entity_id.startswith(domain):
                    return entity_id

        # Fallback to first entity
        return states[0].get("entity_id") if states else None

    def _create_entity_from_state(self, state: Dict, device: Device) -> Optional[Entity]:
        """Create entity from state."""
        entity_id = state.get("entity_id")
        if not entity_id:
            return None

        domain = entity_id.split(".")[0]
        attributes = state.get("attributes", {})

        # Determine entity type
        entity_type = self._determine_entity_type(entity_id, device)

        entity = Entity(
            entity_id=entity_id,
            domain=domain,
            name=attributes.get("friendly_name", entity_id),
            entity_type=entity_type,
            attributes=attributes,
            state=state.get("state", "unknown"),
            capabilities=self._get_entity_capabilities(state),
            unit_of_measurement=attributes.get("unit_of_measurement"),
            device_class=attributes.get("device_class")
        )

        return entity

    def _determine_entity_type(self, entity_id: str, device: Device) -> EntityType:
        """Determine entity type."""
        domain = entity_id.split(".")[0]

        # Primary entity
        if device.primary_entity_id == entity_id:
            return EntityType.PRIMARY

        # Control entities
        if domain in ["light", "switch", "climate", "cover", "fan", "lock", "media_player", "input_boolean", "button"]:
            return EntityType.CONTROL

        # Sensor entities
        if domain in ["sensor", "binary_sensor"]:
            return EntityType.SENSOR

        return EntityType.DIAGNOSTIC

    def _get_entity_capabilities(self, state: Dict) -> Dict[str, Any]:
        """Get entity capabilities."""
        attributes = state.get("attributes", {})
        capabilities = {}

        domain = state.get("entity_id", "").split(".")[0]

        if domain == "light":
            capabilities.update({
                "brightness": attributes.get("brightness") is not None,
                "color": attributes.get("color_mode") is not None,
                "color_temp": attributes.get("color_temp") is not None,
                "effect": "effect" in attributes,
                "transition": True
            })
        elif domain == "switch":
            capabilities["default"] = True
        elif domain == "climate":
            capabilities.update({
                "temperature": True,
                "humidity": attributes.get("humidity") is not None,
                "mode": True,
                "fan_mode": "fan_mode" in attributes,
                "swing_mode": "swing_mode" in attributes,
                "preset_mode": "preset_modes" in attributes
            })

        return capabilities

    async def _aggregate_device_state(self, device: Device) -> None:
        """Aggregate state from all entities."""
        state = DeviceState()

        # Check online status
        for entity in device.entities:
            if entity.state not in ["unavailable", "unknown", "None"]:
                state.online = True
                break

        # Get power state
        primary = device.primary_entity
        if primary:
            state.power_state = primary.state

        # Aggregate sensor data
        for entity in device.sensor_entities:
            self._update_state_from_sensor(state, entity)

        # Aggregate control entity data
        for entity in device.control_entities:
            self._update_state_from_control(state, entity)

        device.state = state

    def _update_state_from_sensor(self, state: DeviceState, entity: Entity) -> None:
        """Update device state from sensor entity."""
        try:
            value = float(entity.state) if entity.state not in ["unavailable", "unknown", "None"] else None

            if "power" in entity.name.lower() and entity.unit_of_measurement in ["W", "kW"]:
                # Handle kW to W conversion
                if entity.unit_of_measurement == "kW":
                    state.power_value = (value * 1000) if value is not None else None
                else:
                    state.power_value = value

            elif "energy" in entity.name.lower() and "today" in entity.name.lower():
                state.energy_today = value

            elif entity.device_class in ["temperature", "heat", "cold"]:
                state.temperature = value

            elif entity.device_class in ["humidity", "moisture"]:
                state.humidity = value

            elif entity.device_class == "pressure":
                state.pressure = value

            elif entity.device_class == "illuminance":
                state.illuminance = value

        except (ValueError, TypeError):
            pass

    def _update_state_from_control(self, state: DeviceState, entity: Entity) -> None:
        """Update device state from control entity."""
        attrs = entity.attributes

        if entity.domain == "light":
            if "brightness" in attrs:
                state.brightness = attrs.get("brightness")
            if "color_temp" in attrs:
                state.color_temp = attrs.get("color_temp")
            if "rgb_color" in attrs:
                state.rgb_color = tuple(attrs.get("rgb_color", []))

        elif entity.domain == "climate":
            state.hvac_mode = entity.state
            state.hvac_action = attrs.get("hvac_action")
            state.preset_mode = attrs.get("preset_mode")
            state.fan_mode = attrs.get("fan_mode")
            state.swing_mode = attrs.get("swing_mode")
            if "current_temperature" in attrs:
                state.temperature = attrs.get("current_temperature")
            if "current_humidity" in attrs:
                state.humidity = attrs.get("current_humidity")

        elif entity.domain == "cover":
            state.position = attrs.get("current_position")

        elif entity.domain == "lock":
            state.locked = entity.state == "locked"

        elif entity.domain == "media_player":
            state.volume = attrs.get("volume_level")
            state.muted = attrs.get("is_volume_muted", False)
            state.playing = entity.state == "playing"

    async def update_entity_state(self, entity_id: str, state_data: Dict) -> None:
        """Update entity state and refresh device state."""
        async with self._lock:
            # Find device for this entity
            device_id = self.entity_to_device.get(entity_id)
            if not device_id:
                return

            device = self.devices.get(device_id)
            if not device:
                return

            # Update entity
            device.update_entity_state(
                entity_id,
                state_data.get("state", "unknown"),
                state_data.get("attributes", {})
            )

            # Re-aggregate device state
            await self._aggregate_device_state(device)

            # Notify callbacks
            for callback in self.state_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device_id, device)
                    else:
                        callback(device_id, device)
                except Exception as e:
                    logger.error(f"Error in device state callback: {e}")

    def get_device(self, device_id: str) -> Optional[Device]:
        """Get device by ID."""
        return self.devices.get(device_id)

    def get_devices(self, device_type: Optional[DeviceType] = None,
                    area_id: Optional[str] = None) -> List[Device]:
        """Get devices with optional filters."""
        devices = list(self.devices.values())

        if device_type:
            devices = [d for d in devices if d.device_type == device_type]

        if area_id:
            devices = [d for d in devices if d.area_id == area_id]

        return devices

    def get_device_by_entity(self, entity_id: str) -> Optional[Device]:
        """Get device by entity ID."""
        device_id = self.entity_to_device.get(entity_id)
        if device_id:
            return self.devices.get(device_id)
        return None

    async def control_device(self, device_id: str, action: str, **params) -> bool:
        """Control device.

        Args:
            device_id: Device ID
            action: Action to perform
            **params: Action parameters

        Returns:
            True if successful
        """
        device = self.devices.get(device_id)
        if not device:
            logger.error(f"Device not found: {device_id}")
            return False

        primary = device.primary_entity
        if not primary:
            logger.error(f"No primary entity for device: {device_id}")
            return False

        # This would integrate with HA WebSocket to call services
        # For now, just log the action
        logger.info(f"Control device {device.name}: {action} {params}")
        logger.debug(f"Via primary entity: {primary.entity_id}")

        # TODO: Implement actual control via HA WebSocket
        return True

    def add_device_change_callback(self, callback: Callable[[str, Device], None]) -> None:
        """Add device change callback."""
        if callback not in self.state_callbacks:
            self.state_callbacks.append(callback)
            logger.info(f"Added device change callback: {callback.__name__ if hasattr(callback, '__name__') else 'unknown'}")
            logger.info(f"Total callbacks registered: {len(self.state_callbacks)}")
        else:
            logger.warning(f"Callback already registered: {callback.__name__ if hasattr(callback, '__name__') else 'unknown'}")

    def remove_device_change_callback(self, callback: Callable[[str, Device], None]) -> None:
        """Remove device change callback."""
        if callback in self.state_callbacks:
            self.state_callbacks.remove(callback)

    def get_device_stats(self) -> Dict[str, Any]:
        """Get device statistics."""
        type_counts = defaultdict(int)
        for device in self.devices.values():
            type_counts[device.device_type.value] += 1

        return {
            "total_devices": len(self.devices),
            "total_entities": len(self.entity_to_device),
            "by_type": dict(type_counts),
            "by_area": {area: len(devices) for area, devices in self.area_to_devices.items()}
        }

    def _print_device_list(self) -> None:
        """Print discovered device list by device ID."""
        logger.info(f"\n{'='*70}")
        logger.info(f"DISCOVERED DEVICES ({len(self.devices)} total)")
        logger.info(f"{'='*70}\n")

        # Sort devices by device ID
        sorted_devices = sorted(self.devices.values(), key=lambda d: d.device_id)

        # Print by device ID
        for device in sorted_devices:
            status = "ON" if device.state.power_state == "on" else "OFF" if device.state.power_state == "off" else "UNKNOWN"
            logger.info(f"[{status}] {device.name}")
            logger.info(f"  Device ID: {device.device_id}")
            logger.info(f"  Device Type: {device.device_type.value}")

            # Group entities by domain for display
            by_domain = defaultdict(list)
            for entity in device.entities:
                by_domain[entity.domain].append(entity)

            # Print entities grouped by domain
            for domain in sorted(by_domain.keys()):
                entities = by_domain[domain]
                logger.info(f"  {domain.upper()} Entities ({len(entities)}):")
                for entity in entities:
                    logger.info(f"    - {entity.entity_id} ({entity.state})")

            logger.info(f"  Capabilities: {', '.join([k for k, v in device.capabilities.to_dict().items() if v]) or 'None'}")
            logger.info("")

        logger.info(f"{'='*70}\n")

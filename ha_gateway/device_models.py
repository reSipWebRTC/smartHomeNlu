"""Device models for Home Assistant Gateway.

This module defines the data structures for devices and entities.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum


class EntityType(Enum):
    """Entity types within a device."""
    PRIMARY = "primary"           # Main control entity
    SENSOR = "sensor"             # Sensor entity
    CONTROL = "control"            # Secondary control entity
    BUTTON = "button"              # Button entity
    DIAGNOSTIC = "diagnostic"     # Diagnostic entity


class DeviceType(Enum):
    """Device types."""
    LIGHT = "light"
    SWITCH = "switch"
    CLIMATE = "climate"
    COVER = "cover"
    FAN = "fan"
    LOCK = "lock"
    MEDIA_PLAYER = "media_player"
    SENSOR = "sensor"
    UNKNOWN = "unknown"


@dataclass
class Entity:
    """Entity within a device."""
    entity_id: str
    domain: str
    name: str
    entity_type: EntityType
    attributes: Dict[str, Any] = field(default_factory=dict)
    state: str = "unknown"
    capabilities: Dict[str, Any] = field(default_factory=dict)
    unit_of_measurement: Optional[str] = None
    device_class: Optional[str] = None

    @property
    def is_primary(self) -> bool:
        """Check if this is the primary entity."""
        return self.entity_type == EntityType.PRIMARY

    @property
    def is_sensor(self) -> bool:
        """Check if this is a sensor entity."""
        return self.entity_type == EntityType.SENSOR

    @property
    def is_control(self) -> bool:
        """Check if this is a control entity."""
        return self.entity_type in [EntityType.PRIMARY, EntityType.CONTROL]


@dataclass
class DeviceCapabilities:
    """Device capabilities."""
    power_control: bool = False
    brightness_control: bool = False
    color_control: bool = False
    color_temp_control: bool = False
    temperature_control: bool = False
    humidity_control: bool = False
    mode_control: bool = False
    fan_control: bool = False
    swing_control: bool = False
    position_control: bool = False
    tilt_control: bool = False
    lock_control: bool = False
    power_monitoring: bool = False
    energy_monitoring: bool = False
    temperature_sensing: bool = False
    humidity_sensing: bool = False
    pressure_sensing: bool = False
    illuminance_sensing: bool = False

    def to_dict(self) -> Dict[str, bool]:
        """Convert to dictionary."""
        return {
            "power_control": self.power_control,
            "brightness_control": self.brightness_control,
            "color_control": self.color_control,
            "color_temp_control": self.color_temp_control,
            "temperature_control": self.temperature_control,
            "humidity_control": self.humidity_control,
            "mode_control": self.mode_control,
            "fan_control": self.fan_control,
            "swing_control": self.swing_control,
            "position_control": self.position_control,
            "tilt_control": self.tilt_control,
            "lock_control": self.lock_control,
            "power_monitoring": self.power_monitoring,
            "energy_monitoring": self.energy_monitoring,
            "temperature_sensing": self.temperature_sensing,
            "humidity_sensing": self.humidity_sensing,
            "pressure_sensing": self.pressure_sensing,
            "illuminance_sensing": self.illuminance_sensing
        }


@dataclass
class DeviceState:
    """Aggregated device state."""
    power_state: Optional[str] = None       # on/off/unknown
    power_value: Optional[float] = None      # Power in Watts
    energy_today: Optional[float] = None     # Energy today in kWh
    brightness: Optional[int] = None         # Brightness 0-255
    color_temp: Optional[int] = None         # Color temp in mireds
    rgb_color: Optional[Tuple] = None       # RGB color tuple
    temperature: Optional[float] = None      # Temperature
    humidity: Optional[float] = None        # Humidity %
    pressure: Optional[float] = None        # Pressure
    illuminance: Optional[float] = None     # Illuminance in lux
    position: Optional[int] = None          # Position 0-100 (for covers)
    hvac_mode: Optional[str] = None        # HVAC mode
    hvac_action: Optional[str] = None      # HVAC action
    preset_mode: Optional[str] = None       # Preset mode
    fan_mode: Optional[str] = None         # Fan mode
    swing_mode: Optional[str] = None        # Swing mode
    locked: Optional[bool] = None          # Lock state
    volume: Optional[float] = None          # Volume 0-1
    muted: Optional[bool] = None           # Mute state
    playing: Optional[bool] = None         # Playing state
    online: bool = False                   # Device online status

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "power_state": self.power_state,
            "power_value": self.power_value,
            "energy_today": self.energy_today,
            "brightness": self.brightness,
            "color_temp": self.color_temp,
            "rgb_color": self.rgb_color,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "pressure": self.pressure,
            "illuminance": self.illuminance,
            "position": self.position,
            "hvac_mode": self.hvac_mode,
            "hvac_action": self.hvac_action,
            "preset_mode": self.preset_mode,
            "fan_mode": self.fan_mode,
            "swing_mode": self.swing_mode,
            "locked": self.locked,
            "volume": self.volume,
            "muted": self.muted,
            "playing": self.playing,
            "online": self.online
        }


@dataclass
class Device:
    """Device representation."""
    device_id: str                      # HA device ID
    name: str                           # Device name
    device_type: DeviceType              # Device type
    model: Optional[str] = None         # Model
    manufacturer: Optional[str] = None    # Manufacturer
    area_id: Optional[str] = None       # Area ID
    primary_entity_id: Optional[str] = None  # Primary entity for control
    entities: List[Entity] = field(default_factory=list)
    capabilities: DeviceCapabilities = field(default_factory=DeviceCapabilities)
    state: DeviceState = field(default_factory=DeviceState)
    metadata: Dict[str, Any] = field(default_factory=dict)
    via_device_id: Optional[str] = None  # Parent device ID

    @property
    def online(self) -> bool:
        """Get device online status."""
        return self.state.online

    @property
    def entity_ids(self) -> List[str]:
        """Get all entity IDs."""
        return [e.entity_id for e in self.entities]

    @property
    def primary_entity(self) -> Optional[Entity]:
        """Get primary entity."""
        if self.primary_entity_id:
            for entity in self.entities:
                if entity.entity_id == self.primary_entity_id:
                    return entity
        # Fallback to first primary entity
        for entity in self.entities:
            if entity.is_primary:
                return entity
        return None

    @property
    def sensor_entities(self) -> List[Entity]:
        """Get all sensor entities."""
        return [e for e in self.entities if e.is_sensor]

    @property
    def control_entities(self) -> List[Entity]:
        """Get all control entities."""
        return [e for e in self.entities if e.is_control]

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        for entity in self.entities:
            if entity.entity_id == entity_id:
                return entity
        return None

    def has_entity(self, entity_id: str) -> bool:
        """Check if device has entity."""
        return self.get_entity(entity_id) is not None

    def add_entity(self, entity: Entity) -> None:
        """Add entity to device."""
        if not self.has_entity(entity.entity_id):
            self.entities.append(entity)

    def update_entity_state(self, entity_id: str, state: str, attributes: Dict[str, Any]) -> None:
        """Update entity state."""
        entity = self.get_entity(entity_id)
        if entity:
            entity.state = state
            entity.attributes = attributes
            # Update device capabilities based on attributes
            self._update_capabilities_from_attributes(entity)

    def _update_capabilities_from_attributes(self, entity: Entity) -> None:
        """Update capabilities from entity attributes."""
        attrs = entity.attributes

        if entity.domain == "light":
            self.capabilities.power_control = True
            if attrs.get("brightness") is not None:
                self.capabilities.brightness_control = True
            if attrs.get("color_mode") is not None or attrs.get("supported_color_modes"):
                self.capabilities.color_control = True
            if attrs.get("color_temp") is not None or "color_temp" in attrs.get("supported_color_modes", []):
                self.capabilities.color_temp_control = True

        elif entity.domain == "switch":
            self.capabilities.power_control = True

        elif entity.domain == "climate":
            self.capabilities.power_control = True
            self.capabilities.temperature_control = True
            self.capabilities.mode_control = True
            if attrs.get("fan_mode") is not None or "fan_modes" in attrs:
                self.capabilities.fan_control = True
            if attrs.get("swing_mode") is not None or "swing_modes" in attrs:
                self.capabilities.swing_control = True

        elif entity.domain == "cover":
            self.capabilities.power_control = True
            if attrs.get("supported_features", 0) & 4:  # SUPPORT_SET_POSITION
                self.capabilities.position_control = True
            if attrs.get("supported_features", 0) & 8:  # SUPPORT_OPEN_TILT
                self.capabilities.tilt_control = True

        elif entity.domain == "lock":
            self.capabilities.lock_control = True

        elif entity.domain == "media_player":
            self.capabilities.power_control = True

        # Sensor capabilities
        if entity.domain == "sensor" or entity.domain == "binary_sensor":
            device_class = attrs.get("device_class")
            if device_class in ["temperature", "heat", "cold"]:
                self.capabilities.temperature_sensing = True
            elif device_class in ["humidity", "moisture"]:
                self.capabilities.humidity_sensing = True
            elif device_class in ["pressure"]:
                self.capabilities.pressure_sensing = True
            elif device_class in ["illuminance"]:
                self.capabilities.illuminance_sensing = True

        # Power and energy monitoring
        if "power" in entity.name.lower() or "electric_power" in entity.name.lower():
            self.capabilities.power_monitoring = True
        if "energy" in entity.name.lower():
            self.capabilities.energy_monitoring = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "type": self.device_type.value,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "area_id": self.area_id,
            "primary_entity_id": self.primary_entity_id,
            "online": self.online,
            "state": self.state.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "entities": [e.entity_id for e in self.entities],
            "metadata": self.metadata
        }

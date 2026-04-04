"""Configuration management for Home Assistant Gateway."""

import yaml
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union
from pathlib import Path


@dataclass
class HomeAssistantConfig:
    """Home Assistant connection configuration."""
    url: str = "http://localhost:8123"
    auth_type: str = "long_lived_token"  # long_lived_token, username_password, oauth2
    access_token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    cert_path: Optional[str] = None
    verify_ssl: bool = True
    websocket_port: int = 8123


@dataclass
class GatewayConfig:
    """Gateway server configuration."""
    host: str = "0.0.0.0"
    port: int = 8124
    max_connections: int = 100
    idle_timeout: int = 300  # seconds
    log_level: str = "INFO"
    log_file: Optional[str] = None
    pid_file: Optional[str] = None


@dataclass
class DeviceFilterConfig:
    """Device filtering configuration."""
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    include_domains: List[str] = field(default_factory=lambda: ["light", "switch", "sensor", "binary_sensor"])
    exclude_entities: List[str] = field(default_factory=list)
    exclude_ha_entities: bool = field(default=False)  # Exclude all Home Assistant entities if True
    exclude_ha_entity_patterns: List[str] = field(default_factory=list)  # List of regex patterns to exclude HA entities


@dataclass
class CacheConfig:
    """Cache configuration."""
    enabled: bool = True
    ttl: int = 300  # seconds
    max_size: int = 1000


@dataclass
class PerformanceConfig:
    """Performance tuning configuration."""
    batch_size: int = 10
    batch_delay: float = 0.1  # seconds
    reconnect_delay: int = 5  # seconds
    max_reconnect_attempts: int = 10


@dataclass
class KNXIntegrationConfig:
    """KNX integration configuration."""
    enabled: bool = False
    knx_gateway_url: str = "ws://localhost:8125/ws"
    reconnect_interval: int = 5
    max_retries: int = 10
    request_timeout: int = 30


@dataclass
class Config:
    """Main configuration class."""
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    devices: DeviceFilterConfig = field(default_factory=DeviceFilterConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    knx: KNXIntegrationConfig = field(default_factory=KNXIntegrationConfig)

    @classmethod
    def from_file(cls, config_path: Union[str, Path]) -> "Config":
        """Load configuration from YAML file."""
        config_path = Path(config_path)

        if not config_path.exists():
            # Create default config file
            default_config = cls()
            default_config.save(config_path)
            return default_config

        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # Convert dict to dataclass instances
        config = cls()
        if 'home_assistant' in data:
            config.home_assistant = HomeAssistantConfig(**data['home_assistant'])
        if 'gateway' in data:
            config.gateway = GatewayConfig(**data['gateway'])
        if 'devices' in data:
            config.devices = DeviceFilterConfig(**data['devices'])
        if 'cache' in data:
            config.cache = CacheConfig(**data['cache'])
        if 'performance' in data:
            config.performance = PerformanceConfig(**data['performance'])
        if 'knx' in data:
            config.knx = KNXIntegrationConfig(**data['knx'])

        return config

    def save(self, config_path: Union[str, Path]) -> None:
        """Save configuration to YAML file."""
        config_path = Path(config_path)

        # Create directory if it doesn't exist
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'home_assistant': self.home_assistant.__dict__,
            'gateway': self.gateway.__dict__,
            'devices': self.devices.__dict__,
            'cache': self.cache.__dict__,
            'performance': self.performance.__dict__,
            'knx': self.knx.__dict__
        }

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, indent=2)

    def validate(self) -> None:
        """Validate configuration."""
        if not self.home_assistant.url:
            raise ValueError("Home Assistant URL is required")

        if self.home_assistant.auth_type == "long_lived_token" and not self.home_assistant.access_token:
            raise ValueError("Access token is required for long_lived_token auth")

        if self.home_assistant.auth_type == "username_password" and not self.home_assistant.username:
            raise ValueError("Username is required for username_password auth")

        if self.gateway.port < 1 or self.gateway.port > 65535:
            raise ValueError("Gateway port must be between 1 and 65535")

        if not self.devices.include_domains:
            raise ValueError("At least one device domain must be included")


def get_default_config_path() -> Path:
    """Get default configuration file path."""
    home_dir = Path.home()
    return home_dir / ".ha_gateway" / "config.yaml"


def load_or_create_config(config_path: Optional[Union[str, Path]] = None) -> Config:
    """Load configuration file or create default one."""
    if config_path is None:
        config_path = get_default_config_path()

    try:
        config = Config.from_file(config_path)
        config.validate()
        return config
    except Exception as e:
        print(f"Error loading config from {config_path}: {e}")
        print("Creating default configuration...")
        config = Config()
        config.save(config_path)
        return config
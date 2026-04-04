"""Main server for Home Assistant Gateway."""

import asyncio
import logging
import signal
import argparse
from pathlib import Path
from typing import Optional

from core import HomeAssistantGateway
from config import Config, load_or_create_config
from auth import Authenticator
from protocol.websocket import HomeAssistantWebSocket, GatewayWebSocketServer
from device_manager import DeviceManager
from new_device_manager import DeviceManager as NewDeviceManager, DeviceGroupingRule
from state_manager import StateManager
from command_handler import CommandHandler
from client import ClientManager
from knx_integration import KNXIntegration


logger = logging.getLogger(__name__)


class HomeAssistantGatewayServer:
    """Main server class for Home Assistant Gateway."""

    def __init__(self, config_path: Optional[str] = None):
        self.config = load_or_create_config(config_path)
        self.gateway: Optional[HomeAssistantGateway] = None
        self.authenticator: Optional[Authenticator] = None
        self.ha_ws: Optional[HomeAssistantWebSocket] = None
        self.gateway_server: Optional[GatewayWebSocketServer] = None
        self.device_manager: Optional[DeviceManager] = None
        self.new_device_manager: Optional[NewDeviceManager] = None
        self.state_manager: Optional[StateManager] = None
        self.command_handler: Optional[CommandHandler] = None
        self.client_manager: Optional[ClientManager] = None
        self.knx_integration: Optional[KNXIntegration] = None
        self.running = False

    async def start(self) -> None:
        """Start the server."""
        logger.info("Starting Home Assistant Gateway Server")

        # Validate configuration
        self.config.validate()

        # Initialize components
        self.authenticator = Authenticator(self.config)
        await self.authenticator.initialize()

        self.client_manager = ClientManager()
        await self.client_manager.start()

        self.device_manager = DeviceManager(self.config)
        await self.device_manager.initialize()

        # Initialize new device manager
        self.new_device_manager = NewDeviceManager(self.config)
        await self.new_device_manager.start()

        # Set grouping rule
        grouping_rule = DeviceGroupingRule(
            by_device_id=True,
            by_via_device=True,
            by_naming_pattern=True
        )
        self.new_device_manager.set_grouping_rule(grouping_rule)

        # Initialize KNX integration
        self.knx_integration = KNXIntegration(self.config)
        await self.knx_integration.initialize()

        self.ha_ws = HomeAssistantWebSocket(self.config, self.authenticator)

        # Connect to Home Assistant first
        logger.info("Connecting to Home Assistant...")
        await self.ha_ws.connect()

        # Set ha_ws reference for new_device_manager (needed for device registry access)
        if self.new_device_manager:
            self.new_device_manager.ha_ws = self.ha_ws

        self.state_manager = StateManager(self.config, self.ha_ws, self.device_manager, self.new_device_manager, server=self)
        await self.state_manager.start()

        self.command_handler = CommandHandler(self.config, self.device_manager, self.state_manager)
        await self.command_handler.start()

        self.gateway_server = GatewayWebSocketServer(self.config, self.ha_ws, self.new_device_manager)

        # Register device change callback for broadcasting
        if self.new_device_manager:
            self.new_device_manager.add_device_change_callback(self._on_device_change)

        # Connect state changes to gateway broadcasting
        self.device_manager.add_state_callback(self._on_state_change)

        # Start WebSocket server
        logger.info(f"Starting WebSocket server on {self.config.gateway.host}:{self.config.gateway.port}")
        await self.gateway_server.start()

        self.running = True
        logger.info("Home Assistant Gateway Server started successfully")

        # Setup signal handlers
        for sig in [signal.SIGINT, signal.SIGTERM]:
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.stop())
            )

    async def stop(self) -> None:
        """Stop the server."""
        if not self.running:
            return

        logger.info("Stopping Home Assistant Gateway Server")
        self.running = False

        # Stop components in reverse order with error handling
        components = [
            ('gateway_server', self.gateway_server, lambda c: c.stop()),
            ('command_handler', self.command_handler, lambda c: c.stop()),
            ('state_manager', self.state_manager, lambda c: c.stop()),
            ('ha_ws', self.ha_ws, lambda c: c.disconnect()),
            ('authenticator', self.authenticator, lambda c: c.close()),
            ('client_manager', self.client_manager, lambda c: c.stop()),
            ('knx_integration', self.knx_integration, lambda c: c.stop()),
        ]

        for name, component, stop_fn in components:
            if component:
                try:
                    await asyncio.wait_for(stop_fn(component), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout stopping {name}")
                except Exception as e:
                    logger.warning(f"Error stopping {name}: {e}")

        logger.info("Home Assistant Gateway Server stopped")

    async def _on_state_change(self, entity_id: str, state) -> None:
        """Handle state changes."""
        if self.gateway_server:
            await self.gateway_server.broadcast_state_change(entity_id, state.to_dict())

        # Sync state to KNX if integration is enabled
        if self.knx_integration and self.knx_integration.config.knx.enabled:
            # Find device ID from entity ID
            device_id = entity_id.split('.')[1]  # e.g., "light.living_room" -> "living_room"

            # Check if device has KNX mapping
            if self.knx_integration.get_knx_mapping(device_id):
                # Convert state to KNX format and sync
                await self.knx_integration.sync_to_knx(
                    device_id,
                    state.to_dict()
                )

    async def _on_device_change(self, device_id: str, device) -> None:
        """Handle device state changes."""
        logger.info(f"Device change detected: {device_id} (type: {device.device_type})")

        if self.gateway_server:
            await self.gateway_server.broadcast_device_state_change(device_id, device)

        # Check if KNX integration is enabled and device needs KNX address
        if self.knx_integration and self.knx_integration.config.knx.enabled:
            # Only register devices that support KNX
            is_compatible = self._is_device_knx_compatible(device)
            logger.debug(f"Device {device_id} KNX compatibility check: {is_compatible}")

            if is_compatible:
                logger.info(f"New KNX-compatible device detected: {device_id}")

                # Get device info for KNX registration
                # Build entities list with full entity info for individual KNX address allocation
                entities_info = []
                if hasattr(device, 'entities'):
                    for entity in device.entities:
                        entities_info.append({
                            "entity_id": entity.entity_id,
                            "domain": entity.domain,
                            "entity_type": entity.domain,  # Use domain as entity_type
                            "name": entity.name
                        })

                device_info = {
                    "id": device_id,
                    "name": getattr(device, 'name', device_id),
                    "type": device.device_type.value if hasattr(device.device_type, 'value') else str(device.device_type),
                    "capabilities": self._get_device_capabilities(device),
                    "entities": entities_info  # Full entity info for per-entity KNX address allocation
                }

                logger.info(f"Registering device with KNX Gateway: {device_info}")

                # Request KNX address
                knx_address = await self.knx_integration.request_knx_address(
                    device_id,
                    device_info
                )

                if knx_address:
                    logger.info(f"KNX address allocated for {device_id}: {knx_address}")
                else:
                    logger.warning(f"Failed to allocate KNX address for {device_id}")

                    # Store mapping and sync initial state
                    knx_mapping = self.knx_integration.get_knx_mapping(device_id)
                    if knx_mapping and hasattr(device, 'entities'):
                        # Sync initial state to KNX
                        for entity_id in device.entities:
                            entity_state = await self.state_manager.get_entity_state(entity_id)
                            if entity_state:
                                await self.knx_integration.sync_to_knx(
                                    entity_id,
                                    entity_state.to_dict()
                                )

    async def get_server_stats(self) -> dict:
        """Get server statistics."""
        stats = {
            "running": self.running,
            "config": {
                "gateway_host": self.config.gateway.host,
                "gateway_port": self.config.gateway.port,
                "ha_url": self.config.home_assistant.url,
                "ha_auth_type": self.config.home_assistant.auth_type
            }
        }

        if self.client_manager:
            stats["clients"] = await self.client_manager.get_client_stats()

        if self.device_manager:
            devices = self.device_manager.get_devices()
            stats["devices"] = {
                "total": len(devices),
                "by_domain": {}
            }
            for device in devices:
                domain = device.domain
                if domain not in stats["devices"]["by_domain"]:
                    stats["devices"]["by_domain"][domain] = 0
                stats["devices"]["by_domain"][domain] += 1

        # Add KNX integration stats

    def _is_device_knx_compatible(self, device) -> bool:
        """Check if a device is KNX compatible."""
        # KNX compatible device types
        from device_models import DeviceType
        knx_types = [DeviceType.LIGHT, DeviceType.SWITCH, DeviceType.COVER,
                    DeviceType.CLIMATE, DeviceType.FAN, DeviceType.LOCK]

        logger.info(f"Checking KNX compatibility for device {device.device_id}: type={device.device_type}")

        # Check device type
        if device.device_type in knx_types:
            logger.info(f"  Device type {device.device_type} is KNX compatible")
        elif device.device_type == DeviceType.UNKNOWN:
            # For UNKNOWN type, check if any entity is KNX compatible
            for entity in device.entities:
                entity_domain = entity.domain
                if entity_domain in ['light', 'switch', 'cover', 'climate', 'fan', 'lock']:
                    # Entity is KNX compatible, treat device as compatible
                    logger.info(f"  Found KNX-compatible entity: {entity.entity_id} (domain: {entity_domain})")
                    return True
            logger.info(f"  No KNX-compatible entities found in device")
            return False
        else:
            logger.info(f"  Device type {device.device_type} is not KNX compatible")
            return False

        # Check if device has at least one KNX-capable capability
        capabilities = self._get_device_capabilities(device)
        logger.info(f"  Device capabilities: {capabilities}")
        knx_capabilities = ['power_control', 'position_control', 'temperature_control', 'brightness_control']

        is_compatible = any(cap in capabilities for cap in knx_capabilities)
        logger.info(f"  Has KNX capabilities: {is_compatible}")
        return is_compatible

    def _get_device_capabilities(self, device) -> list:
        """Get KNX capabilities for a device."""
        capabilities = []

        # Get capabilities from device.capabilities object
        if hasattr(device, 'capabilities') and device.capabilities:
            caps_dict = device.capabilities.to_dict()
            for cap_name, cap_value in caps_dict.items():
                if cap_value and cap_name not in ['temperature_sensing', 'humidity_sensing',
                                                      'pressure_sensing', 'illuminance_sensing']:
                    # Add capability (convert from snake_case to camel_case if needed)
                    capabilities.append(cap_name)

        # Fallback: check device state for basic power control
        if hasattr(device, 'state') and device.state.power_state in ['on', 'off']:
            if 'power_control' not in capabilities:
                capabilities.append('power_control')

        return capabilities

        # Temperature control (climate devices)
        if hasattr(device, 'temperature') and device.temperature is not None:
            capabilities.append('temperature_control')

        # Fan speed control
        if hasattr(device, 'fan_mode') and device.fan_mode is not None:
            capabilities.append('fan_speed_control')

        return capabilities
        if self.knx_integration:
            stats["knx_integration"] = {
                "enabled": self.config.knx.enabled,
                "connected": self.knx_integration.connected,
                "registered_devices": len(self.knx_integration.device_mappings),
                "sync_queue_size": self.knx_integration.sync_queue.qsize()
            }

        return stats


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Home Assistant Gateway Server")
    parser.add_argument(
        "--config",
        help="Path to configuration file",
        default=None
    )
    parser.add_argument(
        "--log-level",
        help="Log level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    server = HomeAssistantGatewayServer(args.config)

    try:
        await server.start()
        # Keep running until stopped
        while server.running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
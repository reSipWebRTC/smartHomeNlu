"""KNX Integration for Home Assistant Gateway.

This module handles the integration between Home Assistant Gateway and KNX Gateway.
It manages device registration, state synchronization, and KNX address mapping.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
import websockets
from dataclasses import asdict

from config import Config

logger = logging.getLogger(__name__)


class KNXIntegration:
    """KNX Integration Manager for HA Gateway."""

    def __init__(self, config: Config):
        """Initialize KNX integration."""
        self.config = config
        self.knx_gateway_url = config.knx.knx_gateway_url
        self.reconnect_interval = config.knx.reconnect_interval
        self.max_retries = config.knx.max_retries
        self.request_timeout = config.knx.request_timeout

        # WebSocket client
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False

        # Device mappings
        self.device_mappings: Dict[str, Dict] = {}  # device_id -> knx_mapping (legacy)
        self.entity_mappings: Dict[str, Dict] = {}  # entity_id -> knx_mapping (new)
        self.knx_to_device: Dict[str, str] = {}  # knx_group -> device_id (legacy)
        self.knx_to_entity: Dict[str, str] = {}  # knx_group -> entity_id (new)

        # Message counter
        self.message_counter = 0

        # State sync queue
        self.sync_queue = asyncio.Queue(maxsize=100)
        self.sync_task: Optional[asyncio.Task] = None

        # Response waiting - for correlation between requests and responses
        self.pending_responses: Dict[str, asyncio.Future] = {}  # message_id -> Future

    async def initialize(self):
        """Initialize KNX integration."""
        logger.info("Initializing KNX integration")
        logger.info(f"KNX config: enabled={self.config.knx.enabled}, url={self.config.knx.knx_gateway_url}")

        if not self.config.knx.enabled:
            logger.info("KNX integration disabled")
            return

        # Connect to KNX Gateway
        await self.connect_to_knx_gateway()

        # Start sync processing
        self.sync_task = asyncio.create_task(self._process_sync_queue())

    async def start(self):
        """Start KNX integration."""
        logger.info("Starting KNX integration")

    async def stop(self):
        """Stop KNX integration."""
        logger.info("Stopping KNX integration")

        # Cancel sync task
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass

        # Disconnect from KNX Gateway
        if self.websocket:
            await self.websocket.close()

        self.connected = False

    async def connect_to_knx_gateway(self):
        """Connect to KNX Gateway WebSocket."""
        # Only try 3 times for initial connection, then continue without KNX
        max_initial_retries = 3
        retry_count = 0
        logger.info(f"Starting KNX Gateway connection (max {max_initial_retries} attempts)")

        while retry_count < max_initial_retries and not self.connected:
            try:
                logger.info(f"Attempting connection {retry_count + 1}/{max_initial_retries} to {self.knx_gateway_url}")

                self.websocket = await asyncio.wait_for(
                    websockets.connect(
                        self.knx_gateway_url,
                        ping_interval=30,
                        ping_timeout=10
                    ),
                    timeout=5  # 5 second timeout per attempt
                )

                # Send hello message
                hello_msg = {
                    "type": "hello",
                    "id": f"ha_gateway_{self.message_counter}",
                    "payload": {
                        "version": "1.0.0",
                        "role": "ha_gateway"
                    }
                }
                await self.websocket.send(json.dumps(hello_msg))

                self.connected = True
                logger.info("Connected to KNX Gateway")

                # Start listening for messages
                asyncio.create_task(self._listen_to_knx_gateway())

            except asyncio.TimeoutError:
                retry_count += 1
                logger.warning(f"Connection attempt {retry_count} timed out")
            except Exception as e:
                retry_count += 1
                logger.warning(f"Connection attempt {retry_count} failed: {e}")

            if retry_count < max_initial_retries and not self.connected:
                await asyncio.sleep(self.reconnect_interval)

        if not self.connected:
            logger.warning("KNX Gateway unavailable after 3 attempts - continuing without KNX integration")

    async def _listen_to_knx_gateway(self):
        """Listen for messages from KNX Gateway."""
        logger.info("Starting to listen for KNX Gateway messages")
        try:
            async for message in self.websocket:
                logger.info(f"Received message from KNX Gateway")
                data = json.loads(message)
                logger.info(f"Message type: {data.get('type')}, id: {data.get('id')}")
                await self._handle_knx_message(data)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection to KNX Gateway closed")
            self.connected = False
            # Attempt to reconnect
            asyncio.create_task(self._reconnect())
        except Exception as e:
            logger.error(f"Error listening to KNX Gateway: {e}")

    async def _handle_knx_message(self, data: Dict):
        """Handle message from KNX Gateway."""
        msg_type = data.get("type")
        msg_id = data.get("id")

        if msg_type == "address_assigned":
            await self._handle_address_assigned(data)

            # Check if any pending response is waiting for this message
            # KNX Gateway sends IDs like "register_0_response", we need to match with "register_0"
            response_id = None
            if msg_id:
                # Try direct match first
                if msg_id in self.pending_responses:
                    response_id = msg_id
                # Try removing "_response" suffix
                elif msg_id.endswith("_response"):
                    original_id = msg_id[:-9]  # Remove "_response" suffix
                    if original_id in self.pending_responses:
                        response_id = original_id

            if response_id:
                # Resolve the future with this response
                future = self.pending_responses.pop(response_id)
                if not future.done():
                    future.set_result(data)

        elif msg_type == "knx_state_update":
            await self._handle_knx_state_update(data)
        elif msg_type == "error":
            logger.error(f"KNX Gateway error: {data}")

            # Check if any pending response is waiting
            response_id = None
            if msg_id:
                # Try direct match first
                if msg_id in self.pending_responses:
                    response_id = msg_id
                # Try removing "_response" suffix
                elif msg_id.endswith("_response"):
                    original_id = msg_id[:-9]  # Remove "_response" suffix
                    if original_id in self.pending_responses:
                        response_id = original_id
                # Try without suffix
                elif msg_id in self.pending_responses:
                    response_id = msg_id

            if response_id:
                future = self.pending_responses.pop(response_id)
                if not future.done():
                    future.set_exception(Exception(f"KNX Gateway error: {data}"))

        elif msg_type == "heartbeat":
            # Heartbeat response
            pass

    async def _handle_address_assigned(self, data: Dict):
        """Handle address assignment response.

        Supports both legacy mode (single device address) and entity mode (per-entity addresses).
        """
        payload = data.get("payload", {})
        device_id = payload.get("device_id")
        address_info = payload.get("address_info")  # Legacy mode
        entity_addresses = payload.get("entity_addresses", [])  # Entity mode

        # Handle entity mode (new)
        if entity_addresses:
            logger.info(f"Processing {len(entity_addresses)} entity addresses for device {device_id}")

            for entity_addr in entity_addresses:
                entity_id = entity_addr.get("entity_id")
                if not entity_id:
                    continue

                # Store entity-level mapping
                self.entity_mappings[entity_id] = {
                    "device_id": device_id,
                    "physical_address": entity_addr.get("physical_address"),
                    "entity_type": entity_addr.get("entity_type"),
                    "group_addresses": entity_addr.get("group_addresses", {}),
                    "dpt_types": entity_addr.get("dpt_types", {}),
                    "registered_at": payload.get("timestamp")
                }

                # Update reverse mapping (group address -> entity)
                group_addresses = entity_addr.get("group_addresses", {})
                for char, group_addr in group_addresses.items():
                    self.knx_to_entity[group_addr] = entity_id

                logger.info(f"KNX address allocated for entity {entity_id}: {entity_addr.get('physical_address')}")

            # Also store device-level mapping for backward compatibility
            device_address = payload.get("device_address")
            if device_address:
                self.device_mappings[device_id] = {
                    "physical_address": device_address.get("physical_address"),
                    "group_addresses": device_address.get("group_addresses", {}),
                    "dpt_types": device_address.get("dpt_types", {}),
                    "entity_count": payload.get("entity_count", 0),
                    "registered_at": payload.get("timestamp")
                }

        # Handle legacy mode (single device address)
        elif device_id and address_info:
            # Store mapping
            self.device_mappings[device_id] = {
                "physical_address": address_info.get("physical_address"),
                "group_addresses": address_info.get("group_addresses", {}),
                "dpt_types": address_info.get("dpt_types", {}),
                "registered_at": payload.get("timestamp")
            }

            # Update reverse mapping
            group_addresses = address_info.get("group_addresses", {})
            for char, group_addr in group_addresses.items():
                self.knx_to_device[group_addr] = device_id

            logger.info(f"KNX address allocated for device {device_id}: {address_info.get('physical_address')}")

    async def _handle_knx_state_update(self, data: Dict):
        """Handle KNX state update from KNX Gateway."""
        payload = data.get("payload", {})
        knx_address = payload.get("knx_address")
        value = payload.get("value")
        device_id = payload.get("device_id")

        # Forward to HA Gateway state management
        # This would typically be handled by the state manager
        logger.info(f"KNX state update: {device_id} -> {knx_address} = {value}")

    async def request_knx_address(self, device_id: str, device_info: Dict) -> Optional[Dict]:
        """Request KNX address for a device.

        Args:
            device_id: Device ID
            device_info: Device information dict with optional 'entities' list

        Returns:
            Response payload from KNX Gateway
        """
        if not self.connected:
            logger.error("Not connected to KNX Gateway")
            return None

        try:
            # Build entities list for registration
            entities = device_info.get("entities", [])

            # Build entities payload for KNX Gateway
            entities_payload = []
            for entity in entities:
                if isinstance(entity, dict):
                    entities_payload.append({
                        "entity_id": entity.get("entity_id"),
                        "domain": entity.get("domain"),
                        "entity_type": entity.get("domain"),  # Use domain as entity_type
                        "name": entity.get("name")
                    })

            # Send registration request
            message = {
                "type": "register_device",
                "id": f"register_{self.message_counter}",
                "payload": {
                    "device_id": device_id,
                    "device_name": device_info.get("name", device_id),
                    "device_type": device_info.get("type", "unknown"),
                    "capabilities": device_info.get("capabilities", []),
                    "entities": entities_payload  # Send entities for individual address allocation
                }
            }

            self.message_counter += 1

            logger.info(f"Sending device registration request to KNX Gateway: {device_id}")
            logger.info(f"  Including {len(entities_payload)} entities for individual address allocation")
            logger.debug(f"Registration message: {json.dumps(message)}")

            # Send and wait for response
            await self.websocket.send(json.dumps(message))

            # Wait for response with timeout
            response = await asyncio.wait_for(
                self._wait_for_response(message["id"]),
                timeout=self.request_timeout
            )

            return response.get("payload")

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for KNX address for device {device_id}")
            return None
        except Exception as e:
            logger.error(f"Error requesting KNX address: {e}")
            return None

    async def _wait_for_response(self, message_id: str, timeout: float = 30) -> Dict:
        """Wait for response to a specific message."""
        # Create a future for the response
        future = asyncio.Future()

        # Register the future
        self.pending_responses[message_id] = future

        try:
            # Wait for the response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            # Remove from pending responses
            self.pending_responses.pop(message_id, None)
            logger.error(f"Timeout waiting for response to message {message_id}")
            raise
        except Exception as e:
            # Remove from pending responses
            self.pending_responses.pop(message_id, None)
            logger.error(f"Error waiting for response to message {message_id}: {e}")
            raise

    async def sync_to_knx(self, device_id: str, state: Dict) -> bool:
        """Sync device state to KNX."""
        if not self.connected:
            logger.error("Not connected to KNX Gateway")
            return False

        # Add to sync queue
        try:
            await self.sync_queue.put({
                "device_id": device_id,
                "state": state,
                "timestamp": asyncio.get_event_loop().time()
            })
            return True
        except asyncio.QueueFull:
            logger.warning("Sync queue full, dropping state update")
            return False

    async def _process_sync_queue(self):
        """Process sync queue with batching."""
        batch = []
        batch_delay = self.config.performance.batch_delay

        while self.connected:
            try:
                # Get next item from queue
                item = await asyncio.wait_for(self.sync_queue.get(), timeout=1.0)
                batch.append(item)

                # Process batch if reached batch size or timeout
                if len(batch) >= self.config.performance.batch_size or batch_delay:
                    if batch:
                        await self._send_sync_batch(batch)
                        batch = []

                    if batch_delay:
                        await asyncio.sleep(batch_delay)

            except asyncio.TimeoutError:
                # Process remaining items in batch
                if batch:
                    await self._send_sync_batch(batch)
                    batch = []

    async def _send_sync_batch(self, batch: List[Dict]):
        """Send a batch of sync messages."""
        if not self.connected:
            return

        for item in batch:
            message = {
                "type": "sync_state_to_knx",
                "id": f"sync_{self.message_counter}",
                "payload": {
                    "device_id": item["device_id"],
                    "state": item["state"]
                }
            }

            try:
                await self.websocket.send(json.dumps(message))
                self.message_counter += 1
            except Exception as e:
                logger.error(f"Error sending sync message: {e}")

    async def _reconnect(self):
        """Reconnect to KNX Gateway."""
        logger.info("Attempting to reconnect to KNX Gateway...")

        await asyncio.sleep(self.reconnect_interval)

        if not self.connected:
            await self.connect_to_knx_gateway()

    def get_knx_mapping(self, device_id: str) -> Optional[Dict]:
        """Get KNX mapping for device."""
        return self.device_mappings.get(device_id)

    def get_entity_knx_mapping(self, entity_id: str) -> Optional[Dict]:
        """Get KNX mapping for a specific entity."""
        return self.entity_mappings.get(entity_id)

    def get_device_entities_knx_mapping(self, device_id: str) -> Dict[str, Dict]:
        """Get all entity KNX mappings for a device."""
        result = {}
        for entity_id, mapping in self.entity_mappings.items():
            if mapping.get("device_id") == device_id:
                result[entity_id] = mapping
        return result

    def get_device_from_knx(self, knx_group: str) -> Optional[str]:
        """Get device ID from KNX group address."""
        # First try entity mapping
        entity_id = self.knx_to_entity.get(knx_group)
        if entity_id:
            entity_mapping = self.entity_mappings.get(entity_id)
            if entity_mapping:
                return entity_mapping.get("device_id")

        # Fallback to legacy device mapping
        return self.knx_to_device.get(knx_group)

    def get_entity_from_knx(self, knx_group: str) -> Optional[str]:
        """Get entity ID from KNX group address."""
        return self.knx_to_entity.get(knx_group)
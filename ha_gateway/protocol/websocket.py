"""WebSocket protocol implementation for Home Assistant Gateway.

This implementation uses only WebSocket API for all interactions with Home Assistant.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Callable, List
from enum import Enum
from collections import defaultdict
import aiohttp
from aiohttp import web, WSMsgType

from config import Config
from .message import Message, MessageType, create_response, create_error, create_state_update, create_device_list, create_device_state_update


logger = logging.getLogger(__name__)


class HACommandType(Enum):
    """Home Assistant WebSocket command types."""
    AUTH = "auth"
    AUTH_REQUIRED = "auth_required"
    AUTH_OK = "auth_ok"
    AUTH_INVALID = "auth_invalid"
    AUTH_OK_OLD = "auth_ok/old"
    PING = "ping"
    PONG = "pong"
    SUBSCRIBE_EVENTS = "subscribe_events"
    UNSUBSCRIBE_EVENTS = "unsubscribe_events"
    FIRE_EVENT = "fire_event"
    CALL_SERVICE = "call_service"
    GET_STATES = "get_states"
    GET_CONFIG = "get_config"
    GET_SERVICES = "get_services"
    GET_PANELS = "get_panels"
    RESULT = "result"
    EVENT = "event"
    ERROR = "error"
    SUPPORTED_FEATURES = "supported_features"


class HomeAssistantWebSocket:
    """WebSocket client for connecting to Home Assistant using only WebSocket API."""

    def __init__(self, config: Config, authenticator):
        self.config = config
        self.authenticator = authenticator
        self.websocket: Optional[aiohttp.ClientWebSocketResponse] = None
        self.message_handlers: Dict[int, asyncio.Future] = {}
        self.event_subscriptions: Dict[int, Callable] = {}
        self.state_handlers: List[Callable] = []
        self.connected = False
        self._auth_complete = False
        self._auth_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._message_id = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._initial_states: Optional[List[Dict[str, Any]]] = None
        self._entity_registry: Optional[Dict[str, Dict[str, Any]]] = None  # entity_id -> entity registry data
        self._device_registry: Optional[Dict[str, Dict[str, Any]]] = None  # device_id -> device registry data

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=False),
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def connect(self) -> None:
        """Connect to Home Assistant WebSocket."""
        if self.connected:
            return

        try:
            ws_url = self.config.home_assistant.url.replace("http", "ws") + "/api/websocket"

            logger.info(f"Connecting to {ws_url}")
            self.websocket = await self.session.ws_connect(
                ws_url,
                ssl=False  # Configure SSL in production
            )

            self.connected = True
            logger.info("Connected to Home Assistant WebSocket")

            # Start message processing task
            asyncio.create_task(self._process_messages())

            # Wait for authentication
            await self._wait_for_auth()

        except Exception as e:
            logger.error(f"Failed to connect to Home Assistant: {e}")
            self.connected = False
            raise

    async def disconnect(self) -> None:
        """Disconnect from Home Assistant WebSocket."""
        logger.info("Disconnecting from Home Assistant")
        self.connected = False

        # Cancel reconnection task if running
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()

        # Cancel pending message handlers
        for future in self.message_handlers.values():
            if not future.done():
                future.cancel()

    async def close(self) -> None:
        """Close the WebSocket client and session."""
        await self.disconnect()
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_command(self, command_type: str, **kwargs) -> Dict[str, Any]:
        """Send a command to Home Assistant via WebSocket.

        Args:
            command_type: The WebSocket command type (e.g., 'get_states', 'call_service')
            **kwargs: Additional parameters for the command

        Returns:
            The result from the WebSocket response

        Raises:
            ConnectionError: If not connected to Home Assistant
            TimeoutError: If response timeout occurs
            Exception: If command execution fails
        """
        if not self.connected or not self._auth_complete:
            raise ConnectionError("Not connected to Home Assistant")

        async with self._lock:
            self._message_id += 1
            message_id = self._message_id

        message = {
            "id": message_id,
            "type": command_type,
            **kwargs
        }

        # Store future for this response
        future = asyncio.Future()
        self.message_handlers[message_id] = future

        # Send message
        logger.debug(f"Sending command: {command_type} (id={message_id})")
        try:
            await self.websocket.send_json(message)
        except Exception as e:
            # Clean up if send fails
            if message_id in self.message_handlers:
                del self.message_handlers[message_id]
            raise ConnectionError(f"Failed to send message: {e}")

        # Wait for response
        try:
            response_data = await asyncio.wait_for(future, timeout=30)
            logger.debug(f"Received response for {message_id}: {json.dumps(response_data, indent=2, ensure_ascii=False)}")

            # Check for error in response
            if response_data.get("type") == HACommandType.RESULT.value:
                if not response_data.get("success", True):
                    error = response_data.get("error", {})
                    error_msg = error.get("message", "Unknown error")
                    error_code = error.get("code", "unknown")
                    raise Exception(f"Command failed: {error_msg} (code: {error_code})")
                return response_data
            elif response_data.get("type") == HACommandType.ERROR.value:
                error = response_data.get("error", {})
                raise Exception(f"Error response: {error.get('message', 'Unknown error')}")
            else:
                return response_data

        except asyncio.TimeoutError:
            if message_id in self.message_handlers:
                del self.message_handlers[message_id]
            logger.error(f"Timeout waiting for response to message {message_id}")
            raise TimeoutError(f"Timeout waiting for response to command: {command_type}")

    async def get_states(self, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get states from Home Assistant via WebSocket.

        Args:
            entity_id: Optional entity ID to get specific entity state

        Returns:
            List of state dictionaries

        Raises:
            ConnectionError: If not connected
            TimeoutError: If response timeout
            Exception: If command fails
        """
        if entity_id:
            # For single entity, use HTTP-style URL on WebSocket
            # WebSocket API doesn't have direct single entity get, so get all and filter
            response = await self.send_command(HACommandType.GET_STATES.value)
            all_states = response.get("result", [])
            for state in all_states:
                if state.get("entity_id") == entity_id:
                    return [state]
            return []
        else:
            response = await self.send_command(HACommandType.GET_STATES.value)
            return response.get("result", [])

    def get_entity_registry_data(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get entity registry data for a specific entity.

        Args:
            entity_id: The entity ID to look up

        Returns:
            Entity registry data including device_id, or None if not found
        """
        if self._entity_registry:
            return self._entity_registry.get(entity_id)
        return None

    def get_device_id_for_entity(self, entity_id: str) -> Optional[str]:
        """Get the device_id for a specific entity.

        Args:
            entity_id: The entity ID to look up

        Returns:
            The device_id if the entity is associated with a device, None otherwise
        """
        entity_data = self.get_entity_registry_data(entity_id)
        if entity_data:
            return entity_data.get("device_id")
        return None

    def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get device registry data for a specific device.

        Args:
            device_id: The device ID to look up

        Returns:
            Device registry data including name, model, manufacturer, or None if not found
        """
        if self._device_registry:
            return self._device_registry.get(device_id)
        return None

    def get_device_name(self, device_id: str) -> Optional[str]:
        """Get the device name from device registry.

        Args:
            device_id: The device ID to look up

        Returns:
            The device name if found, None otherwise
        """
        device_info = self.get_device_info(device_id)
        if device_info:
            return device_info.get("name")
        return None

    def get_device_model_info(self, device_id: str) -> tuple:
        """Get device model and manufacturer from device registry.

        Args:
            device_id: The device ID to look up

        Returns:
            Tuple of (model, manufacturer) - either may be None if not found
        """
        device_info = self.get_device_info(device_id)
        if device_info:
            return device_info.get("model"), device_info.get("manufacturer")
        return None, None

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: Optional[Dict[str, Any]] = None,
        target: Optional[Dict[str, Any]] = None,
        return_response: bool = False
    ) -> Dict[str, Any]:
        """Call a service on Home Assistant via WebSocket.

        Args:
            domain: Domain of the service (e.g., 'light', 'switch')
            service: Service name (e.g., 'turn_on', 'turn_off')
            service_data: Optional service parameters
            target: Optional target specification (entity_id, area_id, etc.)
            return_response: Whether to return service response

        Returns:
            Service call result including context and optional response data

        Raises:
            ConnectionError: If not connected
            TimeoutError: If response timeout
            Exception: If command fails
        """
        kwargs = {
            "domain": domain,
            "service": service
        }
        if service_data:
            kwargs["service_data"] = service_data
        if target:
            kwargs["target"] = target
        if return_response:
            kwargs["return_response"] = True

        return await self.send_command(HACommandType.CALL_SERVICE.value, **kwargs)

    async def subscribe_events(
        self,
        event_type: Optional[str] = None,
        handler: Optional[Callable] = None
    ) -> int:
        """Subscribe to Home Assistant events via WebSocket.

        Args:
            event_type: Event type to subscribe to (None for all events)
            handler: Async callback function for handling events

        Returns:
            Subscription ID

        Raises:
            ConnectionError: If not connected
            Exception: If subscription fails
        """
        kwargs = {}
        if event_type:
            kwargs["event_type"] = event_type

        result = await self.send_command(HACommandType.SUBSCRIBE_EVENTS.value, **kwargs)

        # Store handler for this subscription
        message_id = result.get("id", 0)
        if handler:
            self.event_subscriptions[message_id] = handler

        return message_id

    async def unsubscribe_events(self, subscription: int) -> bool:
        """Unsubscribe from Home Assistant events.

        Args:
            subscription: The subscription ID to unsubscribe

        Returns:
            True if successful

        Raises:
            ConnectionError: If not connected
            Exception: If unsubscription fails
        """
        result = await self.send_command(
            HACommandType.UNSUBSCRIBE_EVENTS.value,
            subscription=subscription
        )

        # Remove handler
        if subscription in self.event_subscriptions:
            del self.event_subscriptions[subscription]

        return result.get("success", False)

    async def fire_event(
        self,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Fire an event on Home Assistant event bus via WebSocket.

        Args:
            event_type: Event type to fire
            event_data: Optional event data

        Returns:
            Event firing result including context

        Raises:
            ConnectionError: If not connected
            TimeoutError: If response timeout
            Exception: If command fails
        """
        kwargs = {"event_type": event_type}
        if event_data:
            kwargs["event_data"] = event_data

        return await self.send_command(HACommandType.FIRE_EVENT.value, **kwargs)

    async def ping(self) -> float:
        """Send a ping to Home Assistant and wait for pong.

        Returns:
            Round-trip time in seconds

        Raises:
            ConnectionError: If not connected
            TimeoutError: If pong timeout
        """
        start_time = asyncio.get_event_loop().time()
        await self.send_command(HACommandType.PING.value)
        # Pong is handled in _process_messages
        return asyncio.get_event_loop().time() - start_time

    async def subscribe_state_changes(self, handler: Optional[Callable] = None) -> int:
        """Subscribe to state_changed events.

        Args:
            handler: Async callback function for handling state changes

        Returns:
            Subscription ID
        """
        logger.info("Subscribing to state_changed events...")
        if handler:
            self.state_handlers.append(handler)
            logger.info(f"Added state handler: {handler}")

        subscription_id = await self.subscribe_events("state_changed", handler)
        logger.info(f"Subscribed to state_changed events with ID: {subscription_id}")
        return subscription_id

    async def fetch_initial_states(self) -> List[Dict[str, Any]]:
        """Fetch initial states after connecting to Home Assistant.

        Returns:
            List of state dictionaries
        """
        logger.info("Fetching initial states from Home Assistant...")
        states = await self.get_states()
        self._initial_states = states
        logger.info(f"Retrieved {len(states)} states from Home Assistant")
        return states

    async def fetch_entity_registry(self) -> Dict[str, Dict[str, Any]]:
        """Fetch entity registry from Home Assistant.

        Returns:
            Dictionary mapping entity_id to entity registry data (including device_id)
        """
        logger.info("Fetching entity registry from Home Assistant...")
        try:
            response = await self.send_command("config/entity_registry/list")
            entities = response.get("result", [])

            # Create a dictionary mapping entity_id to registry data
            entity_registry = {}
            for entity in entities:
                entity_id = entity.get("entity_id")
                if entity_id:
                    entity_registry[entity_id] = entity

            self._entity_registry = entity_registry
            logger.info(f"Retrieved {len(entity_registry)} entities from entity registry")
            return entity_registry
        except Exception as e:
            logger.error(f"Failed to fetch entity registry: {e}")
            return {}

    async def fetch_device_registry(self) -> Dict[str, Dict[str, Any]]:
        """Fetch device registry from Home Assistant.

        Returns:
            Dictionary mapping device_id to device registry data (including name, model, manufacturer)
        """
        logger.info("Fetching device registry from Home Assistant...")
        try:
            response = await self.send_command("config/device_registry/list")
            devices = response.get("result", [])

            # Create a dictionary mapping device_id to device data
            device_registry = {}
            for device in devices:
                device_id = device.get("id")
                if device_id:
                    device_registry[device_id] = device

            self._device_registry = device_registry
            logger.info(f"Retrieved {len(device_registry)} devices from device registry")
            return device_registry
        except Exception as e:
            logger.error(f"Failed to fetch device registry: {e}")
            return {}

    async def _process_messages(self) -> None:
        """Process incoming WebSocket messages."""
        while self.connected:
            try:
                msg = await self.websocket.receive()

                if msg.type == WSMsgType.TEXT:
                    try:
                        data = msg.json()
                        # Handle coalesced messages (array format)
                        if isinstance(data, list):
                            for message in data:
                                await self._handle_message(message)
                        else:
                            await self._handle_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode JSON: {e}")
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self.websocket.exception()}")
                    break
                elif msg.type == WSMsgType.CLOSED:
                    logger.info("WebSocket connection closed")
                    break
                elif msg.type == WSMsgType.CLOSING:
                    logger.debug("WebSocket connection closing")
                    break

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                break

        self.connected = False
        self._auth_complete = False
        self._auth_event.clear()

        # Attempt to reconnect
        if not self._reconnect_task or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")
        message_id = data.get("id")

        # Authentication messages
        if msg_type == HACommandType.AUTH_REQUIRED.value:
            await self._handle_auth_required(data)
        elif msg_type == HACommandType.AUTH_OK.value:
            await self._handle_auth_ok(data)
        elif msg_type == HACommandType.AUTH_INVALID.value:
            await self._handle_auth_invalid(data)

        # Event messages
        elif msg_type == HACommandType.EVENT.value:
            await self._handle_event(data)

        # Result messages (responses to commands)
        elif msg_type == HACommandType.RESULT.value:
            await self._handle_result(data)

        # Error messages
        elif msg_type == HACommandType.ERROR.value:
            await self._handle_error(data)

        # Pong messages
        elif msg_type == HACommandType.PONG.value:
            logger.debug("Received pong from Home Assistant")

        else:
            logger.debug(f"Unhandled message type: {msg_type}")

    async def _handle_auth_required(self, data: Dict[str, Any]) -> None:
        """Handle auth_required message from Home Assistant."""
        logger.debug("Received auth_required from Home Assistant")

        # Get access token from authenticator
        access_token = self.config.home_assistant.access_token

        if not access_token:
            # Try to get from authenticator
            try:
                access_token = await self.authenticator.get_access_token()
            except Exception as e:
                logger.error(f"Failed to get access token: {e}")
                raise

        auth_message = {
            "type": HACommandType.AUTH.value,
            "access_token": access_token
        }

        logger.debug("Sending auth message to Home Assistant")
        await self.websocket.send_json(auth_message)

    async def _handle_auth_ok(self, data: Dict[str, Any]) -> None:
        """Handle auth_ok message from Home Assistant."""
        self._auth_complete = True
        self._auth_event.set()
        logger.info(f"Authentication successful (HA version: {data.get('ha_version', 'unknown')})")

        # Enable message coalescing for better performance
        try:
            await self.websocket.send_json({
                "id": self._message_id + 1,
                "type": HACommandType.SUPPORTED_FEATURES.value,
                "features": {
                    "coalesce_messages": 1
                }
            })
            self._message_id += 1
            logger.debug("Enabled message coalescing feature")
        except Exception as e:
            logger.warning(f"Failed to enable coalescing: {e}")

        # Start post-auth setup
        asyncio.create_task(self._post_auth_setup())

    async def _handle_auth_invalid(self, data: Dict[str, Any]) -> None:
        """Handle auth_invalid message from Home Assistant."""
        error_message = data.get("message", "Authentication failed")
        logger.error(f"Authentication failed: {error_message}")
        self.connected = False
        self._auth_event.set()
        raise ConnectionError(f"Home Assistant authentication failed: {error_message}")

    async def _handle_event(self, data: Dict[str, Any]) -> None:
        """Handle event message from Home Assistant."""
        message_id = data.get("id")
        event_data = data.get("event", {})
        event_type = event_data.get("event_type")

        logger.info(f"Received event: {event_type} (subscription: {message_id})")
        #logger.info(f"Event data: {json.dumps(event_data, indent=2, ensure_ascii=False)}")

        # Check if this is a state changed event
        if event_type == "state_changed":
            await self._handle_state_changed(event_data)
            return

        # Call subscription handler if registered
        if message_id and message_id in self.event_subscriptions:
            handler = self.event_subscriptions[message_id]
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_data)
                else:
                    # Non-async handler, run in executor
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, handler, event_data)
            except Exception as e:
                logger.error(f"Error in event handler for {event_type}: {e}")

    async def _handle_state_changed(self, event_data: Dict[str, Any]) -> None:
        """Handle state_changed event."""
        # state_changed event structure: {"data": {"entity_id": ..., "old_state": ..., "new_state": ...}}
        data = event_data.get("data", {})
        new_state = data.get("new_state")
        old_state = data.get("old_state")

        if new_state:
            entity_id = new_state.get("entity_id")
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"

            # Filter out button entities and other less useful types
            filtered_domains = {"button", "input_button", "input_text", "input_datetime",
                              "script", "automation", "zone", "sun", "group", "persistent_notification"}

            if domain in filtered_domains:
                logger.debug(f"Filtered out {domain} entity: {entity_id}")
                return

            # Filter out time-based states (like button timestamps)
            old_value = old_state.get("state", "N/A") if old_state else "N/A"
            new_value = new_state.get("state", "unknown")

            # Skip if state looks like a timestamp and hasn't changed
            if (old_value == new_value and
                (isinstance(old_value, str) and (old_value.startswith("20") or "T" in old_value))):
                logger.debug(f"Skipping timestamp-only state change: {entity_id}")
                return

            name = new_state.get("attributes", {}).get("friendly_name", entity_id)

            # Print clear status change log
            logger.info(f"{'='*60}")
            logger.info(f"Entity: {name} ({entity_id})")
            logger.info(f"State: {old_value} -> {new_value}")

            # Log important attributes
            new_attrs = new_state.get("attributes", {})

            important_attrs = ["brightness", "color_temp", "rgb_color", "temperature",
                              "humidity", "pressure", "illuminance", "power", "current",
                              "voltage", "battery_level", "hvac_action", "preset_mode"]

            for attr in important_attrs:
                if attr in new_attrs:
                    new_attr_val = new_attrs.get(attr, "N/A")
                    if old_state:
                        old_attrs = old_state.get("attributes", {})
                        old_attr_val = old_attrs.get(attr, "N/A")
                        if old_attr_val != new_attr_val:
                            logger.info(f"{attr}: {old_attr_val} -> {new_attr_val}")
                    else:
                        logger.info(f"{attr}: {new_attr_val}")

            logger.info(f"{'='*60}")

        logger.debug(f"State changed - Old: {json.dumps(old_state, indent=2, ensure_ascii=False)}")
        logger.debug(f"State changed - New: {json.dumps(new_state, indent=2, ensure_ascii=False)}")

        if new_state:
            entity_id = new_state.get("entity_id")

            # Create state update message for gateway clients
            state_message = create_state_update(entity_id, new_state)

            # Notify all state handlers
            for handler in self.state_handlers:
                try:
                    await handler(state_message)
                except Exception as e:
                    logger.error(f"Error in state handler for {entity_id}: {e}")

    async def _handle_result(self, data: Dict[str, Any]) -> None:
        """Handle result message from Home Assistant."""
        message_id = data.get("id")

        if message_id and message_id in self.message_handlers:
            future = self.message_handlers.pop(message_id)
            if not future.done():
                future.set_result(data)

    async def _handle_error(self, data: Dict[str, Any]) -> None:
        """Handle error message from Home Assistant."""
        message_id = data.get("id")

        if message_id and message_id in self.message_handlers:
            future = self.message_handlers.pop(message_id)
            if not future.done():
                future.set_result(data)

    async def _wait_for_auth(self, timeout: float = 10.0) -> None:
        """Wait for authentication to complete."""
        try:
            await asyncio.wait_for(self._auth_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError("Authentication timed out")

    async def _post_auth_setup(self) -> None:
        """Set up subscriptions after authentication."""
        try:
            logger.info("Setting up subscriptions...")

            # Fetch entity registry (contains device_id information)
            await self.fetch_entity_registry()

            # Fetch device registry (contains device name, model, manufacturer)
            await self.fetch_device_registry()

            # Subscribe to state changes
            await self.subscribe_state_changes()
            logger.info("Subscribed to state_changed events")

            # Fetch initial states
            if not self._initial_states:
                await self.fetch_initial_states()
        except Exception as e:
            logger.error(f"Error in post-auth setup: {e}")

    async def _reconnect(self) -> None:
        """Attempt to reconnect to Home Assistant."""
        max_attempts = self.config.performance.max_reconnect_attempts if hasattr(self.config, 'performance') and hasattr(self.config.performance, 'max_reconnect_attempts') else 5
        reconnect_delay = self.config.performance.reconnect_delay if hasattr(self.config, 'performance') and hasattr(self.config.performance, 'reconnect_delay') else 5

        for attempt in range(max_attempts):
            try:
                logger.info(f"Attempting to reconnect (attempt {attempt + 1}/{max_attempts})")
                await asyncio.sleep(reconnect_delay)

                # Cancel old message handlers
                self.message_handlers.clear()

                # Reconnect
                await self.connect()
                logger.info("Reconnection successful")
                return

            except Exception as e:
                logger.error(f"Reconnection attempt {attempt + 1} failed: {e}")

        logger.error("Max reconnection attempts reached")


class GatewayWebSocketServer:
    """WebSocket server for client connections."""

    def __init__(self, config: Config, ha_ws: HomeAssistantWebSocket, new_device_manager=None):
        self.config = config
        self.ha_ws = ha_ws
        self.new_device_manager = new_device_manager
        self.app = web.Application()
        self.app.router.add_get("/ws", self._websocket_handler)
        self.runner = None
        self.site = None
        self.clients: Dict[str, web.WebSocketResponse] = {}
        self.client_subscriptions: Dict[str, List[str]] = {}
        self.device_subscriptions: Dict[str, List[str]] = defaultdict(list)  # device_id -> client_ids

    async def start(self) -> None:
        """Start WebSocket server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(
            self.runner,
            self.config.gateway.host,
            self.config.gateway.port
        )
        await self.site.start()
        logger.info(f"WebSocket server started on {self.config.gateway.host}:{self.config.gateway.port}")

    async def stop(self) -> None:
        """Stop WebSocket server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

        # Close all client connections
        for ws in self.clients.values():
            try:
                await ws.close()
            except Exception:
                pass
        self.clients.clear()
        self.client_subscriptions.clear()

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket client connections."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        client_id = f"client_{id(ws)}"
        self.clients[client_id] = ws

        logger.info(f"Client connected: {client_id}")

        try:
            # Send initial state to new client
            await self._send_initial_state(ws)

            # Process client messages
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_client_message(client_id, msg.data)
                elif msg.type == aiohttp.WSMsgType.PING:
                    # Respond to WebSocket ping
                    await ws.pong()
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"Client error: {ws.exception()}")
                    break

        except Exception as e:
            logger.error(f"Client connection error: {e}")
        finally:
            if client_id in self.clients:
                del self.clients[client_id]
            if client_id in self.client_subscriptions:
                del self.client_subscriptions[client_id]
            await ws.close()
            logger.info(f"Client disconnected: {client_id}")

        return ws

    async def _send_initial_state(self, ws: web.WebSocketResponse) -> None:
        """Send initial state to new client."""
        try:
            # Get stored initial states from Home Assistant WebSocket
            if self.ha_ws._initial_states:
                states = self.ha_ws._initial_states
            else:
                # Fetch fresh states
                states = await self.ha_ws.get_states()
                self.ha_ws._initial_states = states

            logger.debug(f"Sending {len(states)} initial states to client")

            # Send state for each entity
            for state in states:
                msg = create_state_update(state["entity_id"], state)
                await ws.send_str(msg.json)

        except Exception as e:
            logger.error(f"Error sending initial state: {e}")

    async def _handle_client_message(self, client_id: str, message_str: str) -> None:
        """Handle message from client."""
        try:
            message = Message.from_json(message_str)
            await self._process_client_message(client_id, message)
        except Exception as e:
            logger.error(f"Error handling client message: {e}")
            error_msg = create_error(Message(type=MessageType.ERROR, id="system"), str(e))
            await self._send_to_client(client_id, error_msg)

    async def _process_client_message(self, client_id: str, message: Message) -> None:
        """Process a message from client."""
        try:
            if message.type == MessageType.GET_STATE:
                await self._handle_get_state(client_id, message)
            elif message.type == MessageType.SET_STATE:
                await self._handle_set_state(client_id, message)
            elif message.type == MessageType.CALL_SERVICE:
                await self._handle_call_service(client_id, message)
            elif message.type == MessageType.SUBSCRIBE:
                await self._handle_subscribe(client_id, message)
            elif message.type == MessageType.UNSUBSCRIBE:
                await self._handle_unsubscribe(client_id, message)
            elif message.type == MessageType.PING:
                await self._handle_ping(client_id, message)
            elif message.type == MessageType.DISCOVER:
                await self._handle_discover(client_id, message)
            elif message.type == MessageType.LIST_DEVICES:
                await self._handle_list_devices(client_id, message)
            elif message.type == MessageType.GET_DEVICE:
                await self._handle_get_device(client_id, message)
            elif message.type == MessageType.CONTROL_DEVICE:
                await self._handle_control_device(client_id, message)
            elif message.type == MessageType.SUBSCRIBE_DEVICE:
                await self._handle_subscribe_device(client_id, message)
            elif message.type == MessageType.UNSUBSCRIBE_DEVICE:
                await self._handle_unsubscribe_device(client_id, message)
            else:
                error_msg = create_error(message, f"Unsupported message type: {message.type}")
                await self._send_to_client(client_id, error_msg)
        except Exception as e:
            logger.error(f"Error processing client message: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)

    async def _handle_get_state(self, client_id: str, message: Message) -> None:
        """Handle get_state command."""
        entity_id = message.payload.get("entity_id")
        if entity_id:
            try:
                states = await self.ha_ws.get_states(entity_id)
                state = states[0] if states else None
                if state:
                    msg = create_response(message, True, data={"state": state})
                    await self._send_to_client(client_id, msg)
                else:
                    error_msg = create_error(message, "Entity not found")
                    await self._send_to_client(client_id, error_msg)
            except Exception as e:
                logger.error(f"Error getting state for {entity_id}: {e}")
                error_msg = create_error(message, str(e))
                await self._send_to_client(client_id, error_msg)
        else:
            error_msg = create_error(message, "entity_id is required")
            await self._send_to_client(client_id, error_msg)

    async def _handle_set_state(self, client_id: str, message: Message) -> None:
        """Handle set_state command."""
        entity_id = message.payload.get("entity_id")
        state = message.payload.get("state")
        if entity_id and state is not None:
            try:
                # Call appropriate service
                domain = entity_id.split(".")[0]
                # Handle both boolean and string states
                state_text = str(state).strip().lower()
                if state is True or state_text in {"on", "true", "1"}:
                    service = "turn_on"
                    desired_state = "on"
                else:
                    service = "turn_off"
                    desired_state = "off"

                # Prepare target
                target = {"entity_id": entity_id}

                await self.ha_ws.call_service(
                    domain=domain,
                    service=service,
                    target=target
                )

                # Poll briefly so we return the post-action state instead of a stale snapshot.
                updated_state = await self._wait_for_entity_state(
                    entity_id=entity_id,
                    desired_state=desired_state,
                    timeout_sec=2.0,
                    poll_interval=0.2,
                )

                if updated_state:
                    current_state = updated_state.get("state")
                    msg = create_response(
                        message,
                        True,
                        data={
                            "state": current_state,
                            "desired_state": desired_state,
                            "applied": current_state == desired_state,
                        },
                    )
                    await self._send_to_client(client_id, msg)
                else:
                    error_msg = create_error(message, "Failed to get updated state")
                    await self._send_to_client(client_id, error_msg)

            except Exception as e:
                logger.error(f"Error setting state for {entity_id}: {e}")
                error_msg = create_error(message, str(e))
                await self._send_to_client(client_id, error_msg)
        else:
            error_msg = create_error(message, "entity_id and state are required")
            await self._send_to_client(client_id, error_msg)

    async def _get_entity_state_snapshot(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Fetch current state for a single entity via get_states."""
        state_response = await self.ha_ws.send_command(HACommandType.GET_STATES.value)
        all_states = state_response.get("result", [])
        for state in all_states:
            if state.get("entity_id") == entity_id:
                return state
        return None

    async def _wait_for_entity_state(
        self,
        *,
        entity_id: str,
        desired_state: str,
        timeout_sec: float,
        poll_interval: float,
    ) -> Optional[Dict[str, Any]]:
        """Poll entity state until desired state is observed or timeout is reached."""
        deadline = asyncio.get_event_loop().time() + timeout_sec
        latest_state = None
        while True:
            latest_state = await self._get_entity_state_snapshot(entity_id)
            if latest_state and latest_state.get("state") == desired_state:
                return latest_state
            if asyncio.get_event_loop().time() >= deadline:
                return latest_state
            await asyncio.sleep(poll_interval)

    async def _handle_call_service(self, client_id: str, message: Message) -> None:
        """Handle call_service command."""
        domain = message.payload.get("domain")
        service = message.payload.get("service")
        service_data = message.payload.get("service_data", {})
        target = message.payload.get("target", {})
        client_return_response = message.payload.get("return_response")
        return_response = client_return_response is True

        if not isinstance(service_data, dict):
            service_data = {}
        if not isinstance(target, dict):
            target = {}

        if domain and service:
            try:
                # Map turn_on/turn_off to select_option for select/input_select entities
                if domain in ("select", "input_select") and service in ("turn_on", "turn_off"):
                    entity_id = target.get("entity_id") or service_data.get("entity_id")
                    if entity_id:
                        # Get the entity state to find options
                        option = await self._get_select_option(entity_id, service == "turn_on")
                        if option:
                            # Convert to select_option call
                            service = "select_option"
                            service_data = {"option": option}
                            target = {"entity_id": entity_id}
                            return_response = False  # select_option doesn't support responses
                        else:
                            error_msg = create_error(message, "Could not find suitable option")
                            await self._send_to_client(client_id, error_msg)
                            return
                    else:
                        error_msg = create_error(message, "entity_id is required")
                        await self._send_to_client(client_id, error_msg)
                        return

                response = await self.ha_ws.call_service(
                    domain=domain,
                    service=service,
                    service_data=service_data,
                    target=target,
                    return_response=return_response
                )

                if return_response:
                    msg = create_response(message, True, data=response.get("result", {}))
                    await self._send_to_client(client_id, msg)
                else:
                    # Send immediate success response for services that don't return data
                    context = {}
                    if isinstance(response.get("result"), dict):
                        context = response.get("result", {}).get("context", {})
                    msg = create_response(message, True, data={"sent": True, "context": context})
                    await self._send_to_client(client_id, msg)
            except Exception as e:
                if return_response and "service_does_not_support_response" in str(e):
                    logger.warning(
                        "Service %s.%s does not support return_response; retrying without response payload",
                        domain,
                        service,
                    )
                    try:
                        response = await self.ha_ws.call_service(
                            domain=domain,
                            service=service,
                            service_data=service_data,
                            target=target,
                            return_response=False,
                        )
                        context = {}
                        if isinstance(response.get("result"), dict):
                            context = response.get("result", {}).get("context", {})
                        msg = create_response(
                            message,
                            True,
                            data={
                                "sent": True,
                                "context": context,
                                "fallback_without_return_response": True,
                            },
                        )
                        await self._send_to_client(client_id, msg)
                        return
                    except Exception:
                        pass
                logger.error(f"Error calling service {domain}.{service}: {e}")
                error_msg = create_error(message, str(e))
                await self._send_to_client(client_id, error_msg)
        else:
            error_msg = create_error(message, "domain and service are required")
            await self._send_to_client(client_id, error_msg)

    async def _get_select_option(self, entity_id: str, turn_on: bool) -> Optional[str]:
        """Get the appropriate option for a select entity based on turn_on/turn_off.

        Args:
            entity_id: The select entity ID
            turn_on: True for turn_on, False for turn_off

        Returns:
            The option string to use, or None if not found
        """
        try:
            # Get states from Home Assistant
            states = await self.ha_ws.get_states()
            for state in states:
                if state.get("entity_id") == entity_id:
                    attributes = state.get("attributes", {})
                    options = attributes.get("options", [])

                    if not options:
                        return None

                    if turn_on:
                        # Look for "on" keywords
                        on_keywords = ['on', 'open', 'enabled', 'active', 'running', 'start', 'power_on']
                        for option in options:
                            option_lower = option.lower()
                            for keyword in on_keywords:
                                if keyword in option_lower:
                                    return option
                        # Fallback to last option
                        return options[-1] if options else None
                    else:
                        # Look for "off" keywords
                        off_keywords = ['off', 'close', 'disabled', 'inactive', 'stop', 'standby', 'power_off']
                        for option in options:
                            option_lower = option.lower()
                            for keyword in off_keywords:
                                if keyword in option_lower:
                                    return option
                        # Fallback to first option
                        return options[0] if options else None
        except Exception as e:
            logger.error(f"Error getting select options for {entity_id}: {e}")
        return None

    async def _handle_subscribe(self, client_id: str, message: Message) -> None:
        """Handle subscribe command."""
        entity_id = message.payload.get("entity_id")
        if entity_id:
            if client_id not in self.client_subscriptions:
                self.client_subscriptions[client_id] = []
            if entity_id not in self.client_subscriptions[client_id]:
                self.client_subscriptions[client_id].append(entity_id)
            msg = create_response(message, True, data={"subscribed": True})
            await self._send_to_client(client_id, msg)
        else:
            error_msg = create_error(message, "entity_id is required")
            await self._send_to_client(client_id, error_msg)

    async def _handle_unsubscribe(self, client_id: str, message: Message) -> None:
        """Handle unsubscribe command."""
        entity_id = message.payload.get("entity_id")
        if entity_id and client_id in self.client_subscriptions:
            if entity_id in self.client_subscriptions[client_id]:
                self.client_subscriptions[client_id].remove(entity_id)
            msg = create_response(message, True)
            await self._send_to_client(client_id, msg)
        else:
            error_msg = create_error(message, "entity_id is required")
            await self._send_to_client(client_id, error_msg)

    async def _handle_ping(self, client_id: str, message: Message) -> None:
        """Handle ping command."""
        msg = create_response(message, True, data={"timestamp": asyncio.get_event_loop().time()})
        await self._send_to_client(client_id, msg)

    async def _handle_discover(self, client_id: str, message: Message) -> None:
        """Handle discover command."""
        try:
            # Get stored initial states or fetch fresh ones
            if self.ha_ws._initial_states:
                states = self.ha_ws._initial_states
            else:
                states = await self.ha_ws.get_states()
                self.ha_ws._initial_states = states

            devices = []
            for state in states:
                if self._is_device_allowed(state["entity_id"]):
                    device = {
                        "entity_id": state["entity_id"],
                        "name": state.get("attributes", {}).get("friendly_name", state["entity_id"]),
                        "domain": state["entity_id"].split(".")[0],
                        "state": state["state"],
                        "attributes": state.get("attributes", {})
                    }
                    devices.append(device)

            msg = create_response(message, True, data={"devices": devices})
            await self._send_to_client(client_id, msg)

        except Exception as e:
            logger.error(f"Error in discover: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)

    async def _handle_list_devices(self, client_id: str, message: Message) -> None:
        """Handle list_devices command."""
        if not self.new_device_manager:
            error_msg = create_error(message, "Device manager not available")
            await self._send_to_client(client_id, error_msg)
            return

        try:
            # Get filter parameters
            payload = message.payload or {}
            area_id = payload.get("area_id")
            device_type = payload.get("type")

            # Get devices with filters
            from device_models import DeviceType
            type_filter = DeviceType(device_type) if device_type else None
            devices = self.new_device_manager.get_devices(device_type=type_filter, area_id=area_id)

            # Convert to dict format
            device_list = [d.to_dict() for d in devices]

            msg = create_device_list(device_list)
            msg.id = message.id  # Use original message ID for response
            await self._send_to_client(client_id, msg)

            logger.info(f"Listed {len(device_list)} devices for client {client_id}")

        except Exception as e:
            logger.error(f"Error listing devices: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)

    async def _handle_get_device(self, client_id: str, message: Message) -> None:
        """Handle get_device command."""
        if not self.new_device_manager:
            error_msg = create_error(message, "Device manager not available")
            await self._send_to_client(client_id, error_msg)
            return

        try:
            device_id = message.payload.get("device_id")
            if not device_id:
                error_msg = create_error(message, "device_id is required")
                await self._send_to_client(client_id, error_msg)
                return

            device = self.new_device_manager.get_device(device_id)
            if device:
                msg = create_response(message, True, data=device.to_dict())
                await self._send_to_client(client_id, msg)
            else:
                error_msg = create_error(message, f"Device not found: {device_id}")
                await self._send_to_client(client_id, error_msg)

        except Exception as e:
            logger.error(f"Error getting device: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)

    async def _handle_control_device(self, client_id: str, message: Message) -> None:
        """Handle control_device command."""
        if not self.new_device_manager:
            error_msg = create_error(message, "Device manager not available")
            await self._send_to_client(client_id, error_msg)
            return

        try:
            device_id = message.payload.get("device_id")
            action = message.payload.get("action")
            params = message.payload.get("params", {})

            if not device_id or not action:
                error_msg = create_error(message, "device_id and action are required")
                await self._send_to_client(client_id, error_msg)
                return

            # Get device and primary entity
            device = self.new_device_manager.get_device(device_id)
            if not device:
                error_msg = create_error(message, f"Device not found: {device_id}")
                await self._send_to_client(client_id, error_msg)
                return

            primary = device.primary_entity
            if not primary:
                error_msg = create_error(message, f"No primary entity for device: {device_id}")
                await self._send_to_client(client_id, error_msg)
                return

            # Map action to service call
            await self._execute_device_action(primary, action, params)

            msg = create_response(message, True, data={"device_id": device_id, "action": action})
            await self._send_to_client(client_id, msg)

            logger.info(f"Controlled device {device.name}: {action} with params {params}")

        except Exception as e:
            logger.error(f"Error controlling device: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)

    async def _execute_device_action(self, entity, action: str, params: dict) -> None:
        """Execute device action via service call."""
        domain = entity.domain

        if action == "power_on":
            await self.ha_ws.call_service(domain, "turn_on", target={"entity_id": entity.entity_id}, **params)
        elif action == "power_off":
            await self.ha_ws.call_service(domain, "turn_off", target={"entity_id": entity.entity_id}, **params)
        elif action == "power_toggle":
            await self.ha_ws.call_service(domain, "toggle", target={"entity_id": entity.entity_id}, **params)
        elif action == "set_brightness" and domain == "light":
            brightness = params.get("brightness")
            await self.ha_ws.call_service(domain, "turn_on", target={"entity_id": entity.entity_id},
                                       service_data={"brightness": brightness})
        elif action == "set_color_temp" and domain == "light":
            color_temp = params.get("color_temp")
            await self.ha_ws.call_service(domain, "turn_on", target={"entity_id": entity.entity_id},
                                       service_data={"color_temp": color_temp})
        elif action == "set_temperature" and domain == "climate":
            temperature = params.get("temperature")
            await self.ha_ws.call_service(domain, "set_temperature", target={"entity_id": entity.entity_id},
                                       service_data={"temperature": temperature})
        elif action == "open" and domain == "cover":
            await self.ha_ws.call_service(domain, "open_cover", target={"entity_id": entity.entity_id}, **params)
        elif action == "close" and domain == "cover":
            await self.ha_ws.call_service(domain, "close_cover", target={"entity_id": entity.entity_id}, **params)
        elif action == "stop" and domain == "cover":
            await self.ha_ws.call_service(domain, "stop_cover", target={"entity_id": entity.entity_id}, **params)
        elif action == "unlock" and domain == "lock":
            await self.ha_ws.call_service(domain, "unlock", target={"entity_id": entity.entity_id}, **params)
        elif action == "lock" and domain == "lock":
            await self.ha_ws.call_service(domain, "lock", target={"entity_id": entity.entity_id}, **params)
        elif action == "play_pause" and domain == "media_player":
            await self.ha_ws.call_service(domain, "media_play_pause", target={"entity_id": entity.entity_id}, **params)
        else:
            # Try generic service call
            await self.ha_ws.call_service(domain, action, target={"entity_id": entity.entity_id}, service_data=params)

    async def _handle_subscribe_device(self, client_id: str, message: Message) -> None:
        """Handle subscribe_device command."""
        try:
            device_id = message.payload.get("device_id")
            if not device_id:
                error_msg = create_error(message, "device_id is required")
                await self._send_to_client(client_id, error_msg)
                return

            # Add client to device subscriptions
            if client_id not in self.device_subscriptions[device_id]:
                self.device_subscriptions[device_id].append(client_id)

            msg = create_response(message, True, data={"subscribed": True, "device_id": device_id})
            await self._send_to_client(client_id, msg)

            logger.info(f"Client {client_id} subscribed to device {device_id}")

        except Exception as e:
            logger.error(f"Error subscribing to device: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)

    async def _handle_unsubscribe_device(self, client_id: str, message: Message) -> None:
        """Handle unsubscribe_device command."""
        try:
            device_id = message.payload.get("device_id")
            if device_id and device_id in self.device_subscriptions:
                if client_id in self.device_subscriptions[device_id]:
                    self.device_subscriptions[device_id].remove(client_id)

            msg = create_response(message, True)
            await self._send_to_client(client_id, msg)

            logger.info(f"Client {client_id} unsubscribed from device {device_id}")

        except Exception as e:
            logger.error(f"Error unsubscribing from device: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)
        except Exception as e:
            logger.error(f"Error in discover: {e}")
            error_msg = create_error(message, str(e))
            await self._send_to_client(client_id, error_msg)

    async def _send_to_client(self, client_id: str, message: Message) -> None:
        """Send message to specific client."""
        if client_id in self.clients:
            ws = self.clients[client_id]
            try:
                logger.debug(f"Sending to client {client_id}: {json.dumps(json.loads(message.json), indent=2, ensure_ascii=False)}")
                await ws.send_str(message.json)
            except Exception as e:
                logger.error(f"Error sending message to client {client_id}: {e}")
                # Remove client if connection is broken
                if client_id in self.clients:
                    del self.clients[client_id]
                if client_id in self.client_subscriptions:
                    del self.client_subscriptions[client_id]

    async def broadcast_state_change(self, entity_id: str, state: Dict[str, Any]) -> None:
        """Broadcast state change to subscribed clients."""
        msg = create_state_update(entity_id, state)

        for client_id, subscriptions in self.client_subscriptions.items():
            if entity_id in subscriptions or "*" in subscriptions:
                await self._send_to_client(client_id, msg)

    async def broadcast_device_state_change(self, device_id: str, device) -> None:
        """Broadcast device state change to subscribed clients."""
        if not self.new_device_manager:
            return

        msg = create_device_state_update(device_id, device.to_dict())

        # Broadcast to clients subscribed to this device
        for client_id in self.device_subscriptions.get(device_id, []):
            await self._send_to_client(client_id, msg)

        logger.debug(f"Broadcasted device state change for {device_id} to {len(self.device_subscriptions.get(device_id, []))} clients")

    def _is_device_allowed(self, entity_id: str) -> bool:
        """Check if device is allowed based on filter rules."""
        # Exclude all Home Assistant entities if enabled
        if hasattr(self.config, 'devices') and getattr(self.config.devices, 'exclude_ha_entities', False):
            if getattr(self.config.devices, 'exclude_ha_entities', False):
                # Home Assistant entities typically follow these patterns:
                # - sensor.*, binary_sensor.*, switch.*, light.*, automation.*, script.*, zone.*, sun.*, input_boolean.*, input_number.*, weather.*
                # But allow custom integrations
                ha_default_patterns = [
                    r"^automation\.",
                    r"^script\.",
                    r"^zone\.",
                    r"^sun\.",
                    r"^sensor\.home_assistant\.",
                    r"^sensor\.sun\.",
                    r"^input_boolean\.sun\.",
                    r"^input_number\.sun\.",
                    r"^weather\.",
                ]
                if any(pattern.match(entity_id) for pattern in ha_default_patterns):
                    logger.debug(f"Excluding HA default entity: {entity_id}")
                    return False

        # Check custom HA entity patterns to exclude
        if hasattr(self.config, 'devices') and hasattr(self.config.devices, 'exclude_ha_entity_patterns'):
            for pattern in self.config.devices.exclude_ha_entity_patterns:
                if pattern.match(entity_id):
                    logger.debug(f"Excluding HA entity by pattern: {entity_id} matches {pattern}")
                    return False

        # Check exclusion patterns
        if hasattr(self.config, 'devices') and hasattr(self.config.devices, 'exclude_entities'):
            if any(entity_id.startswith(pattern) for pattern in self.config.devices.exclude_entities):
                return False

        # Check include domains
        if hasattr(self.config, 'devices') and hasattr(self.config.devices, 'include_domains'):
            domain = entity_id.split(".")[0]
            if domain not in self.config.devices.include_domains:
                return False

        return True

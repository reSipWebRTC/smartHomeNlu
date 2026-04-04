"""Command handling for Home Assistant Gateway."""

import asyncio
import logging
from typing import Dict, Any, Optional

from config import Config
from device_manager import DeviceManager
from state_manager import StateManager
from protocol.message import MessageType, Message, ServiceCall


logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles incoming commands from clients."""

    def __init__(self, config: Config, device_manager, state_manager: StateManager):
        self.config = config
        self.device_manager = device_manager  # May be None in WebSocket-only mode
        self.state_manager = state_manager
        self.command_queue = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start command handler."""
        logger.info("Starting command handler")
        self._running = True
        self._worker_task = asyncio.create_task(self._process_commands())

    async def stop(self) -> None:
        """Stop command handler."""
        logger.info("Stopping command handler")
        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def handle_command(self, message: Message) -> Dict[str, Any]:
        """Handle a command message."""
        try:
            await self.command_queue.put(message)
            return {"success": True, "queued": True}
        except Exception as e:
            logger.error(f"Error queuing command: {e}")
            return {"success": False, "error": str(e)}

    async def _process_commands(self) -> None:
        """Process commands from the queue."""
        while self._running:
            try:
                message = await asyncio.wait_for(self.command_queue.get(), timeout=1.0)
                await self._execute_command(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing command: {e}")

    async def _execute_command(self, message: Message) -> Dict[str, Any]:
        """Execute a command."""
        logger.debug(f"Executing command: {message.type}")

        result = {"success": False}

        try:
            if message.type == MessageType.GET_STATE:
                entity_id = message.payload.get("entity_id")
                if entity_id:
                    state = await self.state_manager.get_state(entity_id)
                    if state:
                        result = {
                            "success": True,
                            "state": state  # state is already a dict
                        }
                    else:
                        result["error"] = "Entity not found"
                else:
                    result["error"] = "entity_id is required"

            elif message.type == MessageType.SET_STATE:
                entity_id = message.payload.get("entity_id")
                state = message.payload.get("state")
                if entity_id and state is not None:
                    # Update state in device manager
                    await self.device_manager.update_state(entity_id, {
                        "state": state,
                        "attributes": {},
                        "last_updated": asyncio.get_event_loop().time()
                    })
                    result["success"] = True
                else:
                    result["error"] = "entity_id and state are required"

            elif message.type == MessageType.CALL_SERVICE:
                service_call = ServiceCall(
                    domain=message.payload.get("domain"),
                    service=message.payload.get("service"),
                    target=message.payload.get("target"),
                    service_data=message.payload.get("service_data", {})
                )

                if service_call.domain and service_call.service:
                    # Find entities to target
                    target_entities = []
                    if service_call.target:
                        if "entity_id" in service_call.target:
                            target_entities = [service_call.target["entity_id"]]
                        elif "area_id" in service_call.target:
                            # Would need area-to-entity mapping
                            pass
                    else:
                        # Target all entities of the domain
                        target_entities = [
                            d.entity_id for d in self.device_manager.get_devices(service_call.domain)
                        ]

                    if target_entities:
                        success = True
                        results = []

                        # Execute service on each target
                        for entity_id in target_entities:
                            try:
                                await self.device_manager.call_service(
                                    entity_id,
                                    service_call.service,
                                    **service_call.service_data
                                )
                                results.append({"entity_id": entity_id, "success": True})
                            except Exception as e:
                                results.append({"entity_id": entity_id, "success": False, "error": str(e)})
                                success = False

                        result = {
                            "success": success,
                            "results": results,
                            "targeted_entities": len(target_entities)
                        }
                    else:
                        result["error"] = "No matching entities found for service call"
                else:
                    result["error"] = "domain and service are required"

            elif message.type == MessageType.SUBSCRIBE:
                entity_id = message.payload.get("entity_id")
                if entity_id:
                    # This would be handled by the WebSocket server
                    result["success"] = True
                else:
                    result["error"] = "entity_id is required"

            elif message.type == MessageType.UNSUBSCRIBE:
                entity_id = message.payload.get("entity_id")
                if entity_id:
                    # This would be handled by the WebSocket server
                    result["success"] = True
                else:
                    result["error"] = "entity_id is required"

            elif message.type == MessageType.PING:
                result = {
                    "success": True,
                    "timestamp": asyncio.get_event_loop().time(),
                    "status": "running"
                }

            elif message.type == MessageType.DISCOVER:
                devices = self.device_manager.get_devices()
                result = {
                    "success": True,
                    "devices": [device.to_dict() for device in devices]
                }

            else:
                result["error"] = f"Unsupported command type: {message.type}"

        except Exception as e:
            logger.error(f"Error executing command {message.type}: {e}")
            result["error"] = str(e)

        return result

    async def batch_execute_commands(self, commands: list) -> list:
        """Execute multiple commands in batch."""
        results = []
        for cmd_data in commands:
            try:
                message = Message.from_json(cmd_data)
                result = await self._execute_command(message)
                results.append(result)
            except Exception as e:
                results.append({"success": False, "error": str(e)})
        return results
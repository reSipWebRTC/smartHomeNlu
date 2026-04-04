"""State management for Home Assistant Gateway (WebSocket-only version).

This version uses WebSocket API directly for state management.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Callable
from collections import defaultdict
from datetime import datetime, timedelta

from config import Config
from protocol.websocket import HomeAssistantWebSocket
from protocol.message import DeviceState


logger = logging.getLogger(__name__)


class StateManager:
    """Manages device states and state synchronization using WebSocket API.

    The StateManager acts as a local cache and manager for Home Assistant states.
    It receives real-time updates via WebSocket subscriptions and can fetch
    current states on demand.
    """

    def __init__(self, config: Config, ha_ws: HomeAssistantWebSocket, device_manager=None, new_device_manager=None, server=None):
        self.config = config
        self.ha_ws = ha_ws
        self.device_manager = device_manager
        self.new_device_manager = new_device_manager
        self.server = server  # Reference to server for KNX integration
        self.state_cache: Dict[str, Dict[str, Any]] = {}
        self.state_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.state_watchers: Dict[str, List[asyncio.Event]] = defaultdict(list)
        self.state_callbacks: List[Callable] = []
        self.max_history_size = config.cache.max_history if hasattr(config, 'cache') and hasattr(config.cache, 'max_history') else 100
        self._running = False
        self._sync_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start state management."""
        logger.info("Starting state manager")
        self._running = True

        # Register state change handler with Home Assistant WebSocket
        self.ha_ws.state_handlers.append(self._handle_state_change)
        logger.info("Registered state change handler with WebSocket")

        # Initial sync - load all states from HA into device_manager
        await self._initial_sync()

        # Start periodic state sync if cache is enabled
        if hasattr(self.config, 'cache') and self.config.cache.enabled:
            self._sync_task = asyncio.create_task(self._periodic_sync())
            logger.info("Periodic state sync enabled")

    async def stop(self) -> None:
        """Stop state management."""
        logger.info("Stopping state manager")
        self._running = False

        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

    async def _initial_sync(self) -> None:
        """Initial sync - load all states from HA into device_manager."""
        try:
            # Wait a bit for authentication and initial state fetch to complete
            await asyncio.sleep(0.5)

            logger.info("Performing initial state sync with Home Assistant...")

            # Try to use initial states if available (fetched by _post_auth_setup)
            if self.ha_ws._initial_states:
                states = self.ha_ws._initial_states
                logger.info(f"Using cached initial states: {len(states)} states")
            else:
                states = await self.ha_ws.get_states()
                self.ha_ws._initial_states = states

            loaded_count = 0
            for state in states:
                entity_id = state.get("entity_id")
                if entity_id:
                    # Enhance state with entity registry data (device_id)
                    enhanced_state = self._enhance_state_with_registry_data(state)

                    # Update cache
                    self.state_cache[entity_id] = enhanced_state

                    # Update device_manager if available
                    if self.device_manager:
                        try:
                            await self.device_manager.update_state(entity_id, enhanced_state)
                            loaded_count += 1
                        except Exception as e:
                            logger.debug(f"Error updating device manager for {entity_id}: {e}")

            # Enhance states with entity registry data before device discovery
            enhanced_states = [self._enhance_state_with_registry_data(state) for state in states]

            # Discover and initialize new device manager
            if self.new_device_manager:
                try:
                    # Register device change callback BEFORE discovering devices
                    # This ensures the callback is triggered for all discovered devices
                    self.new_device_manager.add_device_change_callback(self._on_device_change)

                    # Now discover devices - this will trigger the callback for each device
                    devices = await self.new_device_manager.discover_devices(enhanced_states)
                    logger.info(f"New device manager discovered {len(devices)} devices")

                except Exception as e:
                    logger.error(f"Error discovering devices for new device manager: {e}")

            logger.info(f"Initial sync complete: loaded {loaded_count} device states")

        except Exception as e:
            logger.error(f"Error in initial sync: {e}")

    async def _periodic_sync(self) -> None:
        """Periodically sync states with Home Assistant.

        This is used as a backup mechanism to ensure state consistency
        even if WebSocket events are missed.
        """
        ttl = self.config.cache.ttl if hasattr(self.config, 'cache') and hasattr(self.config.cache, 'ttl') else 60
        while self._running:
            try:
                await asyncio.sleep(ttl)

                if self._running:
                    logger.debug("Performing periodic state sync")
                    await self.sync_all_states()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic sync: {e}")

    async def _handle_state_change(self, state_message) -> None:
        """Handle state change from WebSocket.

        Args:
            state_message: State message from WebSocket (Message object or dict)
        """
        try:
            # Parse state message - it's a Message object with payload
            if hasattr(state_message, 'payload'):
                # It's a Message object
                payload = state_message.payload
                entity_id = payload.get("entity_id")
                state_data = payload.get("state")
            elif isinstance(state_message, dict):
                # It's already a dict (backward compatibility)
                entity_id = state_message.get("entity_id")
                state_data = state_message.get("state")
            else:
                logger.error(f"Invalid state message type: {type(state_message)}")
                return

            if entity_id and state_data:
                await self.update_state(entity_id, state_data)
        except Exception as e:
            logger.error(f"Error handling state change: {e}")

    def _enhance_state_with_registry_data(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance state data with entity registry information (device_id).

        Args:
            state: Original state data from Home Assistant

        Returns:
            Enhanced state data with device_id added to attributes
        """
        entity_id = state.get("entity_id")
        if not entity_id:
            return state

        # Get device_id from entity registry
        device_id = self.ha_ws.get_device_id_for_entity(entity_id)

        # If device_id exists, add it to attributes
        if device_id:
            # Create a copy to avoid modifying original
            enhanced_state = state.copy()
            attributes = enhanced_state.get("attributes", {})
            if not isinstance(attributes, dict):
                attributes = {}

            # Add device_id to attributes
            attributes_with_device_id = attributes.copy()
            attributes_with_device_id["device_id"] = device_id
            enhanced_state["attributes"] = attributes_with_device_id

            logger.debug(f"Added device_id '{device_id}' to entity '{entity_id}'")
            return enhanced_state

        return state

    async def update_state(self, entity_id: str, state_data: Dict[str, Any]) -> None:
        """Update state from Home Assistant event.

        Args:
            entity_id: Entity ID that changed
            state_data: New state data from Home Assistant
        """
        old_state = self.state_cache.get(entity_id, {}).get("state")
        new_state = state_data.get("state")

        # Update cache
        self.state_cache[entity_id] = state_data

        # Update device manager if available
        if self.device_manager:
            try:
                await self.device_manager.update_state(entity_id, state_data)
            except Exception as e:
                logger.error(f"Error updating device manager for {entity_id}: {e}")

        # Update new device manager if available
        if self.new_device_manager:
            try:
                await self.new_device_manager.update_entity_state(entity_id, state_data)
            except Exception as e:
                logger.error(f"Error updating new device manager for {entity_id}: {e}")

        # Record history
        if old_state != new_state:
            await self.record_state_change(entity_id, old_state, new_state)

        # Notify callbacks
        for callback in self.state_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(entity_id, state_data)
                else:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, callback, entity_id, state_data)
            except Exception as e:
                logger.error(f"Error in state callback: {e}")

        logger.debug(f"Updated state for {entity_id}: {old_state} -> {new_state}")

    async def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get current state of an entity.

        Args:
            entity_id: Entity ID to get state for

        Returns:
            State data dictionary or None if not found
        """
        # Check cache first
        if entity_id in self.state_cache:
            return self.state_cache[entity_id]

        # If not in cache, fetch from Home Assistant
        try:
            states = await self.ha_ws.get_states(entity_id)
            if states:
                state = states[0]
                self.state_cache[entity_id] = state
                return state
        except Exception as e:
            logger.error(f"Error fetching state for {entity_id}: {e}")

        return None

    async def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get all cached states."""
        return self.state_cache.copy()

    async def sync_all_states(self) -> None:
        """Sync all states from Home Assistant.

        Fetches all current states from Home Assistant and updates the cache.
        This is useful for initial load or periodic sync.
        """
        try:
            logger.info("Syncing all states from Home Assistant...")
            states = await self.ha_ws.get_states()

            for state in states:
                entity_id = state.get("entity_id")
                if entity_id:
                    self.state_cache[entity_id] = state

            logger.info(f"Synced {len(states)} states from Home Assistant")
        except Exception as e:
            logger.error(f"Error syncing states: {e}")

    async def get_state_history(self, entity_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get state history for an entity.

        Args:
            entity_id: Entity ID to get history for
            limit: Maximum number of history entries to return

        Returns:
            List of state change history entries
        """
        history = self.state_history.get(entity_id, [])
        return history[-limit:]

    async def record_state_change(self, entity_id: str, old_state: str, new_state: str) -> None:
        """Record a state change in history.

        Args:
            entity_id: Entity ID that changed
            old_state: Previous state value
            new_state: New state value
        """
        if not hasattr(self.config, 'cache') or not self.config.cache.enabled:
            return

        timestamp = datetime.now().isoformat()
        entry = {
            "timestamp": timestamp,
            "old_state": old_state,
            "new_state": new_state
        }

        self.state_history[entity_id].append(entry)

        # Keep history size in check
        if len(self.state_history[entity_id]) > self.max_history_size:
            self.state_history[entity_id].pop(0)

        # Notify watchers
        for event in self.state_watchers[entity_id]:
            event.set()
            self.state_watchers[entity_id].remove(event)

    async def wait_for_state_change(self, entity_id: str, timeout: Optional[float] = None) -> str:
        """Wait for a state change on an entity.

        Args:
            entity_id: Entity ID to watch
            timeout: Maximum time to wait (seconds)

        Returns:
            New state value

        Raises:
            TimeoutError: If timeout occurs before state change
            CancelledError: If waiting is cancelled
        """
        event = asyncio.Event()
        self.state_watchers[entity_id].append(event)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            state = self.state_cache.get(entity_id, {}).get("state")
            return state if state is not None else "unknown"
        except asyncio.TimeoutError:
            self.state_watchers[entity_id].remove(event)
            raise
        except asyncio.CancelledError:
            self.state_watchers[entity_id].remove(event)
            raise

    async def get_entity_statistics(self, entity_id: str, period_hours: int = 24) -> Dict[str, Any]:
        """Get statistics for an entity over a period.

        Args:
            entity_id: Entity ID to analyze
            period_hours: Number of hours to analyze

        Returns:
            Dictionary with statistics including state changes, most common state, etc.
        """
        if not hasattr(self.config, 'cache') or not self.config.cache.enabled:
            return {}

        cutoff = datetime.now() - timedelta(hours=period_hours)
        history = [
            entry for entry in self.state_history.get(entity_id, [])
            if datetime.fromisoformat(entry["timestamp"]) >= cutoff
        ]

        if not history:
            return {}

        # Calculate statistics
        states = [entry["new_state"] for entry in history]
        state_changes = len(states) - 1

        # Most common state
        state_counts = defaultdict(int)
        for state in states:
            state_counts[state] += 1
        most_common = max(state_counts.items(), key=lambda x: x[1]) if state_counts else ("unknown", 0)

        # Time in each state
        state_times = defaultdict(float)
        for i in range(len(history) - 1):
            try:
                start = datetime.fromisoformat(history[i]["timestamp"])
                end = datetime.fromisoformat(history[i + 1]["timestamp"])
                duration = (end - start).total_seconds()
                state_times[history[i]["new_state"]] += duration
            except (ValueError, KeyError):
                continue

        return {
            "period_hours": period_hours,
            "state_changes": state_changes,
            "most_common_state": most_common[0],
            "most_common_count": most_common[1],
            "time_in_states": {
                state: time for state, time in state_times.items()
            },
            "total_duration": (datetime.now() - cutoff).total_seconds()
        }

    async def cleanup_old_history(self, max_age_hours: int = 24 * 7) -> int:
        """Clean up old state history.

        Args:
            max_age_hours: Maximum age of history entries to keep

        Returns:
            Number of entities cleaned up
        """
        if not hasattr(self.config, 'cache') or not self.config.cache.enabled:
            return 0

        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        entities_to_remove = []
        cleaned_count = 0

        for entity_id, history in self.state_history.items():
            original_count = len(history)

            # Keep only recent entries
            self.state_history[entity_id] = [
                entry for entry in history
                if datetime.fromisoformat(entry["timestamp"]) >= cutoff
            ]

            # Remove empty histories
            if not self.state_history[entity_id]:
                entities_to_remove.append(entity_id)

            cleaned_count += original_count - len(self.state_history[entity_id])

        for entity_id in entities_to_remove:
            del self.state_history[entity_id]

        logger.info(f"Cleaned up {cleaned_count} old history entries, removed {len(entities_to_remove)} entity histories")
        return cleaned_count

    async def add_state_callback(self, callback: Callable) -> None:
        """Add a callback function to be notified of state changes.

        Args:
            callback: Function to call with (entity_id, state_data)
        """
        if callback not in self.state_callbacks:
            self.state_callbacks.append(callback)

    async def remove_state_callback(self, callback: Callable) -> None:
        """Remove a state change callback.

        Args:
            callback: Function to remove
        """
        if callback in self.state_callbacks:
            self.state_callbacks.remove(callback)

    async def _on_device_change(self, device_id: str, device) -> None:
        """Handle device state change from new device manager."""
        logger.info(f"Device state changed: {device_id} - {device.name}")
        logger.debug(f"Device state: {device.state.to_dict()}")

        # Forward to server's device change handler for KNX registration
        if self.server and hasattr(self.server, '_on_device_change'):
            try:
                await self.server._on_device_change(device_id, device)
            except Exception as e:
                logger.error(f"Error in server device change handler: {e}")

    def get_cache_size(self) -> int:
        """Get the current size of the state cache."""
        return len(self.state_cache)

    def get_history_size(self) -> int:
        """Get the total size of all history."""
        return sum(len(h) for h in self.state_history.values())

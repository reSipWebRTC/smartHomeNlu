"""Client management for Home Assistant Gateway."""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from protocol.message import Message, MessageType


logger = logging.getLogger(__name__)


@dataclass
class ClientInfo:
    """Information about a connected client."""
    id: str
    websocket = None
    connected_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    subscriptions: Set[str] = field(default_factory=set)
    is_authenticated: bool = False
    auth_token: Optional[str] = None
    metadata: Dict[str, any] = field(default_factory=dict)


class ClientManager:
    """Manages connected clients."""

    def __init__(self):
        self.clients: Dict[str, ClientInfo] = {}
        self.auth_tokens: Dict[str, str] = {}  # token -> client_id
        self._lock = asyncio.Lock()
        self.max_idle_time = timedelta(minutes=5)
        self.cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start client manager."""
        logger.info("Starting client manager")
        self.cleanup_task = asyncio.create_task(self._cleanup_idle_clients())

    async def stop(self) -> None:
        """Stop client manager."""
        logger.info("Stopping client manager")
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

    async def add_client(self, websocket) -> str:
        """Add a new client."""
        async with self._lock:
            client_id = str(uuid.uuid4())
            client = ClientInfo(
                id=client_id,
                websocket=websocket,
                connected_at=datetime.now(),
                last_activity=datetime.now()
            )
            self.clients[client_id] = client
            logger.debug(f"Added client: {client_id}")
            return client_id

    async def remove_client(self, client_id: str) -> None:
        """Remove a client."""
        async with self._lock:
            if client_id in self.clients:
                client = self.clients[client_id]
                # Remove auth token if exists
                if client.auth_token:
                    del self.auth_tokens[client.auth_token]
                del self.clients[client_id]
                logger.debug(f"Removed client: {client_id}")

    async def get_client(self, client_id: str) -> Optional[ClientInfo]:
        """Get client by ID."""
        return self.clients.get(client_id)

    async def update_activity(self, client_id: str) -> None:
        """Update client activity time."""
        async with self._lock:
            if client_id in self.clients:
                self.clients[client_id].last_activity = datetime.now()

    async def add_subscription(self, client_id: str, entity_id: str) -> bool:
        """Add a subscription for a client."""
        async with self._lock:
            if client_id in self.clients:
                self.clients[client_id].subscriptions.add(entity_id)
                return True
            return False

    async def remove_subscription(self, client_id: str, entity_id: str) -> bool:
        """Remove a subscription for a client."""
        async with self._lock:
            if client_id in self.clients:
                if entity_id in self.clients[client_id].subscriptions:
                    self.clients[client_id].subscriptions.remove(entity_id)
                    return True
            return False

    async def get_subscriptions(self, client_id: str) -> Set[str]:
        """Get all subscriptions for a client."""
        if client_id in self.clients:
            return self.clients[client_id].subscriptions.copy()
        return set()

    async def authenticate_client(self, client_id: str, token: str) -> bool:
        """Authenticate a client with a token."""
        async with self._lock:
            if client_id in self.clients:
                # Store the token
                self.clients[client_id].auth_token = token
                self.clients[client_id].is_authenticated = True
                self.auth_tokens[token] = client_id
                logger.debug(f"Authenticated client: {client_id}")
                return True
            return False

    async def get_client_by_token(self, token: str) -> Optional[ClientInfo]:
        """Get client by authentication token."""
        client_id = self.auth_tokens.get(token)
        if client_id:
            return await self.get_client(client_id)
        return None

    async def is_authorized(self, client_id: str, action: str) -> bool:
        """Check if client is authorized for an action."""
        # For now, all authenticated clients are authorized
        # In the future, we could implement role-based access control
        client = await self.get_client(client_id)
        return client is not None and client.is_authenticated

    async def broadcast(self, message: Message, exclude_client: Optional[str] = None) -> None:
        """Broadcast message to all clients."""
        if not message:
            return

        # Create copies of clients to avoid locking issues during broadcast
        clients_to_send = []
        async with self._lock:
            for client_id, client in self.clients.items():
                if client_id != exclude_client and client.websocket:
                    clients_to_send.append((client_id, client))

        # Send to clients without holding the lock
        for client_id, client in clients_to_send:
            try:
                await client.websocket.send_str(message.json)
                await self.update_activity(client_id)
            except Exception as e:
                logger.error(f"Error sending message to client {client_id}: {e}")
                # Remove client if connection is broken
                await self.remove_client(client_id)

    async def get_client_stats(self) -> Dict[str, any]:
        """Get statistics about connected clients."""
        async with self._lock:
            stats = {
                "total_clients": len(self.clients),
                "authenticated_clients": sum(1 for c in self.clients.values() if c.is_authenticated),
                "active_clients": sum(1 for c in self.clients.values()
                                   if datetime.now() - c.last_activity < self.max_idle_time),
                "total_subscriptions": sum(len(c.subscriptions) for c in self.clients.values())
            }
            return stats

    async def _cleanup_idle_clients(self) -> None:
        """Clean up idle clients."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                now = datetime.now()
                idle_clients = []

                async with self._lock:
                    for client_id, client in self.clients.items():
                        if now - client.last_activity > self.max_idle_time:
                            idle_clients.append(client_id)

                if idle_clients:
                    logger.info(f"Cleaning up {len(idle_clients)} idle clients")
                    for client_id in idle_clients:
                        await self.remove_client(client_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in idle client cleanup: {e}")
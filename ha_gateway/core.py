"""Core Home Assistant Gateway implementation.

This version uses only WebSocket API for communication with Home Assistant.
"""

import asyncio
import logging
import signal
from typing import Optional

from config import load_or_create_config
from auth import Authenticator
from protocol.websocket import HomeAssistantWebSocket, GatewayWebSocketServer
from state_manager import StateManager
from command_handler import CommandHandler


logger = logging.getLogger(__name__)


class HomeAssistantGateway:
    """Main Home Assistant Gateway class using WebSocket-only communication."""

    def __init__(self, config_path: Optional[str] = None):
        self.config = load_or_create_config(config_path)
        self.authenticator: Optional[Authenticator] = None
        self.ha_ws: Optional[HomeAssistantWebSocket] = None
        self.gateway_server: Optional[GatewayWebSocketServer] = None
        self.state_manager: Optional[StateManager] = None
        self.command_handler: Optional[CommandHandler] = None
        self.running = False
        self.shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start Home Assistant Gateway."""
        logger.info("Starting Home Assistant Gateway (WebSocket-only mode)")

        # Validate configuration
        self.config.validate()

        # Initialize components
        self.authenticator = Authenticator(self.config)
        await self.authenticator.initialize()

        self.ha_ws = HomeAssistantWebSocket(self.config, self.authenticator)
        self.state_manager = StateManager(self.config, self.ha_ws)
        self.command_handler = CommandHandler(self.config, None, self.state_manager)

        self.gateway_server = GatewayWebSocketServer(self.config, self.ha_ws)

        # Connect to Home Assistant WebSocket
        logger.info("Connecting to Home Assistant via WebSocket...")
        await self.ha_ws.connect()
        logger.info("Connected to Home Assistant successfully")

        # Subscribe to state changes
        logger.info("Subscribing to state changes...")
        await self.ha_ws.subscribe_state_changes(self._handle_state_change)
        logger.info("State subscription active")

        # Fetch initial states
        logger.info("Fetching initial states...")
        initial_states = await self.ha_ws.fetch_initial_states()
        logger.info(f"Loaded {len(initial_states)} initial states")

        # Start state synchronization
        await self.state_manager.start()

        # Start WebSocket server for clients
        logger.info("Starting WebSocket server for clients...")
        await self.gateway_server.start()

        self.running = True
        logger.info("Home Assistant Gateway started successfully")

        # Setup signal handlers
        for sig in [signal.SIGINT, signal.SIGTERM]:
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.stop())
            )

        # Keep running until shutdown
        await self.shutdown_event.wait()

    async def stop(self) -> None:
        """Stop Home Assistant Gateway."""
        if not self.running:
            return

        logger.info("Stopping Home Assistant Gateway")
        self.running = False

        # Signal shutdown
        self.shutdown_event.set()

        # Stop components in reverse order
        if self.gateway_server:
            await self.gateway_server.stop()

        if self.state_manager:
            await self.state_manager.stop()

        if self.ha_ws:
            await self.ha_ws.close()

        if self.authenticator:
            await self.authenticator.close()

        logger.info("Home Assistant Gateway stopped")

    async def _handle_state_change(self, state_message) -> None:
        """Handle state change from Home Assistant.

        Args:
            state_message: State update message from Home Assistant
        """
        try:
            entity_id = state_message.payload.get("entity_id")
            state = state_message.payload.get("state")

            if entity_id and state:
                logger.debug(f"State changed: {entity_id} -> {state.get('state', 'unknown')}")

                # Update state manager
                await self.state_manager.update_state(entity_id, state)

                # Broadcast to gateway clients
                if self.gateway_server:
                    await self.gateway_server.broadcast_state_change(
                        entity_id,
                        state
                    )
        except Exception as e:
            logger.error(f"Error handling state change: {e}")


async def main() -> None:
    """Main entry point for gateway."""
    import argparse

    parser = argparse.ArgumentParser(description="Home Assistant Gateway (WebSocket-only)")
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
    parser.add_argument(
        "--websocket-only",
        help="Use WebSocket API only (no HTTP fallback)",
        action="store_true",
        default=True
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    gateway = HomeAssistantGateway(args.config)
    try:
        await gateway.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
    except TimeoutError as e:
        logger.error(f"Timeout error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.exception("Full exception traceback:")
    finally:
        await gateway.stop()


if __name__ == "__main__":
    asyncio.run(main())

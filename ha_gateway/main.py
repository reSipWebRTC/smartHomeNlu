#!/usr/bin/env python3
"""Main entry point for Home Assistant Gateway."""

import os
import sys
import asyncio

# Add the ha_gateway directory to the path so we can import modules
ha_gateway_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ha_gateway_path)

# Now import the server
from server import HomeAssistantGatewayServer
import argparse

def main():
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

    import logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    server = HomeAssistantGatewayServer(args.config)

    # Use a single event loop for both start and stop
    try:
        asyncio.run(run_server(server))
    except KeyboardInterrupt:
        print("\nReceived interrupt signal")

async def run_server(server):
    """Run the server with proper shutdown handling."""
    try:
        await server.start()
        print("Gateway server started. Press Ctrl+C to stop.")

        # Keep running until stopped
        while server.running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("\nReceived cancel signal")
    except KeyboardInterrupt:
        print("\nReceived interrupt signal")
    finally:
        # Stop the server in the same event loop
        print("Cleaning up...")
        try:
            await server.stop()
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                print("Event loop already closed, skipping cleanup")
            else:
                raise
        print("Gateway server stopped")

if __name__ == "__main__":
    main()
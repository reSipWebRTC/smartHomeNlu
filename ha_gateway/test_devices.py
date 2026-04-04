#!/usr/bin/env python3
"""Test script for device management."""

import asyncio
import json
import websockets
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


async def test_devices():
    """Test device management."""
    uri = "ws://localhost:8124/ws"

    try:
        async with websockets.connect(uri) as websocket:
            logger.info("Connected to HA Gateway")

            # Test 1: List devices
            logger.info("\n=== Test 1: List Devices ===")
            list_msg = {
                "id": 1,
                "type": "list_devices"
            }
            await websocket.send(json.dumps(list_msg))
            response = json.loads(await websocket.recv())
            logger.info(f"Response: {json.dumps(response, indent=2, ensure_ascii=False)}")

            if response.get("type") == "device_list":
                devices = response.get("payload", {}).get("devices", [])
                logger.info(f"Found {len(devices)} devices")
                for device in devices:
                    logger.info(f"  - {device['name']} ({device['type']}) - {device['device_id']}")

            # Test 2: Get device details
            if devices:
                first_device = devices[0]
                device_id = first_device['device_id']

                logger.info(f"\n=== Test 2: Get Device Details ({device_id}) ===")
                get_msg = {
                    "id": 2,
                    "type": "get_device",
                    "payload": {"device_id": device_id}
                }
                await websocket.send(json.dumps(get_msg))
                response = json.loads(await websocket.recv())
                logger.info(f"Response: {json.dumps(response, indent=2, ensure_ascii=False)}")

                # Test 3: Subscribe to device
                logger.info(f"\n=== Test 3: Subscribe to Device ===")
                sub_msg = {
                    "id": 3,
                    "type": "subscribe_device",
                    "payload": {"device_id": device_id}
                }
                await websocket.send(json.dumps(sub_msg))
                response = json.loads(await websocket.recv())
                logger.info(f"Response: {json.dumps(response, indent=2, ensure_ascii=False)}")

                # Test 4: Listen for device state updates
                logger.info(f"\n=== Test 4: Listen for Device State Updates ===")
                logger.info("Change the device state in Home Assistant...")
                logger.info("Waiting for updates (Ctrl+C to stop)...")

                try:
                    while True:
                        response = json.loads(await websocket.recv())
                        if response.get("type") == "device_state_update":
                            logger.info(f"\nDevice state update received:")
                            logger.info(json.dumps(response, indent=2, ensure_ascii=False))

                        elif response.get("type") == "response":
                            logger.info(f"\nResponse received:")
                            logger.info(json.dumps(response, indent=2, ensure_ascii=False))

                except KeyboardInterrupt:
                    logger.info("\nStopped listening")

    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_devices())

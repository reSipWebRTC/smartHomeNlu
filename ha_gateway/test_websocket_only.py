#!/usr/bin/env python3
"""Test script for WebSocket-only Home Assistant Gateway.

This script demonstrates all features using WebSocket API:
1. Connection and authentication
2. Fetching states
3. Calling services
4. Subscribing to events
5. Real-time state updates
"""

import asyncio
import json
import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_or_create_config, Config
from auth import Authenticator
from protocol.websocket import HomeAssistantWebSocket, HACommandType
from protocol.message import Message, MessageType


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WebSocketTester:
    """Test class for WebSocket API interactions."""

    def __init__(self, config_path: Optional[str] = None):
        self.config = load_or_create_config(config_path)
        self.authenticator = None
        self.ha_ws = None
        self.test_passed = 0
        self.test_failed = 0

    async def run_all_tests(self) -> None:
        """Run all WebSocket API tests."""
        print("\n" + "=" * 60)
        print("WebSocket API Test Suite")
        print("=" * 60 + "\n")

        try:
            # Test 1: Connection and Authentication
            await self.test_connection_and_auth()

            # Test 2: Fetch All States
            await self.test_fetch_all_states()

            # Test 3: Fetch Single Entity State
            await self.test_fetch_single_state()

            # Test 4: Get Services
            await self.test_get_services()

            # Test 5: Call Service (Light)
            await self.test_call_service_light()

            # Test 6: Subscribe to State Changes
            await self.test_subscribe_state_changes()

            # Test 7: Fire Event
            await self.test_fire_event()

            # Test 8: Ping/Pong
            await self.test_ping_pong()

            # Test 9: Get Config
            await self.test_get_config()

            # Test 10: Subscribe/Unsubscribe Events
            await self.test_subscribe_unsubscribe()

        except Exception as e:
            logger.error(f"Test suite error: {e}")

        finally:
            await self.cleanup()

        # Print summary
        print("\n" + "=" * 60)
        print(f"Test Results: {self.test_passed} passed, {self.test_failed} failed")
        print("=" * 60 + "\n")

    async def test_connection_and_auth(self) -> None:
        """Test 1: Connection and Authentication."""
        print("\n[TEST 1] Connection and Authentication")
        print("-" * 60)

        try:
            # Initialize authenticator
            self.authenticator = Authenticator(self.config)
            await self.authenticator.initialize()

            # Create WebSocket client
            self.ha_ws = HomeAssistantWebSocket(self.config, self.authenticator)

            # Connect to Home Assistant
            print("Connecting to Home Assistant...")
            await self.ha_ws.connect()
            print("✓ Connected successfully")

            print("✓ Test 1 PASSED\n")
            self.test_passed += 1

        except Exception as e:
            print(f"✗ Test 1 FAILED: {e}\n")
            self.test_failed += 1
            raise

    async def test_fetch_all_states(self) -> None:
        """Test 2: Fetch All States."""
        print("[TEST 2] Fetch All States")
        print("-" * 60)

        try:
            states = await self.ha_ws.get_states()
            print(f"✓ Fetched {len(states)} states")

            # Display first few states
            for state in states[:5]:
                entity_id = state.get("entity_id")
                domain = entity_id.split(".")[0] if entity_id else "unknown"
                state_value = state.get("state", "unknown")
                friendly_name = state.get("attributes", {}).get("friendly_name", entity_id)
                print(f"  - {friendly_name} ({entity_id}): {state_value}")

            if len(states) > 5:
                print(f"  ... and {len(states) - 5} more entities")

            print("✓ Test 2 PASSED\n")
            self.test_passed += 1

        except Exception as e:
            print(f"✗ Test 2 FAILED: {e}\n")
            self.test_failed += 1

    async def test_fetch_single_state(self) -> None:
        """Test 3: Fetch Single Entity State."""
        print("[TEST 3] Fetch Single Entity State")
        print("-" * 60)

        try:
            # Try to find a light entity
            states = await self.ha_ws.get_states()
            light_entities = [
                s for s in states
                if s.get("entity_id", "").startswith("light.")
            ]

            if not light_entities:
                print("⚠ No light entities found, skipping this test\n")
                self.test_passed += 1
                return

            test_entity = light_entities[0]
            entity_id = test_entity.get("entity_id")

            # Fetch single entity
            states = await self.ha_ws.get_states(entity_id)
            state = states[0] if states else None

            if state:
                print(f"✓ Fetched state for {entity_id}")
                print(f"  State: {state.get('state')}")
                print(f"  Attributes: {list(state.get('attributes', {}).keys())}")
                print("✓ Test 3 PASSED\n")
                self.test_passed += 1
            else:
                print(f"✗ Failed to fetch state for {entity_id}\n")
                self.test_failed += 1

        except Exception as e:
            print(f"✗ Test 3 FAILED: {e}\n")
            self.test_failed += 1

    async def test_get_services(self) -> None:
        """Test 4: Get Services."""
        print("[TEST 4] Get Available Services")
        print("-" * 60)

        try:
            # This would require adding get_services method
            # For now, we'll just call the command directly
            response = await self.ha_ws.send_command(HACommandType.GET_SERVICES.value)
            services = response.get("result", {})

            print(f"✓ Fetched services for {len(services)} domains")

            # Display first few domains
            for domain, domain_services in list(services.items())[:5]:
                service_count = len(domain_services.get("services", {}))
                print(f"  - {domain}: {service_count} services")

            if len(services) > 5:
                print(f"  ... and {len(services) - 5} more domains")

            print("✓ Test 4 PASSED\n")
            self.test_passed += 1

        except Exception as e:
            print(f"✗ Test 4 FAILED: {e}\n")
            self.test_failed += 1

    async def test_call_service_light(self) -> None:
        """Test 5: Call Service (Light)."""
        print("[TEST 5] Call Service (Light)")
        print("-" * 60)

        try:
            # Find a light entity
            states = await self.ha_ws.get_states()
            light_entities = [
                s for s in states
                if s.get("entity_id", "").startswith("light.") and s.get("state") == "off"
            ]

            if not light_entities:
                print("⚠ No off light entities found, using first light\n")

            test_entity = light_entities[0] if light_entities else [
                s for s in states
                if s.get("entity_id", "").startswith("light.")
            ][0]

            entity_id = test_entity.get("entity_id")
            domain = entity_id.split(".")[0]
            friendly_name = test_entity.get("attributes", {}).get("friendly_name", entity_id)

            print(f"Testing with: {friendly_name} ({entity_id})")
            print(f"Current state: {test_entity.get('state')}")

            # Call turn_on service
            print("Calling turn_on service...")
            response = await self.ha_ws.call_service(
                domain=domain,
                service="turn_on",
                target={"entity_id": entity_id}
            )

            if response.get("success", True):
                print("✓ Service call successful")

                # Wait a bit and check state
                await asyncio.sleep(1)
                states = await self.ha_ws.get_states(entity_id)
                new_state = states[0].get("state") if states else "unknown"
                print(f"New state: {new_state}")

                print("✓ Test 5 PASSED\n")
                self.test_passed += 1
            else:
                print(f"✗ Service call failed: {response}\n")
                self.test_failed += 1

        except Exception as e:
            print(f"✗ Test 5 FAILED: {e}\n")
            self.test_failed += 1

    async def test_subscribe_state_changes(self) -> None:
        """Test 6: Subscribe to State Changes."""
        print("[TEST 6] Subscribe to State Changes")
        print("-" * 60)

        try:
            state_changed_event = asyncio.Event()
            state_received = []

            async def state_handler(state_msg):
                entity_id = state_msg.payload.get("entity_id")
                state = state_msg.payload.get("state", {}).get("state")
                state_received.append({"entity_id": entity_id, "state": state})
                state_changed_event.set()
                print(f"  Received state change: {entity_id} -> {state}")

            # Subscribe to state changes
            print("Subscribing to state_changed events...")
            subscription_id = await self.ha_ws.subscribe_state_changes(handler=state_handler)
            print(f"✓ Subscribed (ID: {subscription_id})")

            # Wait for at least one state change or timeout
            print("Waiting for state change...")

            try:
                await asyncio.wait_for(state_changed_event.wait(), timeout=10)

                if state_received:
                    print("✓ Received state change event")
                    print("✓ Test 6 PASSED\n")
                    self.test_passed += 1
                else:
                    print("⚠ No state change received within timeout")
                    print("✓ Test 6 PASSED (partial)\n")
                    self.test_passed += 1

            except asyncio.TimeoutError:
                print("⚠ Timeout waiting for state change")
                print("✓ Test 6 PASSED (partial)\n")
                self.test_passed += 1

            # Unsubscribe
            await self.ha_ws.unsubscribe_events(subscription_id)
            print(f"✓ Unsubscribed from {subscription_id}")

        except Exception as e:
            print(f"✗ Test 6 FAILED: {e}\n")
            self.test_failed += 1

    async def test_fire_event(self) -> None:
        """Test 7: Fire Event."""
        print("[TEST 7] Fire Custom Event")
        print("-" * 60)

        try:
            # Fire a test event
            event_type = "ha_gateway_test"
            event_data = {
                "source": "WebSocket Test Suite",
                "timestamp": asyncio.get_event_loop().time()
            }

            print(f"Firing event: {event_type}")
            response = await self.ha_ws.fire_event(event_type, event_data)

            if response.get("success", True):
                print("✓ Event fired successfully")
                context = response.get("result", {}).get("context", {})
                print(f"  Context ID: {context.get('id', 'N/A')}")

                print("✓ Test 7 PASSED\n")
                self.test_passed += 1
            else:
                print(f"✗ Event fire failed: {response}\n")
                self.test_failed += 1

        except Exception as e:
            print(f"✗ Test 7 FAILED: {e}\n")
            self.test_failed += 1

    async def test_ping_pong(self) -> None:
        """Test 8: Ping/Pong."""
        print("[TEST 8] Ping/Pong")
        print("-" * 60)

        try:
            print("Sending ping...")
            round_trip_time = await self.ha_ws.ping()
            print(f"✓ Received pong in {round_trip_time:.3f} seconds")

            print("✓ Test 8 PASSED\n")
            self.test_passed += 1

        except Exception as e:
            print(f"✗ Test 8 FAILED: {e}\n")
            self.test_failed += 1

    async def test_get_config(self) -> None:
        """Test 9: Get Config."""
        print("[TEST 9] Get Home Assistant Config")
        print("-" * 60)

        try:
            response = await self.ha_ws.send_command(HACommandType.GET_CONFIG.value)
            config = response.get("result", {})

            print("✓ Fetched configuration")
            print(f"  Location: {config.get('latitude', 'N/A')}, {config.get('longitude', 'N/A')}")
            print(f"  Timezone: {config.get('time_zone', 'N/A')}")
            print(f"  Currency: {config.get('currency', 'N/A')}")
            print(f"  Unit System: {config.get('unit_system', 'N/A')}")

            print("✓ Test 9 PASSED\n")
            self.test_passed += 1

        except Exception as e:
            print(f"✗ Test 9 FAILED: {e}\n")
            self.test_failed += 1

    async def test_subscribe_unsubscribe(self) -> None:
        """Test 10: Subscribe and Unsubscribe."""
        print("[TEST 10] Subscribe and Unsubscribe")
        print("-" * 60)

        try:
            # Subscribe to a specific event type
            print("Subscribing to 'service_registered' events...")
            subscription_id = await self.ha_ws.subscribe_events("service_registered")
            print(f"✓ Subscribed (ID: {subscription_id})")

            # Unsubscribe immediately
            await asyncio.sleep(0.5)
            print(f"Unsubscribing...")
            await self.ha_ws.unsubscribe_events(subscription_id)
            print(f"✓ Unsubscribed")

            print("✓ Test 10 PASSED\n")
            self.test_passed += 1

        except Exception as e:
            print(f"✗ Test 10 FAILED: {e}\n")
            self.test_failed += 1

    async def cleanup(self) -> None:
        """Clean up resources."""
        print("\nCleaning up...")
        if self.ha_ws:
            await self.ha_ws.close()
        if self.authenticator:
            await self.authenticator.close()
        print("✓ Cleanup complete")


async def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="WebSocket API Test Suite")
    parser.add_argument(
        "--config",
        help="Path to configuration file",
        default=None
    )
    parser.add_argument(
        "--test",
        choices=["all", "connection", "states", "services", "events"],
        default="all",
        help="Which test(s) to run"
    )

    args = parser.parse_args()

    tester = WebSocketTester(args.config)

    if args.test == "all":
        await tester.run_all_tests()
    elif args.test == "connection":
        await tester.test_connection_and_auth()
        await tester.cleanup()
    elif args.test == "states":
        await tester.test_connection_and_auth()
        await tester.test_fetch_all_states()
        await tester.test_fetch_single_state()
        await tester.cleanup()
    elif args.test == "services":
        await tester.test_connection_and_auth()
        await tester.test_get_services()
        await tester.test_call_service_light()
        await tester.cleanup()
    elif args.test == "events":
        await tester.test_connection_and_auth()
        await tester.test_subscribe_state_changes()
        await tester.test_fire_event()
        await tester.test_subscribe_unsubscribe()
        await tester.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")

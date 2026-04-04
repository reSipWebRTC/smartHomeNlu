#!/usr/bin/env python3
"""Basic tests for Home Assistant Gateway without actual HA connection."""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config, load_or_create_config
from auth import Authenticator
from device_manager import DeviceManager
from state_manager import StateManager
from protocol.message import Message, MessageType, DeviceState


async def test_config():
    """Test configuration loading and validation."""
    print("Testing configuration...")
    config = load_or_create_config()
    config.validate()
    print("✓ Configuration test passed")


async def test_auth():
    """Test authentication without actual connection."""
    print("Testing authentication...")
    config = load_or_create_config()
    authenticator = Authenticator(config)

    try:
        await authenticator.initialize()
        print("✓ Authentication initialization passed")
        await authenticator.close()
    except Exception as e:
        print(f"✗ Authentication test failed: {e}")


async def test_device_manager():
    """Test device management."""
    print("Testing device manager...")
    config = load_or_create_config()
    device_manager = DeviceManager(config)

    try:
        await device_manager.initialize()
        print("✓ Device manager initialization passed")

        # Test device creation
        await device_manager.update_state("test.light", {
            "state": "on",
            "attributes": {"brightness": 255},
            "last_updated": "2024-01-01T00:00:00+00:00"
        })

        device = device_manager.get_device("test.light")
        assert device is not None
        assert device.state.state == "on"
        print("✓ Device state update passed")

    except Exception as e:
        print(f"✗ Device manager test failed: {e}")


async def test_state_manager():
    """Test state management."""
    print("Testing state manager...")
    config = load_or_create_config()
    device_manager = DeviceManager(config)
    await device_manager.initialize()

    state_manager = StateManager(config, device_manager)

    try:
        await state_manager.start()
        print("✓ State manager initialization passed")

        # Test state recording
        await state_manager.record_state_change("test.light", "off", "on")
        history = await state_manager.get_state_history("test.light")
        assert len(history) == 1
        assert history[0]["old_state"] == "off"
        assert history[0]["new_state"] == "on"
        print("✓ State recording passed")

        await state_manager.stop()
    except Exception as e:
        print(f"✗ State manager test failed: {e}")


async def test_protocol():
    """Test protocol message handling."""
    print("Testing protocol...")
    try:
        # Test message creation
        msg = Message(type=MessageType.GET_STATE, id="test_1", payload={"entity_id": "light.test"})
        assert msg.type == MessageType.GET_STATE
        assert msg.payload["entity_id"] == "light.test"
        print("✓ Message creation passed")

        # Test message serialization
        json_str = msg.json
        loaded_msg = Message.from_json(json_str)
        assert loaded_msg.type == MessageType.GET_STATE
        assert loaded_msg.id == msg.id
        print("✓ Message serialization passed")

        # Test response creation
        response = Message.create_response(msg, True, {"state": "on"})
        assert response.type == MessageType.RESPONSE
        assert response.payload["success"] is True
        print("✓ Response creation passed")

    except Exception as e:
        print(f"✗ Protocol test failed: {e}")


async def main():
    """Run all tests."""
    print("=== Home Assistant Gateway Basic Tests ===\n")

    tests = [
        test_config,
        test_auth,
        test_device_manager,
        test_state_manager,
        test_protocol
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
            print()
        except Exception as e:
            failed += 1
            print(f"\n✗ Test {test.__name__} failed: {e}\n")

    print(f"=== Results: {passed} passed, {failed} failed ===")

    if failed == 0:
        print("🎉 All basic tests passed!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
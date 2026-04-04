#!/usr/bin/env python3
"""Quick test to verify WebSocket implementation works."""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, load_or_create_config
from auth import Authenticator


async def test_basic_setup():
    """Test basic WebSocket setup without connecting."""
    print("Testing basic setup...")

    # Test config loading
    try:
        config = load_or_create_config()
        print(f"✓ Config loaded: HA URL = {config.home_assistant.url}")
    except Exception as e:
        print(f"✗ Config failed: {e}")
        return False

    # Test authenticator
    try:
        auth = Authenticator(config)
        await auth.initialize()
        print("✓ Authenticator initialized")
        await auth.close()
    except Exception as e:
        print(f"✗ Authenticator failed: {e}")
        return False

    # Test WebSocket class import
    try:
        from protocol.websocket import HomeAssistantWebSocket, HACommandType
        print("✓ WebSocket classes imported")
        print(f"✓ HACommandType enum: {[c.value for c in HACommandType]}")
    except Exception as e:
        print(f"✗ WebSocket import failed: {e}")
        return False

    # Test message classes
    try:
        from protocol.message import Message, MessageType
        print("✓ Message classes imported")
        print(f"✓ MessageType enum: {[m.value for m in MessageType]}")
    except Exception as e:
        print(f"✗ Message import failed: {e}")
        return False

    print("\nAll basic tests passed!")
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(test_basic_setup())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

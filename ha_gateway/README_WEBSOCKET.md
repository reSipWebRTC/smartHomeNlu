# Home Assistant Gateway - WebSocket Only Implementation

This version of the Home Assistant Gateway communicates exclusively with Home Assistant via the WebSocket API, eliminating all HTTP API dependencies.

## Overview

The WebSocket-only implementation provides:

- **Real-time bidirectional communication** with Home Assistant
- **State subscription and live updates** without polling
- **Service calling** via WebSocket
- **Event firing and subscription** via WebSocket
- **Automatic reconnection** with exponential backoff
- **Message coalescing** for improved performance
- **No HTTP API fallback** - pure WebSocket communication

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Client Applications                     │
│              (WebSocket Clients)                        │
└────────────────────┬────────────────────────────────────────┘
                     │ WebSocket (Gateway Protocol)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│              Gateway WebSocket Server                      │
│         (aiohttp, /ws endpoint)                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ WebSocket (Home Assistant Protocol)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│           Home Assistant Instance                        │
│         (/api/websocket endpoint)                       │
└─────────────────────────────────────────────────────────────────┘
```

## WebSocket API Commands Used

### 1. Connection & Authentication

```python
# Authentication flow (automatic in HomeAssistantWebSocket)
{
    "type": "auth",
    "access_token": "YOUR_ACCESS_TOKEN"
}

# Response
{
    "type": "auth_ok",
    "ha_version": "202X.Y.Z"
}
```

### 2. Feature Enablement

```python
{
    "id": 1,
    "type": "supported_features",
    "features": {
        "coalesce_messages": 1
    }
}
```

### 3. Get States

```python
# Get all states
{
    "id": 1,
    "type": "get_states"
}

# Response
{
    "id": 1,
    "type": "result",
    "success": true,
    "result": [
        {
            "entity_id": "light.living_room",
            "state": "on",
            "attributes": {
                "friendly_name": "Living Room",
                "brightness": 255
            },
            "last_changed": "2024-01-01T12:00:00Z",
            "last_updated": "2024-01-01T12:00:00Z",
            "context": {
                "id": "...",
                "parent_id": null,
                "user_id": "..."
            }
        },
        ...
    ]
}
```

### 4. Call Service

```python
{
    "id": 2,
    "type": "call_service",
    "domain": "light",
    "service": "turn_on",
    "target": {
        "entity_id": "light.living_room"
    },
    "service_data": {
        "brightness": 255,
        "color_name": "blue"
    }
    # Optional: include only when the target service supports response payloads.
    # "return_response": true
}

# Response
{
    "id": 2,
    "type": "result",
    "success": true,
    "result": {
        "context": { ... }
    }
}
```

When `return_response` is set to `true` for a service that does not support response
payloads, Home Assistant can return `service_validation_error`
(`service_does_not_support_response`).

### 5. Subscribe to Events

```python
{
    "id": 3,
    "type": "subscribe_events",
    "event_type": "state_changed"
}

# Response
{
    "id": 3,
    "type": "result",
    "success": true,
    "result": null
}

# Event notifications
{
    "id": 3,
    "type": "event",
    "event": {
        "event_type": "state_changed",
        "data": {
            "entity_id": "light.living_room",
            "old_state": { ... },
            "new_state": { ... }
        },
        "origin": "LOCAL",
        "time_fired": "2024-01-01T12:00:00Z"
    }
}
```

### 6. Unsubscribe Events

```python
{
    "id": 4,
    "type": "unsubscribe_events",
    "subscription": 3  # The ID from subscribe_events
}

# Response
{
    "id": 4,
    "type": "result",
    "success": true,
    "result": null
}
```

### 7. Fire Event

```python
{
    "id": 5,
    "type": "fire_event",
    "event_type": "custom_event",
    "event_data": {
        "key": "value"
    }
}

# Response
{
    "id": 5,
    "type": "result",
    "success": true,
    "result": {
        "context": { ... }
    }
}
```

### 8. Ping/Pong

```python
# Client ping
{
    "id": 6,
    "type": "ping"
}

# Server pong
{
    "id": 6,
    "type": "pong"
}
```

### 9. Get Services

```python
{
    "id": 7,
    "type": "get_services"
}

# Response
{
    "id": 7,
    "type": "result",
    "success": true,
    "result": {
        "light": {
            "services": {
                "turn_on": { ... },
                "turn_off": { ... }
            }
        },
        ...
    }
}
```

### 10. Get Config

```python
{
    "id": 8,
    "type": "get_config"
}

# Response
{
    "id": 8,
    "type": "result",
    "success": true,
    "result": {
        "latitude": 37.7749,
        "longitude": -122.4194,
        "unit_system": "metric",
        "time_zone": "America/Los_Angeles",
        ...
    }
}
```

## Key Classes

### HomeAssistantWebSocket

Main WebSocket client for Home Assistant communication.

**Key Methods:**

- `connect()` - Establish WebSocket connection and authenticate
- `disconnect()` - Close WebSocket connection
- `close()` - Clean up resources
- `send_command(command_type, **kwargs)` - Send command and await response
- `get_states(entity_id=None)` - Fetch entity states
- `call_service(domain, service, ...)` - Call HA service
- `subscribe_events(event_type, handler)` - Subscribe to events
- `unsubscribe_events(subscription)` - Unsubscribe from events
- `fire_event(event_type, event_data)` - Fire custom event
- `ping()` - Send ping for connection health
- `subscribe_state_changes(handler)` - Subscribe to state_changed events
- `fetch_initial_states()` - Fetch all states on connection

### GatewayWebSocketServer

WebSocket server for external client connections.

**Key Methods:**

- `start()` - Start the WebSocket server
- `stop()` - Stop the WebSocket server
- `broadcast_state_change(entity_id, state)` - Broadcast to all subscribed clients

### StateManager

Manages state cache and history.

**Key Methods:**

- `update_state(entity_id, state_data)` - Update from event
- `get_state(entity_id)` - Get cached or fetch state
- `get_all_states()` - Get all cached states
- `sync_all_states()` - Sync all states from HA
- `add_state_callback(callback)` - Add state change listener
- `get_entity_statistics(entity_id, period_hours)` - Get state statistics

## Configuration

The gateway uses the same configuration file format:

```yaml
# config.yaml
home_assistant:
  url: "http://localhost:8123"
  access_token: "YOUR_ACCESS_TOKEN"

gateway:
  host: "0.0.0.0"
  port: 54321

cache:
  enabled: true
  ttl: 60
  max_history: 100

performance:
  max_reconnect_attempts: 5
  reconnect_delay: 5
```

## Usage

### Starting the Gateway

```bash
python -m ha_gateway.core --config config.yaml
```

### Running Tests

```bash
# Run all tests
python ha_gateway/test_websocket_only.py

# Run specific test categories
python ha_gateway/test_websocket_only.py --test connection
python ha_gateway/test_websocket_only.py --test states
python ha_gateway/test_websocket_only.py --test services
python ha_gateway/test_websocket_only.py --test events
```

### Client Protocol

Clients connect to `ws://gateway-host:gateway-port/ws` using JSON messages:

```json
// Discover devices
{
    "type": "discover",
    "id": "unique-id",
    "payload": {}
}

// Get state
{
    "type": "get_state",
    "id": "unique-id",
    "payload": {
        "entity_id": "light.living_room"
    }
}

// Set state
{
    "type": "set_state",
    "id": "unique-id",
    "payload": {
        "entity_id": "light.living_room",
        "state": "on"
    }
}

// Subscribe
{
    "type": "subscribe",
    "id": "unique-id",
    "payload": {
        "entity_id": "light.living_room"
    }
}

// Response format
{
    "type": "response",
    "id": "same-as-request",
    "payload": {
        "success": true,
        "data": { ... }
    }
}
```

## Error Handling

All commands that fail will return an error response:

```json
{
    "id": 1,
    "type": "result",
    "success": false,
    "error": {
        "code": "invalid_format",
        "message": "Message incorrectly formatted."
    }
}
```

Common error codes:

- `invalid_format` - Message format error
- `unknown_command` - Command not recognized
- `unauthorized` - Authentication failed
- `service_validation_error` - Service call validation failed
- `home_assistant_error` - General Home Assistant error

## Reconnection Strategy

The WebSocket client automatically reconnects on connection loss:

1. Detect connection failure
2. Wait for `reconnect_delay` seconds (configurable)
3. Attempt reconnection (up to `max_reconnect_attempts` times)
4. On success: Restore subscriptions and sync states
5. On failure: Increment attempt count and retry

## Performance Features

### Message Coalescing

Enables batching of multiple messages for reduced network overhead:

```python
# Enabled automatically after authentication
{
    "type": "supported_features",
    "features": {
        "coalesce_messages": 1
    }
}
```

### State Caching

Local state cache reduces WebSocket calls:

1. States are cached after initial fetch
2. Cache is updated by state_changed events
3. Periodic sync ensures cache consistency
4. Cache TTL is configurable

## Migration from HTTP API

If migrating from HTTP-only gateway:

1. **Update configuration** - No changes needed for basic config
2. **Update clients** - WebSocket is now required (no HTTP fallback)
3. **Handle new message types** - Event-based updates instead of polling

Key differences from HTTP API:

| Feature | HTTP API | WebSocket API |
|----------|-----------|---------------|
| State updates | Polling required | Real-time push |
| Connection | Per-request | Persistent |
| Latency | Higher (per request) | Lower (persistent) |
| Server load | More (polling) | Less (event-driven) |
| Bandwidth | More (full responses) | Less (incremental) |

## Troubleshooting

### Connection Issues

```python
# Check configuration
- URL should be reachable
- Access token should be valid
- Firewall should allow WebSocket connections

# Enable debug logging
python -m ha_gateway.core --config config.yaml --log-level DEBUG
```

### State Not Updating

```python
# Check subscription status
# State subscriptions should be active

# Verify WebSocket connection
# Gateway should maintain active connection

# Check state cache
# StateManager maintains local cache
```

### Service Call Failures

```python
# Verify domain and service exist
# Use get_services to check

# Check target specification
# entity_id, area_id, device_id formats

# Review service_data format
# Must match service schema
```

## Security Considerations

1. **Access Tokens** - Store securely, never log
2. **SSL/TLS** - Enable in production (set `ssl=True`)
3. **Authentication** - All connections require valid token
4. **Input Validation** - Validate all client inputs
5. **Rate Limiting** - Consider implementing rate limits for clients

## Future Enhancements

Potential improvements to consider:

- [ ] Binary message support for large payloads
- [ ] WebSocket compression
- [ ] Query parameters for get_states (filtering)
- [ ] Batch command support
- [ ] Advanced subscription filters
- [ ] Metrics and monitoring endpoints
- [ ] WebSocket subprotocol negotiation

## References

- [Home Assistant WebSocket API Docs](https://developers.home-assistant.io/docs/api/websocket/)
- [WebSocket Protocol RFC](https://datatracker.ietf.org/doc/html/rfc6455/)
- [aiohttp Documentation](https://docs.aiohttp.org/)

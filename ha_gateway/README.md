# Home Assistant Gateway

A standalone Home Assistant bridge that provides a unified WebSocket interface for connecting clients to Home Assistant devices and services.

## Features

- **WebSocket Interface**: Exposes Home Assistant devices via WebSocket
- **Device Discovery**: Automatically discovers and manages Home Assistant devices
- **State Synchronization**: Real-time state updates between Home Assistant and connected clients
- **Service Calls**: Execute Home Assistant services through the gateway
- **Authentication**: Secure authentication with multiple methods
- **Client Management**: Multiple client support with subscription management
- **Performance Optimized**: Batched updates and connection pooling

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd ha_gateway
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create configuration:
```bash
cp example_config.yaml ~/.ha_gateway/config.yaml
```

4. Edit the configuration file with your Home Assistant details:
```bash
nano ~/.ha_gateway/config.yaml
```

## Configuration

The gateway supports several configuration options:

### Home Assistant Connection

- `url`: Your Home Assistant instance URL (default: http://localhost:8123)
- `auth_type`: Authentication method (long_lived_token, username_password, oauth2)
- `access_token`: Long-lived access token for authentication
- `username`: Username for password authentication
- `password`: Password for authentication

### Gateway Server

- `host`: Host to bind to (0.0.0.0 for all interfaces)
- `port`: Port to listen on (default: 8124)
- `max_connections`: Maximum concurrent connections
- `idle_timeout`: Client idle timeout in seconds

### Device Filtering

- `include_domains`: List of device domains to include
- `exclude_entities`: List of entity IDs to exclude
- `include`: Additional include patterns
- `exclude`: Additional exclude patterns

## Usage

### Starting the Gateway

```bash
# Using default config (~/.ha_gateway/config.yaml)
python -m ha_gateway.server

# Using custom config
python -m ha_gateway.server --config /path/to/config.yaml

# With debug logging
python -m ha_gateway.server --log-level DEBUG
```

### Client Connection

Connect to the gateway WebSocket:

```javascript
const ws = new WebSocket('ws://localhost:8124/ws');

ws.onmessage = function(event) {
    const message = JSON.parse(event.data);
    console.log('Received:', message);
};

// Send commands
ws.send(JSON.stringify({
    type: 'discover',
    id: 'discover_1',
    payload: {}
}));

ws.send(JSON.stringify({
    type: 'get_state',
    id: 'get_state_1',
    payload: {
        entity_id: 'light.bedroom'
    }
}));

ws.send(JSON.stringify({
    type: 'set_state',
    id: 'set_state_1',
    payload: {
        entity_id: 'light.bedroom',
        state: 'on'
    }
}));

ws.send(JSON.stringify({
    type: 'call_service',
    id: 'call_service_1',
    payload: {
        domain: 'light',
        service: 'turn_on',
        service_data: {
            entity_id: 'light.bedroom'
        }
    }
}));
```

### Message Types

#### Client to Gateway

- `discover`: Discover all available devices
- `get_state`: Get state of a specific entity
- `set_state`: Set state of an entity
- `call_service`: Call a Home Assistant service
- `subscribe`: Subscribe to state changes
- `unsubscribe`: Unsubscribe from state changes
- `ping`: Ping the gateway

#### Gateway to Client

- `state_update`: State change notification
- `discover_devices`: Response to discover command
- `response`: Response to commands
- `error`: Error message

## Architecture

```
ha_gateway/
├── __init__.py              # Package initialization
├── config.py                # Configuration management
├── auth.py                  # Authentication module
├── core.py                  # Core gateway logic
├── server.py                # Main server implementation
├── client.py                # Client management
├── device_manager.py        # Device and state management
├── state_manager.py         # State management
├── command_handler.py       # Command processing
├── protocol/                # Protocol handling
│   ├── __init__.py
│   ├── websocket.py         # WebSocket implementation
│   └── message.py          # Message format definition
├── requirements.txt         # Dependencies
└── example_config.yaml      # Example configuration
```

## Security Considerations

- **Network Security**: The gateway should be deployed on a trusted network
- **Authentication**: Always use authentication tokens
- **Access Control**: Implement proper client authentication in production
- **Encryption**: Consider using WSS (WebSocket Secure) in production

## Performance Tips

- Adjust `batch_size` and `batch_delay` for your use case
- Use device filtering to limit unnecessary state updates
- Monitor client connections to prevent resource exhaustion

## Troubleshooting

### Common Issues

1. **Connection Refused**: Check if Home Assistant is running and accessible
2. **Authentication Failed**: Verify your access token or credentials
3. **Device Not Found**: Check device filtering configuration
4. **High Memory Usage**: Adjust cache settings

### Logs

Check the logs for detailed information:
```bash
tail -f ~/.ha_gateway.log
```

## Development

To contribute to this project:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.
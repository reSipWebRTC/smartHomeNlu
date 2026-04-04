# KNX Integration Setup Guide

This guide shows how to enable and test the KNX integration between HA Gateway and KNX Gateway.

## Prerequisites

1. Install Python dependencies:
```bash
cd /home/david/Work/hass/ha_gateway
pip install -r requirements.txt
cd /home/david/Work/hass/knx_gateway
pip install -r requirements.txt
```

2. Start KNX Gateway:
```bash
cd /home/david/Work/hass/knx_gateway
python3 main.py
```

3. Start HA Gateway (with KNX integration enabled):
```bash
cd /home/david/Work/hass/ha_gateway
python3 server.py
```

## Configuration

Enable KNX integration by editing your `~/.ha_gateway/config.yaml`:

```yaml
# Add these settings to your config file
knx:
  enabled: true
  knx_gateway_url: "ws://localhost:8125/ws"
  reconnect_interval: 5
  max_retries: 10
  request_timeout: 30
```

## How It Works

### 1. KNX Address Allocation

When HA Gateway detects a new KNX-compatible device, it automatically:
- Registers the device with KNX Gateway
- Receives KNX addresses (physical and group addresses)
- Creates a mapping between the entity and KNX addresses

### 2. Device-Entity Mapping

HA Gateway maintains mappings between:
- Home Assistant entity IDs (e.g., `light.living_room`)
- KNX group addresses (e.g., `1/1/1` for control, `1/1/3` for brightness)
- KNX data types (DPT)

### 3. Bidirectional Control

The system supports two-way communication:

#### HA → KNX (State Sync)
- When a device state changes in Home Assistant
- HA Gateway converts the state to KNX format
- Sends the command to KNX Gateway
- KNX Gateway broadcasts to KNX bus

#### KNX → HA (Control)
- When a KNX device is controlled
- KNX Gateway receives the command
- Converts to HA service call
- HA Gateway executes the service

## Testing

Run the integration test to verify all functions:

```bash
python3 test_knx_integration_complete.py
```

## Supported Device Types

The following device types are KNX-compatible:
- **Lights**: On/off, brightness, color temperature
- **Switches**: On/off control
- **Covers**: Position control, tilt
- **Climate**: Temperature, mode, fan speed
- **Fans**: Speed control
- **Humidifiers**: On/off, humidity level
- **Locks**: Lock/unlock
- **Media Players**: Play/pause, volume

## Message Flow

### Device Registration
```
HA Gateway → KNX Gateway
{
    "type": "register_device",
    "payload": {
        "device_id": "living_room_light",
        "device_name": "客厅灯",
        "device_type": "light",
        "capabilities": ["power_control", "brightness_control"]
    }
}

KNX Gateway → HA Gateway
{
    "type": "address_assigned",
    "payload": {
        "device_id": "living_room_light",
        "success": true,
        "address_info": {
            "physical_address": "1/1.1",
            "group_addresses": {
                "control": "1/1/1",
                "brightness": "1/1/3"
            }
        }
    }
}
```

### State Sync
```
HA Device Change → HA Gateway → KNX Gateway → KNX Bus
```

### Control Command
```
KNX Device → KNX Gateway → HA Gateway → HA Service Call
```

## Troubleshooting

1. **Connection Issues**
   - Check if KNX Gateway is running on port 8125
   - Verify WebSocket URL in configuration
   - Check firewall settings

2. **Address Allocation Failed**
   - Ensure KNX Gateway has available addresses
   - Check device compatibility
   - Verify device registration format

3. **State Sync Issues**
   - Check KNX mapping is created correctly
   - Verify state conversion rules
   - Check KNX Gateway log for errors

4. **Control Commands Failed**
   - Verify device exists in HA
   - Check service name and parameters
   - Review HA Gateway logs

## Advanced Configuration

### Custom Address Allocation
You can customize address allocation by modifying `knx_gateway/config.py`.

### State Conversion Rules
Add custom state conversion in `knx_integration.py` by modifying the `_convert_to_knx_format` method.

### Security
For production use, consider:
- Adding API key authentication
- Implementing IP whitelisting
- Using TLS for WebSocket connections

## Monitoring

Both gateways provide detailed logging:
- KNX Gateway: `knx_gateway.log`
- HA Gateway: `ha_gateway.log`

Use log level `DEBUG` for troubleshooting:
```yaml
log_level: "DEBUG"
```

## Performance Tuning

For large installations:
- Adjust batch sizes in configuration
- Increase connection timeouts
- Enable message coalescing
- Monitor memory usage

## Examples

### Example: Living Room Light
```
Device: light.living_room
KNX Control: 1/1/1 (DPT1.001)
KNX Brightness: 1/1/3 (DPT5.001)
```

### Example: Bedroom Switch
```
Device: switch.bedroom
KNX Control: 2/1/1 (DPT1.001)
```

This integration provides a seamless bridge between Home Assistant and KNX systems, enabling full bidirectional control and synchronization.
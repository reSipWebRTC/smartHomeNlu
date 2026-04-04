# 设备管理系统文档

## 概述

设备管理系统提供统一的设备抽象层，将多个 Home Assistant 实体聚合为一个设备对象，提供给应用程序调用。

### 核心特性

- **设备聚合**: 自动将相关实体（控制实体、传感器等）聚合成一个设备
- **智能分组**: 支持多种设备分组策略（device_id、via_device、命名规则）
- **状态聚合**: 自动聚合所有实体的状态为统一的设备状态
- **能力识别**: 自动识别设备能力（亮度控制、颜色控制、功率监测等）
- **类型推断**: 自动推断设备类型（灯、开关、空调、窗帘等）

## 数据结构

### Device (设备)

```python
{
    "device_id": "abc123",           # HA 设备 ID
    "name": "智能插座",              # 设备名称
    "type": "switch",                # 设备类型
    "model": "cuco.plug.v3",         # 型号
    "manufacturer": "Xiaomi",         # 制造商
    "area_id": "living_room",         # 区域
    "primary_entity_id": "switch.plug", # 主实体ID
    "online": true,                   # 在线状态
    "state": { ... },                # 设备状态
    "capabilities": { ... },           # 设备能力
    "entities": [                     # 关联实体列表
        "switch.plug",
        "sensor.plug_power",
        "sensor.plug_energy"
    ],
    "metadata": { ... }               # 额外元数据
}
```

### DeviceState (设备状态)

```python
{
    "power_state": "on",              # 开关状态: on/off/unknown
    "power_value": 45.6,             # 当前功率 (W)
    "energy_today": 1.2,              # 今日用电 (kWh)
    "brightness": 255,                  # 亮度 (0-255)
    "color_temp": 400,                 # 色温 (mireds)
    "rgb_color": [255, 100, 50],      # RGB颜色
    "temperature": 24.5,               # 温度 (°C)
    "humidity": 45.0,                  # 湿度 (%)
    "pressure": 1013.2,                # 气压 (hPa)
    "illuminance": 500.0,              # 照度 (lux)
    "position": 80,                     # 位置 (0-100)
    "hvac_mode": "cool",               # 暖通模式
    "hvac_action": "cooling",          # 暖通动作
    "preset_mode": "home",              # 预设模式
    "fan_mode": "high",                # 风扇模式
    "swing_mode": "vertical",            # 摆风模式
    "locked": false,                     # 锁定状态
    "volume": 0.5,                      # 音量 (0-1)
    "muted": false,                     # 静音状态
    "playing": true,                     # 播放状态
    "online": true                       # 在线状态
}
```

### DeviceCapabilities (设备能力)

```python
{
    "power_control": true,           # 电源控制
    "brightness_control": true,      # 亮度控制
    "color_control": true,          # 颜色控制
    "color_temp_control": true,      # 色温控制
    "temperature_control": true,    # 温度控制
    "humidity_control": true,       # 湿度控制
    "mode_control": true,          # 模式控制
    "fan_control": true,            # 风扇控制
    "swing_control": true,          # 摆风控制
    "position_control": true,       # 位置控制
    "tilt_control": true,           # 倾斜控制
    "lock_control": true,            # 锁定控制
    "power_monitoring": true,       # 功率监测
    "energy_monitoring": true,      # 电量监测
    "temperature_sensing": true,    # 温度传感
    "humidity_sensing": true,       # 湿度传感
    "pressure_sensing": true,       # 压力传感
    "illuminance_sensing": true     # 照度传感
}
```

## 设备类型

### Light (灯)
```json
{
    "type": "light",
    "primary_entity": "light.xxx",
    "entities": ["light.xxx", "sensor.xxx_brightness"],
    "capabilities": ["power_control", "brightness_control", "color_control", "color_temp_control"],
    "state": {
        "power_state": "on",
        "brightness": 255,
        "color_temp": 400
    }
}
```

### Switch (开关)
```json
{
    "type": "switch",
    "primary_entity": "switch.xxx",
    "entities": ["switch.xxx", "sensor.xxx_power", "sensor.xxx_energy", "button.xxx_reset"],
    "capabilities": ["power_control", "power_monitoring", "energy_monitoring"],
    "state": {
        "power_state": "on",
        "power_value": 45.6,
        "energy_today": 1.2
    }
}
```

### Climate (空调/温控)
```json
{
    "type": "climate",
    "primary_entity": "climate.xxx",
    "entities": ["climate.xxx", "sensor.xxx_temperature", "sensor.xxx_humidity"],
    "capabilities": ["power_control", "temperature_control", "humidity_control", "mode_control"],
    "state": {
        "power_state": "on",
        "hvac_mode": "cool",
        "temperature": 24.5,
        "humidity": 45.0
    }
}
```

### Cover (窗帘)
```json
{
    "type": "cover",
    "primary_entity": "cover.xxx",
    "entities": ["cover.xxx", "sensor.xxx_position"],
    "capabilities": ["power_control", "position_control"],
    "state": {
        "power_state": "on",
        "position": 80
    }
}
```

## WebSocket API

### 1. 获取设备列表

**请求**:
```json
{
    "id": 1,
    "type": "list_devices",
    "payload": {
        "area_id": "living_room",  // 可选: 按区域过滤
        "type": "light"             // 可选: 按类型过滤
    }
}
```

**响应**:
```json
{
    "id": 1,
    "type": "device_list",
    "payload": {
        "devices": [
            {
                "device_id": "abc123",
                "name": "客厅灯",
                "type": "light",
                "state": { ... },
                "capabilities": { ... },
                "entities": ["light.living_room", "sensor.living_room_brightness"]
            }
        ]
    }
}
```

### 2. 获取设备详情

**请求**:
```json
{
    "id": 2,
    "type": "get_device",
    "payload": {
        "device_id": "abc123"
    }
}
```

**响应**:
```json
{
    "id": 2,
    "type": "response",
    "payload": {
        "success": true,
        "data": {
            "device_id": "abc123",
            "name": "客厅灯",
            "type": "light",
            "state": { ... },
            "capabilities": { ... },
            "entities": [ ... ]
        }
    }
}
```

### 3. 控制设备

**请求**:
```json
{
    "id": 3,
    "type": "control_device",
    "payload": {
        "device_id": "abc123",
        "action": "power_on",
        "params": {
            "brightness": 255,
            "color_temp": 400
        }
    }
}
```

**支持的设备操作**:

| 动作 | 描述 | 适用设备类型 | 参数 |
|------|------|-------------|------|
| power_on | 打开电源 | 所有 | - |
| power_off | 关闭电源 | 所有 | - |
| power_toggle | 切换电源 | 所有 | - |
| set_brightness | 设置亮度 | light | brightness: 0-255 |
| set_color_temp | 设置色温 | light | color_temp: mireds |
| set_temperature | 设置温度 | climate | temperature: °C |
| open | 打开 | cover | - |
| close | 关闭 | cover | - |
| stop | 停止 | cover | - |
| lock | 上锁 | lock | - |
| unlock | 解锁 | lock | - |
| play_pause | 播放/暂停 | media_player | - |

**响应**:
```json
{
    "id": 3,
    "type": "response",
    "payload": {
        "success": true,
        "data": {
            "device_id": "abc123",
            "action": "power_on"
        }
    }
}
```

### 4. 订阅设备

**请求**:
```json
{
    "id": 4,
    "type": "subscribe_device",
    "payload": {
        "device_id": "abc123"
    }
}
```

**响应**:
```json
{
    "id": 4,
    "type": "response",
    "payload": {
        "success": true,
        "data": {
            "subscribed": true,
            "device_id": "abc123"
        }
    }
}
```

**状态更新推送**:
```json
{
    "id": "auto-generated",
    "type": "device_state_update",
    "payload": {
        "device_id": "abc123",
        "state": {
            "power_state": "on",
            "brightness": 255,
            "color_temp": 400
        }
    }
}
```

### 5. 取消订阅设备

**请求**:
```json
{
    "id": 5,
    "type": "unsubscribe_device",
    "payload": {
        "device_id": "abc123"
    }
}
```

## 设备分组策略

### 1. 按 device_id 分组
优先使用 Home Assistant 的 `device_id` 属性，自动关联同一设备下的所有实体。

```yaml
config:
  devices:
    grouping:
      by_device_id: true  # 默认开启
```

### 2. 按 via_device 分组
对于子设备，通过 `via_device` 属性关联到父设备。

```yaml
config:
  devices:
    grouping:
      by_via_device: true  # 默认开启
```

### 3. 按命名规则分组
对于没有 `device_id` 的实体，通过命名模式分组。

```yaml
config:
  devices:
    grouping:
      by_naming_pattern: true  # 默认开启
      naming_pattern: "(.+?)_[^_]+$"  # 匹配设备前缀
```

示例：
- `plug_001_power` → 设备 `plug_001`
- `plug_001_energy` → 设备 `plug_001`
- `plug_002_power` → 设备 `plug_002`

## 使用示例

### Python 客户端

```python
import asyncio
import json
import websockets

async def main():
    uri = "ws://localhost:8124/ws"

    async with websockets.connect(uri) as ws:
        # 1. 获取设备列表
        await ws.send(json.dumps({
            "id": 1,
            "type": "list_devices"
        }))

        response = json.loads(await ws.recv())
        print(f"设备列表: {response['payload']['devices']}")

        # 2. 订阅设备状态
        device_id = response['payload']['devices'][0]['device_id']
        await ws.send(json.dumps({
            "id": 2,
            "type": "subscribe_device",
            "payload": {"device_id": device_id}
        }))

        # 3. 监听状态更新
        while True:
            msg = json.loads(await ws.recv())
            if msg['type'] == 'device_state_update':
                print(f"设备状态更新: {msg}")

asyncio.run(main())
```

### JavaScript 客户端

```javascript
const ws = new WebSocket('ws://localhost:8124/ws');

// 获取设备列表
ws.onopen = () => {
    ws.send(JSON.stringify({
        id: 1,
        type: 'list_devices'
    }));
};

// 处理响应
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'device_list') {
        console.log('设备列表:', msg.payload.devices);
        // 订阅第一个设备
        subscribeToDevice(msg.payload.devices[0].device_id);
    }

    if (msg.type === 'device_state_update') {
        console.log('设备状态更新:', msg.payload);
    }
};

// 控制设备
function controlDevice(deviceId, action) {
    ws.send(JSON.stringify({
        id: Date.now(),
        type: 'control_device',
        payload: {
            device_id: deviceId,
            action: action
        }
    }));
}

// 订阅设备
function subscribeToDevice(deviceId) {
    ws.send(JSON.stringify({
        id: Date.now(),
        type: 'subscribe_device',
        payload: {
            device_id: deviceId
        }
    }));
}
```

## 服务器启动

### 启动服务

```bash
# 默认启动
python3 server.py

# 指定配置文件
python3 server.py --config /path/to/config.yaml

# 设置日志级别
python3 server.py --log-level DEBUG

# 重启服务
pkill -f "python3 server.py"
sleep 2
python3 server.py --log-level DEBUG
```

### 启动日志示例

```
2026-03-19 10:00:00 - INFO - Starting Home Assistant Gateway Server
2026-03-19 10:00:00 - INFO - Connecting to Home Assistant...
2026-03-19 10:00:00 - INFO - Connected to Home Assistant WebSocket
2026-03-19 10:00:00 - INFO - Subscribing to state_changed events...
2026-03-19 10:00:00 - INFO - Subscribed to state_changed events with ID: 1
2026-03-19 10:00:00 - INFO - Registered state change handler with WebSocket
2026-03-19 10:00:00 - INFO - Performing initial state sync with Home Assistant...
2026-03-19 10:00:00 - INFO - Using cached initial states: 53 states
2026-03-19 10:00:00 - INFO - New device manager discovered 15 devices

======================================================================
DISCOVERED DEVICES (15 total)
======================================================================

CLIMATE (2):
  - [ON] 主卧空调
      ID: climate.bedroom_ac
      Type: climate
      Entities: 3 (climate, sensor, sensor)
      Capabilities: power_control, temperature_control, mode_control, fan_control, humidity_sensing, temperature_sensing

LIGHT (5):
  - [ON] 客厅灯
      ID: light.living_room
      Type: light
      Entities: 2 (light, sensor)
      Capabilities: power_control, brightness_control, color_control, color_temp_control

SWITCH (8):
  - [ON] 智能插座
      ID: switch.plug
      Type: switch
      Entities: 4 (switch, sensor, sensor, button)
      Capabilities: power_control, power_monitoring, energy_monitoring

======================================================================

2026-03-19 10:00:00 - INFO - Initial sync complete: loaded 53 device states
2026-03-19 10:00:00 - INFO - WebSocket server started on 0.0.0.0:8124
```

## 故障排查

### 问题1: 设备没有正确分组

**症状**: 相关实体被分散到多个设备中

**解决**:
1. 检查 Home Assistant 中设备的 `device_id` 属性是否正确设置
2. 调整分组规则配置
3. 检查实体命名是否符合命名模式

### 问题2: 设备能力识别不完整

**症状**: 设备缺少某些能力（如亮度控制）

**解决**:
1. 检查实体属性是否完整
2. 确保 Home Assistant 集成正确报告设备特性
3. 手动在配置中添加设备能力

### 问题3: 设备状态更新延迟

**症状**: Home Assistant 中状态已更新，但设备状态未同步

**解决**:
1. 检查 WebSocket 连接状态
2. 查看日志中的事件订阅状态
3. 确认 `state_changed` 事件订阅成功

### 问题4: 设备控制无响应

**症状**: 发送控制命令后设备没有响应

**解决**:
1. 确认设备主实体正确设置
2. 检查操作是否被设备支持
3. 查看 Home Assistant 日志确认服务调用状态

### 问题5: 设备状态聚合错误

**症状**: 设备状态与实际不符

**解决**:
1. 检查传感器实体是否正确关联
2. 确认传感器单位正确
3. 查看日志中的状态更新记录

## 配置文件

### 完整配置示例

```yaml
# Home Assistant 连接配置
home_assistant:
  url: "http://localhost:8123"
  auth_type: "long_lived_token"
  access_token: "your_access_token_here"
  verify_ssl: false

# 网关服务器配置
gateway:
  host: "0.0.0.0"
  port: 8124
  max_connections: 100
  idle_timeout: 300
  log_level: "INFO"

# 设备过滤配置
devices:
  include_domains: ["light", "switch", "sensor", "binary_sensor", "climate", "cover", "fan", "lock", "media_player"]
  exclude_entities: []
  exclude_ha_entities: false
  exclude_ha_entity_patterns: []

  # 设备分组规则
  grouping:
    by_device_id: true
    by_via_device: true
    by_naming_pattern: true
    naming_pattern: "(.+?)_[^_]+$"

# 缓存配置
cache:
  enabled: true
  ttl: 300
  max_size: 1000

# 性能配置
performance:
  batch_size: 10
  batch_delay: 0.1
  reconnect_delay: 5
  max_reconnect_attempts: 10
```

## API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/ws` | WebSocket | 主要 WebSocket 连接端点 |

## WebSocket 端口

- **默认端口**: 8124
- **协议**: ws:// 或 wss:// (如果配置 SSL)
- **路径**: /ws

## 版本信息

- **当前版本**: 1.0.0
- **支持的 HA 版本**: 2024.12.0+
- **WebSocket API 版本**: HA WebSocket API v1

## 更新日志

### v1.0.0 (2026-03-19)
- 初始版本
- 实现设备聚合功能
- 实现设备控制 API
- 实现设备状态订阅
- 实现设备分组策略
- 实现设备能力识别
- 实现设备状态聚合

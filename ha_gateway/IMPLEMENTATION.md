# Home Assistant Gateway - WebSocket API 实现

## 项目概述

本项目实现了一个基于 **纯 WebSocket API** 的 Home Assistant 网关，完全移除了 HTTP API 依赖。

## 核心特性

- ✅ **纯 WebSocket 通信** - 与 Home Assistant 的所有交互均通过 WebSocket API
- ✅ **实时状态订阅** - 订阅 `state_changed` 事件，无需轮询
- ✅ **双向消息传输** - 支持命令调用和状态推送
- ✅ **自动重连机制** - 连接断开后自动重连
- ✅ **消息合并优化** - 启用消息合并减少网络开销
- ✅ **本地状态缓存** - 实现状态缓存和历史记录
- ✅ **Home Assistant 实体过滤** - 支持过滤默认 HA 实体，只暴露自定义集成设备

## 架构设计

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                    客户端                         │
│              (WebSocket 客户端)                        │
└────────────────────┬────────────────────────────────────────────────────────┘
                     │ WebSocket (Gateway 协议)
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              Gateway WebSocket Server                       │
│              (aiohttp, 监听在 8124 端口)             │
│                                                       │
│         ├── HomeAssistantWebSocket                     │
│         │    ├─ 发送 WebSocket 命令        │
│         │    ├─ 处理响应               │
│         │    ├─ 订阅事件                 │
│         │    └─ 处理断线重连            │
└────────────────────────────┴────────────────────────────────────────────────────────┘
                     │ WebSocket (HA 协议)
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│            Home Assistant 实例                         │
│            (ws://localhost:8123/api/websocket)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## WebSocket API 命令集

### 1. 连接与认证

```json
// 1. 客户端连接
ws://localhost:8123/api/websocket

// 2. Home Assistant 请求认证
{
  "type": "auth_required",
  "ha_version": "2025.12.5"
}

// 3. 客户端发送认证
{
  "type": "auth",
  "access_token": "YOUR_ACCESS_TOKEN"
}

// 4. 认证成功响应
{
  "type": "auth_ok",
  "ha_version": "2025.12.5"
}
```

### 2. 功能启用

```json
{
  "id": 1,
  "type": "supported_features",
  "features": {
    "coalesce_messages": 1
  }
}
```

### 3. 获取状态

```json
// 请求
{
  "id": 2,
  "type": "get_states"
}

// 响应
{
  "id": 2,
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
      "last_changed": "2024-03-18T12:00:00.000Z",
      "last_updated": "2024-03-18T12:00:00.000Z",
      "context": {
        "id": "01ABCDEF123...",
        "parent_id": null,
        "user_id": "user123"
      }
    }
  ]
}
```

### 4. 调用服务

```json
// 请求
{
  "id": 3,
  "type": "call_service",
  "domain": "light",
  "service": "turn_on",
  "service_data": {
    "brightness": 255,
    "color_name": "blue"
  },
  "target": {
    "entity_id": "light.living_room"
  },
  "return_response": true
}

// 响应
{
  "id": 3,
  "type": "result",
  "success": true,
  "result": {
    "context": {
      "id": "01XYZ...",
      "parent_id": null,
      "user_id": "user123"
    },
    "response": null
  }
}
```

### 5. 订阅事件

```json
// 请求
{
  "id": 4,
  "type": "subscribe_events",
  "event_type": "state_changed"
}

// 响应
{
  "id": 4,
  "type": "result",
  "success": true,
  "result": null
}

// 事件通知
{
  "id": 4,
  "type": "event",
  "event": {
    "event_type": "state_changed",
    "data": {
      "entity_id": "light.living_room",
      "old_state": {...},
      "new_state": {...}
    },
    "origin": "LOCAL",
    "time_fired": "2024-03-18T12:00:00.000Z"
  }
}
```

### 6. 取消订阅

```json
// 请求
{
  "id": 5,
  "type": "unsubscribe_events",
  "subscription": 4  // 订阅 ID
}

// 响应
{
  "id": 5,
  "type": "result",
  "success": true,
  "result": null
}
```

### 7. 触发事件

```json
// 请求
{
  "id": 6,
  "type": "fire_event",
  "event_type": "my_custom_event",
  "event_data": {
    "source": "WebSocket Gateway",
    "timestamp": "2024-03-18T12:00:00.000Z",
    "custom_data": "value"
  }
}

// 响应
{
  "id": 6,
  "type": "result",
  "success": true,
  "result": {
    "context": {
      "id": "01ABC...",
      "parent_id": null,
      "user_id": "user123"
    }
  }
}
```

### 8. Ping/Pong

```json
// 请求
{
  "id": 7,
  "type": "ping"
}

// 响应
{
  "id": 7,
  "type": "pong"
}
```

### 9. 获取配置

```json
// 请求
{
  "id": 8,
  "type": "get_config"
}

// 响应
{
  "id": 8,
  "type": "result",
  "success": true,
  "result": {
    "latitude": 52.3731339,
    "longitude": 4.8903147,
    "unit_system": "metric",
    "time_zone": "America/Los_Angeles",
    "currency": "USD"
  }
}
```

## 文件结构

```
ha_gateway/
├── protocol/
│   ├── websocket.py          # WebSocket 协议实现
│   └── message.py           # 消息格式定义
├── server.py               # 网关服务器
├── core.py                 # 核心实现 (WebSocket-only)
├── state_manager.py        # 状态管理
├── config.py              # 配置管理
├── auth.py                # 认证处理
├── client.py              # 客户管理
├── command_handler.py      # 命令处理
└── device_manager.py       # 设备管理
```

## 核心类说明

### HomeAssistantWebSocket

Home Assistant WebSocket 客户端，实现与 Home Assistant 的双向通信。

**主要方法：**

| 方法 | 说明 |
|------|------|
| `connect()` | 建立 WebSocket 连接并完成认证 |
| `disconnect()` | 断开 WebSocket 连接 |
| `send_command()` | 发送 WebSocket 命令并等待响应 |
| `get_states()` | 获取实体状态 |
| `call_service()` | 调用 Home Assistant 服务 |
| `subscribe_events()` | 订阅 Home Assistant 事件 |
| `unsubscribe_events()` | 取消事件订阅 |
| `fire_event()` | 触发自定义事件 |
| `ping()` | 发送心跳检测 |
| `subscribe_state_changes()` | 订阅状态变化事件 |

**配置：**

```python
# 连接配置
ws_url = "ws://localhost:8123/api/websocket"
timeout = 30  # 连接和命令超时时间
reconnect_delay = 5  # 重连延迟（秒）
max_reconnect_attempts = 5  # 最大重连次数
```

### GatewayWebSocketServer

面向客户端的 WebSocket 服务器，处理客户端连接和消息路由。

**主要方法：**

| 方法 | 说明 |
|------|------|
| `start()` | 启动 WebSocket 服务器 |
| `stop()` | 停止 WebSocket 服务器 |
| `broadcast_state_change()` | 向订阅的客户端广播状态变化 |

**网关协议消息类型：**

| 类型 | 方向 | 说明 |
|------|------|----------|
| `discover` | 客户 → 网关 | 发现所有设备 |
| `get_state` | 客户 → 网关 | 获取单个实体状态 |
| `set_state` | 客户 → 网关 | 设置实体状态 |
| `call_service` | 客户 → 网关 | 调用服务 |
| `subscribe` | 客户 → 网关 | 订阅实体变化 |
| `unsubscribe` | 客户 → 网关 | 取消订阅 |
| `ping` | 客户 → 网关 | 心跳检测 |
| `state_update` | 网关 → 客户 | 状态更新推送 |
| `response` | 网关 → 客户 | 命令响应 |
| `error` | 网关 → 客户 | 错误消息 |

### 设备过滤

网关支持过滤 Home Assistant 的默认实体，减少不必要的设备暴露。

**过滤规则：**

1. **Home Assistant 默认实体排除**
   - 当 `exclude_ha_entities: true` 时，自动排除 automation、script、zone、sun 等默认实体
   - 保留用户自定义集成（如 my_integration）的设备

2. **模式匹配过滤**
   - 支持 `exclude_ha_entity_patterns` 配置项，使用正则表达式排除特定实体
   - 例如：排除天气传感器 `^sensor\.weather_`，或所有二进制传感器 `^binary_sensor\.`

3. **域名白名单**
   - 通过 `include_domains` 指定允许的域名
   - 例如：只允许 `["my_custom_integration"]`，排除所有其他

**实现位置：**

过滤逻辑在 `GatewayWebSocketServer._is_device_allowed()` 方法中实现：

```python
# 检查 HA 默认实体
ha_default_patterns = [
    r"^automation\.",
    r"^script\.",
    r"^zone\.",
    r"^sun\.",
    r"^sensor\.home_assistant\.",
    r"^sensor\.sun\.",
    r"^input_boolean\.sun\.",
    r"^input_number\.sun\.",
    r"^weather\.",
]

# 检查自定义模式
if pattern in self.config.devices.exclude_ha_entity_patterns:
    if pattern.match(entity_id):
        return False

# 检查精确排除
if any(entity_id.startswith(pattern) for pattern in self.config.devices.exclude_entities):
    return False

# 检查域名白名单
if domain not in self.config.devices.include_domains:
    return False
```

面向客户端的 WebSocket 服务器，处理客户端连接和消息路由。

**主要方法：**

| 方法 | 说明 |
|------|------|
| `start()` | 启动 WebSocket 服务器 |
| `stop()` | 停止 WebSocket 服务器 |
| `broadcast_state_change()` | 向订阅的客户端广播状态变化 |

**网关协议消息类型：**

| 类型 | 方向 | 说明 |
|------|------|------|
| `discover` | 客户 → 网关 | 发现所有设备 |
| `get_state` | 客户 → 网关 | 获取单个实体状态 |
| `set_state` | 客户 → 网关 | 设置实体状态 |
| `call_service` | 客户 → 网关 | 调用服务 |
| `subscribe` | 客户 → 网关 | 订阅实体变化 |
| `unsubscribe` | 客户 → 网关 | 取消订阅 |
| `ping` | 客户 → 网关 | 心跳检测 |
| `state_update` | 网关 → 客户 | 状态更新推送 |
| `response` | 网关 → 客户 | 命令响应 |
| `error` | 网关 → 客户 | 错误消息 |

### StateManager

状态管理器，负责本地状态缓存和历史记录。

**主要功能：**

1. **状态缓存** - 缓存从 Home Assistant 获取的状态
2. **历史记录** - 记录状态变化历史
3. **状态订阅** - 通过 WebSocket 订阅 Home Assistant 事件
4. **定期同步** - 可选的定期状态同步
5. **状态查询** - 提供状态查询接口
6. **状态统计** - 计算状态使用统计信息

**主要方法：**

| 方法 | 说明 |
|------|------|
| `update_state()` | 更新实体状态 |
| `get_state()` | 获取实体当前状态 |
| `get_all_states()` | 获取所有缓存的状态 |
| `sync_all_states()` | 从 HA 同步所有状态 |
| `add_state_callback()` | 添加状态变化回调 |
| `get_entity_statistics()` | 获取实体统计信息 |
| `cleanup_old_history()` | 清理旧的历史记录 |

## 配置文件

配置文件示例 (`config.yaml`)：

```yaml
home_assistant:
  url: "http://localhost:8123"
  access_token: "YOUR_ACCESS_TOKEN"

gateway:
  host: "0.0.0.0"
  port: 8124

cache:
  enabled: true
  ttl: 60  # 定期同步间隔（秒）
  max_history: 100  # 最大历史记录数

devices:
  enabled: true
  # Home Assistant 实体过滤
  exclude_ha_entities: false  # 排除所有 Home Assistant 默认实体（automation、script、zone、sun 等）
  exclude_ha_entity_patterns: []  # 排除特定模式的 HA 实体（正则表达式）

performance:
  max_reconnect_attempts: 5
  reconnect_delay: 5
```

## Home Assistant 实体过滤

### 概述

网关支持过滤 Home Assistant 的默认实体，只暴露用户自定义集成的设备。

### 配置选项

```yaml
devices:
  enabled: true
  # Home Assistant 实体过滤
  exclude_ha_entities: false  # 排除所有 Home Assistant 默认实体（automation、script、zone、sun 等）
  exclude_ha_entity_patterns: []  # 排除特定模式的 HA 实体（正则表达式）

performance:
  max_reconnect_attempts: 5
  reconnect_delay: 5  # 重连延迟（秒）
```

### 过滤规则

当 `exclude_ha_entities` 设置为 `true` 时，以下模式的实体将被自动排除：

| 模式 | 说明 |
|------|------|
| `^automation\.` | 自动化实体 |
| `^script\.` | 脚本实体 |
| `^zone\.` | 区域实体 |
| `^sun\.` | 太阳实体 |
| `^sensor\.home_assistant\.` | Home Assistant 传感器 |
| `^sensor\.sun\.` | 太阳传感器 |
| `^input_boolean\.sun\.` | 太阳输入 |

自定义实体（非上述模式）将始终被允许通过。

### 使用方法

1. **启用 HA 实体过滤**
   ```yaml
   # config.yaml
   devices:
     exclude_ha_entities: true
   ```

2. **排除特定实体**
   ```yaml
   # config.yaml
   devices:
     exclude_ha_entity_patterns:
       - "^sensor\.weather_"
       - "^binary_sensor\."
   ```

3. **自定义白名单**
   ```yaml
   # config.yaml
   devices:
     include_domains:
       - "my_custom_integration"
       - "another_custom_integration"
     ```

### 默认 Home Assistant 实体列表

以下实体会被默认 Home Assistant 安装创建，建议在自定义集成或过滤：

| 域/域 | 实体类型 | 示例 |
|------|---------|------|
| `automation` | 自动化 | `automation.turn_on_lights` |
| `script` | 脚本 | `script.reload_sitemap` |
| `zone` | 区域 | `zone.home` |
| `sun` | 太阳 | `sun.sun` |
| `weather` | 天气 | `weather.home` |
| `sensor.home_assistant` | Home Assistant 内部传感器 |
| `input_boolean` | 输入 | `input_boolean.start` |
| `input_number` | 输入 | `input_number.duration` |

### 调试配置

测试过滤是否生效：

```bash
# 启动服务器
python3 server.py --log-level DEBUG

# 查看日志中的过滤信息
# 应该看到类似 "Excluding HA default entity: automation.xxx" 的日志
```

## 启动方式

### 方式一：使用 server.py

```bash
# 启动网关（默认 INFO 日志）
python3 server.py

# 启动网关（DEBUG 日志）
python3 server.py --log-level DEBUG

# 指定配置文件
python3 server.py --config /path/to/config.yaml
```

### 方式二：使用 core.py

```bash
# WebSocket-only 模式
python3 -m ha_gateway.core --config config.yaml

# 指定日志级别
python3 -m ha_gateway.core --config config.yaml --log-level DEBUG
```

## 测试

### 运行测试套件

```bash
# 运行所有 WebSocket API 测试
python3 test_websocket_only.py

# 运行特定测试
python3 test_websocket_only.py --test connection
python3 test_websocket_only.py --test states
python3 test_websocket_only.py --test services
python3 test_websocket_only.py --test events
```

### 简单 WebSocket 客户端测试

```bash
# 基础连接和状态测试
python3 test_ws_simple.py
```

### 快速验证

```bash
# 验证基本配置和导入
python3 quick_test.py
```

## 错误代码参考

| 错误代码 | 说明 | 处理方式 |
|----------|------|----------|
| `invalid_format` | 消息格式错误 | 返回详细错误信息 |
| `unknown_command` | 未知命令类型 | 记录并拒绝 |
| `unauthorized` | 认证失败 | 断开连接 |
| `service_validation_error` | 服务调用验证失败 | 返回验证错误 |
| `home_assistant_error` | Home Assistant 错误 | 返回 HA 错误信息 |

## 错误响应格式

```json
{
  "id": <请求 ID>,
  "type": "error",
  "payload": {
    "error": "错误描述",
    "code": "错误代码"
  }
}
```

示例：

```json
{
  "id": 10,
  "type": "error",
  "payload": {
    "error": "Service validation failed: Option 'custom' is not a supported mode.",
    "code": "service_validation_error",
    "translation_key": "unsupported_mode",
    "translation_domain": "kitchen_sink",
    "translation_placeholders": {
      "mode": "custom"
    }
  }
}
```

## 性能优化

### 消息合并

启用后，多个消息可以合并为单个网络包：

```json
[
  {"id": 1, "type": "result", ...},
  {"id": 2, "type": "result", ...},
  {"id": 3, "type": "event", ...}
]
```

### 本地缓存

状态缓存减少了不必要的 WebSocket 命令：

1. 初始状态获取一次
2. 后续更新通过事件推送
3. 本地查询无需网络请求

### 批量状态传输

初始状态批量发送给新连接的客户端：

```python
# 发送所有 53 个实体状态
for state in states:
    msg = create_state_update(state["entity_id"], state)
    await ws.send_str(msg.json)
```

## 开发指南

### 添加新的 WebSocket 命令

1. 在 `HACommandType` 枚举中添加命令类型
2. 在 `send_command` 方法中添加参数处理
3. 添加相应的 `async def` 方法处理响应

### 修改现有命令

WebSocket 命令是无版本的，可以直接修改：

```python
# 示例：添加新命令
async def new_command(self, param1: str, param2: int) -> Dict[str, Any]:
    """处理新命令。"""
    # 发送命令到 Home Assistant
    response = await self.send_command("new_command_type", param1=param1, param2=param2)
    return response.get("result", {})
```

### 添加新的事件订阅

```python
# 在状态管理器中添加回调
async def _handle_custom_event(self, event_data: Dict[str, Any]) -> None:
    """处理自定义事件。"""
    event_type = event_data.get("event_type")
    # 处理事件
    pass
```

## 故障排除

### 常见问题

**问题 1：连接失败**

```
症状：Failed to connect to Home Assistant
原因：
- URL 错误
- Access Token 无效
- 网络问题
- Home Assistant 未运行
```

**解决方法：**

1. 验证 Home Assistant URL
   ```bash
   curl http://localhost:8123/api/
   ```

2. 检查 Access Token
   - 确保 Token 有效且未过期
   - Token 有正确的权限

3. 检查网络连接
   ```bash
   telnet localhost 8123
   ```

**问题 2：状态未更新**

```
症状：状态变化未实时更新
原因：
- 事件订阅失败
- 事件处理函数出错
- 网络连接不稳定
```

**解决方法：**

1. 启用 DEBUG 日志
   ```bash
   python3 server.py --log-level DEBUG
   ```

2. 检查事件订阅日志
   - 查找 `Subscribed to state_changed`
   - 查找 `Received event: state_changed`

3. 检查消息处理
   - 确保 `_handle_state_changed` 正常工作

**问题 3：内存占用过高**

```
症状：进程内存使用持续增长
原因：
- 状态历史无限增长
- 连接未正确关闭
- 消息未正确清理
```

**解决方法：**

1. 配置历史记录大小限制
   ```yaml
   cache:
     max_history: 100
   ```

2. 实现定期清理
   ```python
   await self.state_manager.cleanup_old_history(max_age_hours=24 * 7)
   ```

### 调试技巧

**启用详细日志**

```python
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

**监控 WebSocket 消息**

```python
# 在 _handle_message 方法中添加日志
logger.debug(f"Received message: {data}")
```

**测试特定功能**

```python
# 只测试连接和认证
python3 -c "
import asyncio
import websockets
async def test():
    async with websockets.connect('ws://localhost:8123/api/websocket') as ws:
        print('Connected')
        # 认证测试
        msg = {'type': 'auth', 'access_token': 'TOKEN'}
        await ws.send(json.dumps(msg))
        response = await ws.recv()
        print(f'Auth response: {json.loads(response)}')
asyncio.run(test())
"
```

## 安全建议

1. **Access Token 安全**
   - 不要将 Token 提交到版本控制系统
   - 使用环境变量存储敏感信息
   - 定期轮换 Token

2. **网络配置**
   - 生产环境使用 SSL/TLS (`ssl=True`)
   - 配置防火墙规则限制访问
   - 使用 VPN 或专网连接

3. **输入验证**
   - 验证所有客户端输入
   - 限制消息频率
   - 实现速率限制

4. **日志安全**
   - 记录前脱敏敏感数据
   - 不要记录完整的 Token
   - 限制日志文件大小

## 迁移指南

### 从 HTTP API 迁移到 WebSocket API

**修改配置调用：**

```python
# 旧代码（HTTP）
async def get_states_http():
    async with session.get(f"{url}/api/states") as response:
        return await response.json()

# 新代码（WebSocket）
async def get_states_websocket():
    return await self.ha_ws.get_states()
```

**更新服务调用：**

```python
# 旧代码（HTTP）
async def call_service_http(domain, service, data):
    await session.post(f"{url}/api/services/{domain}/{service}", json=data)

# 新代码（WebSocket）
async def call_service_websocket(domain, service, data, target):
    return await self.ha_ws.call_service(domain, service, service_data=data, target=target)
```

## 参考资源

- [Home Assistant WebSocket API 文档](https://developers.home-assistant.io/docs/api/websocket/)
- [aiohttp 文档](https://docs.aiohttp.org/)
- [Python asyncio 文档](https://docs.python.org/3/library/asyncio.html)
- [WebSocket 协议 RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455)

## 版本信息

- Home Assistant 版本：2025.12.5
- Python 版本：3.12+
- aiohttp 版本：3.13.3
- WebSocket 协议版本：13

## 许可证

本项目遵循 MIT 许可证。

## 贡献者

- David
- 任何对本项目的贡献都是受欢迎的

## 许可证

MIT License

Copyright (c) 2024 David

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

# KNX 与 Home Assistant Gateway 集成架构

## 1. 系统架构概览

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  KNX Gateway   │    │  HA Gateway     │    │  Home Assistant │
│                │◄──►│                │◄──►│                │
│                │    │                │    │                │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          │ (提供KNX地址)          │ (状态同步)            │ (设备控制)
          │                      │                      │
    ┌────▼────────┐    ┌──────────▼──────────┐    ┌────────▼─────────┐
    │  KNX Devices │    │   Device Mapping    │    │   Physical Devices│
    │  (灯光,开关) │    │   (实体→KNX映射)  │    │   (灯,空调等)    │
    └─────────────┘    └─────────────────────┘    └─────────────────┘
```

## 2. 功能需求

### 2.1 KNX Gateway 职责
1. **KNX地址管理**
   - 维护KNX地址池
   - 为新设备分配KNX地址
   - 管理KNX组地址

2. **状态监听**
   - 接收HA Gateway的状态变化通知
   - 将HA状态转换为KNX总线命令
   - 监听KNX总线状态变化

3. **控制转发**
   - 接收KNX总线控制命令
   - 转发到HA Gateway
   - 处理双向通信

### 2.2 HA Gateway 职责
1. **设备注册**
   - 发现新设备时请求KNX地址
   - 建立设备与KNX的映射关系
   - 存储映射配置

2. **状态同步**
   - 监听设备状态变化
   - 转换为KNX格式并转发
   - 接收KNX状态更新

3. **控制接口**
   - 接收KNX控制请求
   - 转换为HA服务调用
   - 返回执行结果

## 3. 核心组件设计

### 3.1 KNX Gateway 组件

```python
class KNXGateway:
    """KNX 网关连接器"""

    # 配置
    config: KNXConfig
    connection: KNXConnection
    address_pool: KNXAddressPool

    # 地址映射存储
    device_mappings: Dict[str, KNXMapping]

    # WebSocket连接
    ha_gateway_client: Optional[WebSocketClient]

    async def start(self):
        """启动KNX网关"""

    async def stop(self):
        """停止KNX网关"""

    # 功能1: 提供KNX地址分配服务
    async def register_device(self, device_info: DeviceInfo) -> KNXAddress:
        """
        注册设备，分配KNX地址

        Args:
            device_info: 设备信息

        Returns:
            分配的KNX地址和组地址
        """

    # 功能2: 监听HA网关状态变化
    def subscribe_to_ha_status(self, callback: Callable):
        """
        订阅HA网关状态变化

        Args:
            callback: 状态变化回调函数
        """

    # 功能3: 接收KNX控制指令
    async def on_knx_control(self, knx_address: str, value: Any):
        """
        处理KNX控制指令

        Args:
            knx_address: KNX地址
            value: 控制值
        """

    # 功能4: 发送状态到KNX总线
    async def send_to_knx(self, knx_address: str, value: Any):
        """
        发送状态到KNX总线

        Args:
            knx_address: KNX组地址
            value: 状态值
        """
```

### 3.2 HA Gateway 组件扩展

```python
class DeviceIntegration:
    """设备集成管理器"""

    # KNX网关连接
    knx_gateway_client: Optional[WebSocketClient]
    device_mappings: Dict[str, KNXMapping]

    async def initialize(self, knx_gateway_url: str):
        """初始化KNX集成"""

    # 功能1: 请求KNX地址
    async def request_knx_address(self, device_id: str, device_info: Dict) -> Optional[KNXAddress]:
        """
        向KNX网关请求KNX地址

        Args:
            device_id: 设备ID
            device_info: 设备信息

        Returns:
            分配的KNX地址
        """

    # 功能2: 建立KNX映射
    def create_knx_mapping(self, device_id: str, knx_address: KNXAddress):
        """
        创建设备与KNX的映射关系

        Args:
            device_id: 设备ID
            knx_address: KNX地址
        """

    # 功能3: 同步状态到KNX
    async def sync_to_knx(self, device_id: str, state: DeviceState):
        """
        将设备状态同步到KNX

        Args:
            device_id: 设备ID
            state: 设备状态
        """

    # 功能4: 处理KNX控制请求
    async def handle_knx_control(self, knx_address: str, value: Any):
        """
        处理来自KNX的控制请求

        Args:
            knx_address: KNX地址
            value: 控制值
        """
```

### 3.3 Device Mapping (映射管理器)

```python
class DeviceMapping:
    """设备映射管理器"""

    # 存储映射关系
    mapping_db: Dict[str, DeviceKNXMapping]

    # 配置的映射规则
    mapping_rules: Dict[str, MappingRule]

    async def create_mapping(self, device_id: str, knx_address: str, config: Dict):
        """创建新的设备映射"""

    def get_mapping_by_device(self, device_id: str) -> Optional[DeviceKNXMapping]:
        """根据设备ID获取映射"""

    def get_mapping_by_knx(self, knx_address: str) -> Optional[DeviceKNXMapping]:
        """根据KNX地址获取映射"""

    async def sync_to_knx(self, device_id: str, state: Any):
        """将状态同步到KNX"""

    async def sync_to_ha(self, knx_address: str, knx_value: Any):
        """将KNX状态同步到HA"""
```

## 4. 通信协议设计

### 4.1 WebSocket 消息格式

#### HA Gateway → KNX Gateway

**1. 注册设备请求**
```json
{
    "type": "register_device",
    "id": "msg_001",
    "payload": {
        "device_id": "abc123",
        "device_name": "客厅灯",
        "device_type": "light",
        "capabilities": ["power_control", "brightness_control"],
        "entities": [
            {
                "entity_id": "light.living_room",
                "attributes": {
                    "friendly_name": "客厅灯"
                }
            }
        ]
    }
}
```

**2. 状态同步请求**
```json
{
    "type": "sync_state_to_knx",
    "id": "msg_002",
    "payload": {
        "device_id": "abc123",
        "state": {
            "power_state": "on",
            "brightness": 200
        }
    }
}
```

#### KNX Gateway → HA Gateway

**1. 地址分配响应**
```json
{
    "type": "address_assigned",
    "id": "msg_001_response",
    "payload": {
        "device_id": "abc123",
        "success": true,
        "address_info": {
            "device_address": "1/1.1",
            "group_addresses": {
                "control": "1/1/1",
                "status": "1/1/2",
                "dimming": "1/1/3"
            }
        },
        "knx_dpt": {
            "control": "DPT1.001",
            "brightness": "DPT5.001"
        }
    }
}
```

**2. 状态更新通知**
```json
{
    "type": "knx_state_update",
    "id": "msg_knx_001",
    "payload": {
        "device_id": "abc123",
        "knx_address": "1/1/1",
        "knx_group": "Light/Living_Room/State",
        "value": 1,
        "dpt": "DPT1.001",
        "timestamp": "2026-03-19T10:00:00Z"
    }
}
```

### 4.2 错误响应格式
```json
{
    "type": "error",
    "id": "msg_001_response",
    "payload": {
        "error_code": "ADDRESS_POOL_EXHAUSTED",
        "error_message": "No available KNX addresses in pool",
        "device_id": "abc123",
        "timestamp": "2026-03-19T10:00:00Z"
    }
}
```

## 5. 地址分配策略

### 5.1 地址池管理
```yaml
knx_addresses:
  # 物理地址池 (主地址)
  physical_addresses:
    prefix: "1"
    start: 1
    end: 255

  # 组地址池 (按类型划分)
  group_addresses:
    lights:
      pattern: "1/1/{id}"
      range: [1, 100]
      dpt: "DPT1.001"

    switches:
      pattern: "2/1/{id}"
      range: [1, 100]
      dpt: "DPT1.001"

    blinds:
      pattern: "3/1/{id}"
      range: [1, 50]
      dpt: "DPT1.008"

    climate:
      pattern: "4/1/{id}"
      range: [1, 30]
      dpt: "DPT9.001"

  # 地址分配记录
  allocations: []
  reserved: []
```

### 5.2 地址分配规则

1. **按设备类型分配**
   - Light → 组地址: 1/1/1-100
   - Switch → 组地址: 2/1/1-100
   - Cover → 组地址: 3/1/1-50
   - Climate → 组地址: 4/1/1-30

2. **按区域分配**
   - Living Room → 1/1/1-20
   - Bedroom → 1/1/21-40
   - Kitchen → 1/1/41-60
   - Bathroom → 1/1/61-80

3. **动态分配算法**
   ```python
   def allocate_address(device_type, area):
       """动态分配KNX地址"""
       pool = get_address_pool(device_type, area)
       if pool.available_addresses:
           address = pool.allocate()
           return {
               "physical_address": f"{pool.prefix}/{address}",
               "group_addresses": generate_group_addresses(device_type, address)
           }
       else:
           raise AddressPoolExhaustedError()
   ```

## 6. 状态映射规则

### 6.1 HA状态 ↔ KNX值
```python
state_mapping = {
    "light": {
        "HA_state": "on/off",
        "KNX_value": "1/0",
        "KNX_dpt": "DPT1.001",
        "conversion": "direct"
    },
    "brightness": {
        "HA_value": "0-255",
        "KNX_value": "0-255",
        "KNX_dpt": "DPT5.001",
        "conversion": "linear"
    },
    "color_temp": {
        "HA_value": "mireds (153-500)",
        "KNX_value": "mireds (153-500)",
        "KNX_dpt": "DPT5.001",
        "conversion": "linear"
    },
    "temperature": {
        "HA_value": "16-30°C",
        "KNX_value": "0-6700",
        "KNX_dpt": "DPT9.001",
        "conversion": "multiply:10"
    },
    "humidity": {
        "HA_value": "0-100%",
        "KNX_value": "0-1000",
        "KNX_dpt": "DPT5.001",
        "conversion": "divide:10"
    },
    "cover_position": {
        "HA_value": "0-100%",
        "KNX_value": "0-100%",
        "KNX_dpt": "DPT5.001",
        "conversion": "direct"
    }
}
```

### 6.2 映射配置文件
```yaml
device_mappings:
  living_room_light:
    device_id: "light.living_room"
    knx_address: "1/1/1"
    device_type: "light"
    mappings:
      state:
        knx_dpt: "DPT1.001"
        knx_group: "1/1/1"
        knx_values:
          on: 1
          off: 0
      brightness:
        knx_dpt: "DPT5.001"
        knx_group: "1/1/2"
        range: [0, 255]

  living_room_switch:
    device_id: "switch.living_room"
    knx_address: "2/1/1"
    device_type: "switch"
    mappings:
      state:
        knx_dpt: "DPT1.001"
        knx_group: "2/1/1"
        knx_values:
          on: 1
          off: 0
      power:
        knx_dpt: "DPT5.001"
        knx_group: "2/1/2"
        unit: "W"
```

## 7. 业务流程

### 7.1 设备注册流程
```
┌─────────────────┐    ┌─────────────────┐
│  HA Gateway   │    │  KNX Gateway   │
└───────┬──────┘    └───────┬──────┘
        │                    │
    1. 发现新设备            │
        │                    │
    2. 发送register_device   │────────────►
        │                    │
    3.                     │        4. 分配KNX地址
        │              ◄────────────┘
        │                    │
    5. 接收KNX地址       │
    6. 创建设备-KNX映射    │
        │                    │
    7. 同步初始状态       │────────────►
        │                    │        8. 广播到KNX总线
        │              ◄────────────┘
        │                    │
    9. 确认地址分配        │
        │                    │
    10. 注册成功           │
```

### 7.2 HA → KNX 状态同步流程
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  HA Gateway   │    │  KNX Gateway   │    │   KNX Bus      │
└───────┬──────┘    └───────┬──────┘    └─────────┬───────┘
        │                    │                      │
    1. 设备状态变化        │                      │
        │                    │                      │
    2. 查找KNX映射        │                      │
        │                    │                      │
    3. 转换为KNX格式       │                      │
        │                    │                      │
    4. 发送到KNX网关       │────────────►          │
        │                    │        5. 转发到总线 ───────►
        │                    │                      │
        │              ◄────────────┘         6. 设备执行
        │                    │              ◄───────────┘
    7. 确认执行            │
        │                    │
```

### 7.3 KNX → HA 控制流程
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  KNX Devices  │    │  KNX Gateway   │    │  HA Gateway   │
└───────┬──────┘    └───────┬──────┘    └───────┬──────┘
        │                    │                      │
    1. 物理操作           │                      │
        │                    │                      │
    2. 发送到组地址        │                      │
        │────────────────────►                      │
        │                    │        3. 接收控制消息 ──────────►
        │                    │                      │
        │              ◄────────────┘         4. 查找设备映射
        │                    │                      │
        │                    │              ◄───────────┘
    5. 调用HA服务        │
        │                    │
        │                    │
    6. 确认执行            │
        │◄───────────────────┘
        │                    │
```

## 8. 错误处理机制

### 8.1 通信错误处理
```python
class KNXErrorHandler:
    """KNX通信错误处理器"""

    error_handlers = {
        "CONNECTION_LOST": handle_connection_lost,
        "TIMEOUT": handle_timeout,
        "INVALID_ADDRESS": handle_invalid_address,
        "PERMISSION_DENIED": handle_permission_denied,
        "ADDRESS_POOL_EXHAUSTED": handle_pool_exhausted,
        "MAPPING_NOT_FOUND": handle_mapping_not_found,
        "CONVERSION_FAILED": handle_conversion_failed
    }

    async def handle_error(self, error_type: str, device_id: str, message: str):
        """处理错误"""
        handler = self.error_handlers.get(error_type, self.handle_unknown_error)
        await handler(device_id, message)
```

### 8.2 重连机制
```python
class ReconnectionManager:
    """重连管理器"""

    config = {
        "max_retries": 5,
        "retry_delay": 5,  # 秒
        "backoff_multiplier": 2,
        "max_backoff": 60
    }

    async def reconnect(self):
        """执行重连"""
        for attempt in range(self.config["max_retries"]):
            try:
                await self.connect()
                logger.info("Reconnection successful")
                return True
            except Exception as e:
                delay = min(
                    self.config["retry_delay"] * (self.config["backoff_multiplier"] ** attempt),
                    self.config["max_backoff"]
                )
                logger.warning(f"Reconnection attempt {attempt + 1} failed, retrying in {delay}s")
                await asyncio.sleep(delay)

        return False

    async def restore_state(self):
        """恢复设备状态"""
        for device_id, mapping in self.device_mappings.items():
            current_state = await self.get_ha_state(device_id)
            await self.sync_to_knx(device_id, current_state)
```

## 9. 配置管理

### 9.1 KNX Gateway 配置
```yaml
knx_gateway:
  # 服务器配置
  host: "0.0.0.0"
  port: 8125
  max_connections: 100

  # KNX连接配置
  knx_connection:
    host: "192.168.1.100"
    port: 3671
    local_ip: "192.168.1.10"
    connection_timeout: 5
    heartbeat_interval: 30

  # 地址池配置
  address_pool:
    physical:
      prefix: "1"
      start: 1
      end: 255
    groups:
      lights:
        pattern: "1/1/{id}"
        range: [1, 100]
      switches:
        pattern: "2/1/{id}"
        range: [1, 100]
      blinds:
        pattern: "3/1/{id}"
        range: [1, 50]
      climate:
        pattern: "4/1/{id}"
        range: [1, 30]

  # 日志配置
  logging:
    level: "DEBUG"
    file: "/var/log/knx_gateway.log"
    max_size: 10485760  # 10MB
    backup_count: 5

  # 性能配置
  performance:
    batch_size: 50
    batch_delay: 0.1
    max_queue_size: 1000
```

### 9.2 集成配置
```yaml
integration:
  # KNX网关连接
  knx_gateway:
    url: "ws://knx-gateway:8125/ws"
    reconnect_interval: 5
    max_retries: 10

  # 设备类型映射
  device_type_mapping:
    light:
      knx_group: "lights"
      knx_dpt: "DPT1.001"
      address_pool: "lights"
      attributes:
        state: true
        brightness: true
        color_temp: true

    switch:
      knx_group: "switches"
      knx_dpt: "DPT1.001"
      address_pool: "switches"
      attributes:
        state: true
        power: true

    cover:
      knx_group: "blinds"
      knx_dpt: "DPT1.008"
      address_pool: "blinds"
      attributes:
        state: true
        position: true

    climate:
      knx_group: "climate"
      knx_dpt: "DPT9.001"
      address_pool: "climate"
      attributes:
        state: true
        temperature: true
        mode: true

  # 区域映射
  area_mapping:
    living_room:
      knx_prefix: "1/1"
      ha_area: "living_room"
    bedroom:
      knx_prefix: "1/2"
      ha_area: "bedroom"
    kitchen:
      knx_prefix: "1/3"
      ha_area: "kitchen"

  # 状态同步配置
  sync:
    enabled: true
    sync_interval: 0  # 实时同步
    batch_size: 10
    max_delay: 1.0
```

## 10. 监控和日志

### 10.1 监控指标
```python
class MonitoringMetrics:
    """监控指标"""

    metrics = {
        # 连接指标
        "knx_connection_status": "connected/disconnected",
        "ha_connection_status": "connected/disconnected",

        # 设备指标
        "registered_devices": total_count,
        "active_mappings": active_count,
        "failed_registrations": failed_count,

        # 通信指标
        "messages_sent": total_sent,
        "messages_received": total_received,
        "messages_failed": failed_count,

        # 性能指标
        "average_response_time": avg_ms,
        "throughput_per_second": msg_per_sec,
        "queue_size": current_queue_length,

        # 错误指标
        "error_rate_per_minute": errors_per_min,
        "last_error": error_info,

        # KNX总线指标
        "knx_bus_load": bus_load_percent,
        "knx_telegrams_per_second": telegram_rate
    }
```

### 10.2 日志格式
```json
{
    "timestamp": "2026-03-19T10:00:00Z",
    "level": "INFO",
    "component": "knx_integration",
    "event": "device_registered",
    "device_id": "abc123",
    "knx_address": "1/1/1",
    "duration_ms": 45,
    "message": "Device registered successfully",
    "correlation_id": "req_001"
}
```

## 11. 扩展性设计

### 11.1 插件式架构
```python
class KNXIntegrationPlugin:
    """KNX集成插件基类"""

    name: str
    version: str

    async def on_device_registered(self, device: DeviceInfo):
        """设备注册时触发"""
        pass

    async def on_state_changed(self, device_id: str, old_state: Any, new_state: Any):
        """状态变化时触发"""
        pass

    async def on_knx_received(self, knx_address: str, value: Any):
        """接收到KNX消息时触发"""
        pass

    async def on_error(self, error_type: str, context: Dict):
        """发生错误时触发"""
        pass
```

### 11.2 动态配置更新
```python
class ConfigManager:
    """配置管理器"""

    async def reload_config(self):
        """重新加载配置文件"""
        pass

    async def add_mapping_rule(self, rule: MappingRule):
        """添加新的映射规则"""
        pass

    async def update_device_type_mapping(self, type_config: Dict):
        """更新设备类型映射"""
        pass

    async def export_config(self) -> Dict:
        """导出当前配置"""
        pass
```

## 12. 安全考虑

### 12.1 认证机制
```yaml
authentication:
  # API密钥认证
  api_key:
    enabled: true
    key: "secure_key_here"
    header_name: "X-API-Key"

  # TLS证书
  tls:
    enabled: false
    cert_path: "/etc/ssl/cert.pem"
    key_path: "/etc/ssl/key.pem"

  # IP白名单
  ip_whitelist:
    enabled: true
    allowed_ips:
      - "192.168.1.0/24"
      - "10.0.0.0/8"
```

### 12.2 访问控制
```yaml
access_control:
  # 基于角色的访问控制
  roles:
    admin:
      can_control: true
      can_configure: true
      can_monitor: true

    user:
      can_control: true
      can_configure: false
      can_monitor: true

    guest:
      can_control: false
      can_configure: false
      can_monitor: true

  # 基于设备的访问控制
  device_permissions:
    critical_devices:
      - "climate.bedroom"
      - "lock.front_door"
      allowed_roles: ["admin", "user"]
```

## 13. 性能考虑

### 13.1 性能优化策略
- 使用消息队列处理状态更新
- 批量发送地址分配请求
- 缓存映射关系减少查询
- 异步处理提高响应速度
- 压缩大批量消息
- 使用连接池管理WebSocket连接

### 13.2 性能基准测试
- 模拟 100+ 设备并发注册
- 测试每秒状态同步吞吐量
- 验证内存使用情况 < 512MB
- 测试重连恢复时间 < 30秒
- 测试端到端延迟 < 100ms

## 14. 实现阶段

### Phase 1: 基础架构 (Week 1-2)
1. 建立 WebSocket 双向连接
2. 实现设备注册协议
3. 实现地址分配功能
4. 实现基础映射存储

### Phase 2: 状态同步 (Week 3-4)
1. 实现双向状态同步
2. 添加状态转换逻辑
3. 实现心跳机制
4. 添加错误处理

### Phase 3: 高级功能 (Week 5-6)
1. 实现批量操作
2. 添加配置热更新
3. 实现监控面板
4. 性能优化

### Phase 4: 完善功能 (Week 7-8)
1. 添加调试模式
2. 实现配置导出
3. 添加备份机制
4. 完善文档

## 15. 测试策略

### 15.1 单元测试
```python
class TestDeviceMapping:
    def test_create_mapping(self):
        pass

    def test_find_by_device(self):
        pass

    def test_find_by_knx(self):
        pass

class TestKNXProtocol:
    def test_address_allocation(self):
        pass

    def test_state_conversion(self):
        pass
```

### 15.2 集成测试
1. 端到端设备注册流程
2. 双向状态同步测试
3. 控制流程测试
4. 错误恢复测试

## 16. 附录

### 16.1 KNX DPT 参考
| DPT | 名称 | 用途 | 范围 |
|-----|------|------|------|
| DPT1.001 | Switch | 开关 | 0/1 |
| DPT1.008 | Dimmer | 调光 | 0-100% |
| DPT5.001 | Dimmer | 调光 | 0-255 |
| DPT9.001 | Temperature | 温度 | -273.2-6703.6°C |
| DPT5.001 | Scaling | 缩放 | 0-65535 |
| DPT3.007 | Time | 时间 | 00:00:00-23:59:59 |

### 16.2 错误代码参考
| 错误代码 | 描述 | 处理方式 |
|---------|------|---------|
| CONNECTION_LOST | 连接丢失 | 自动重连 |
| TIMEOUT | 请求超时 | 重试请求 |
| INVALID_ADDRESS | 无效地址 | 验证并请求新地址 |
| PERMISSION_DENIED | 权限拒绝 | 检查权限配置 |
| ADDRESS_POOL_EXHAUSTED | 地址池耗尽 | 扩展地址池 |
| MAPPING_NOT_FOUND | 映射未找到 | 重新注册设备 |
| CONVERSION_FAILED | 转换失败 | 检查转换规则 |

---

**文档版本**: 1.0.0
**最后更新**: 2026-03-19
**作者**: HA Gateway Team

# SmartHome NLU 与 ha_gateway 接口契约（v1）

## 1. 目标
定义运行时对 ha_gateway 的最小可用调用契约，覆盖：
- 实体搜索：`ha_search_entities`
- 服务执行：`ha_call_service`
- 状态查询：`ha_get_entity`

## 2. 通用返回封装（Envelope）
所有工具调用统一返回如下结构：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `success` | `bool` | 是 | 调用是否成功 |
| `status_code` | `int` | 是 | 上游或映射后的状态码 |
| `data` | `object/null` | 否 | 成功时业务数据 |
| `error_code` | `string/null` | 否 | 失败时标准错误码 |
| `error` | `string/null` | 否 | 失败时可读错误信息 |
| `trace_id` | `string` | 是 | 链路追踪 ID |

## 3. 工具接口定义

## 3.1 `ha_search_entities`

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | `string` | 是 | - | 自然语言关键词 |
| `domain` | `string` | 否 | 空 | 领域过滤，如 `light` |
| `limit` | `int` | 否 | `3` | 返回上限，建议 `1~5` |

成功返回 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `entities` | `array` | 匹配实体列表 |
| `entities[].entity_id` | `string` | 实体 ID |
| `entities[].name` | `string` | 显示名 |
| `entities[].area` | `string` | 区域 |
| `entities[].state` | `string` | 当前状态 |
| `entities[].score` | `float` | 匹配分数 |

## 3.2 `ha_call_service`

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `domain` | `string` | 是 | 服务域，如 `light` |
| `service` | `string` | 是 | 服务名，如 `turn_on` |
| `entity_id` | `string` | 是 | 目标实体 |
| `data` | `object` | 否 | 服务参数，如 `brightness_pct` |

成功返回 `data`（最小要求）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `entity_id` | `string` | 已执行实体 |
| `state` | `string/nullable` | 可能返回执行后状态 |
| `message` | `string/nullable` | 可读提示 |

## 3.3 `ha_get_entity`

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `entity_id` | `string` | 是 | 目标实体 |

成功返回 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `entity` | `object` | 实体对象 |
| `entity.entity_id` | `string` | 实体 ID |
| `entity.name` | `string` | 显示名 |
| `entity.state` | `string` | 当前状态 |
| `entity.attributes` | `object/nullable` | 其他属性 |

## 4. 标准错误码

| 错误码 | HTTP | 语义 | 是否重试 |
|---|---|---|---|
| `BAD_REQUEST` | 400 | 参数错误或缺失 | 否 |
| `UNAUTHORIZED` | 401 | 未认证 | 否 |
| `FORBIDDEN` | 403 | 无权限 | 否 |
| `ENTITY_NOT_FOUND` | 404 | 实体不存在 | 否 |
| `NOT_FOUND` | 404 | 资源不存在 | 否 |
| `CONFLICT` | 409 | 资源冲突 | 否 |
| `UPSTREAM_TIMEOUT` | 504 | 上游超时 | 是 |
| `UPSTREAM_ERROR` | 502 | 上游失败 | 是 |
| `INTERNAL_ERROR` | 500 | 本地内部异常 | 否 |

## 5. 调用约束

| 项 | 规则 |
|---|---|
| 工具白名单 | 仅允许 `ha_search_entities`、`ha_call_service`、`ha_get_entity` |
| 超时 | 单次调用 `3~8s`，默认 `5s` |
| 重试 | 仅对 `UPSTREAM_TIMEOUT/UPSTREAM_ERROR`，最多 `2` 次 |
| 幂等 | 对控制类指令启用幂等键，窗口 `20~30s` |
| 审计 | 每次调用必须记录 `trace_id/user/tool/entity/result/latency` |

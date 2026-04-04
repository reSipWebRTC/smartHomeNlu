# SmartHome NLU 执行状态机（v1）

## 1. 状态列表

| 状态 | 说明 |
|---|---|
| `IDLE` | 等待请求 |
| `RESOLVE_ENTITY` | 解析并搜索实体 |
| `CHECK_POLICY` | 权限与风险校验 |
| `WAIT_CONFIRM` | 等待用户确认高风险操作 |
| `EXECUTE` | 调用 `ha_call_service` 执行 |
| `RETRY_OR_FAIL` | 可重试失败分支 |
| `VERIFY` | 调用 `ha_get_entity` 做状态核验 |
| `CLARIFY` | 需要用户补充信息 |
| `FAILED` | 执行失败 |
| `CANCELLED` | 用户取消或确认过期 |
| `DONE` | 执行并验证成功 |
| `DONE_UNVERIFIED` | 执行成功但状态未核验 |

## 2. 状态流转

| 当前状态 | 触发条件 | 下一状态 |
|---|---|---|
| `IDLE` | 收到用户指令 | `RESOLVE_ENTITY` |
| `RESOLVE_ENTITY` | 搜索命中可用实体 | `CHECK_POLICY` |
| `RESOLVE_ENTITY` | 无结果或分数低于阈值 | `CLARIFY` |
| `CHECK_POLICY` | 权限不足 | `FAILED` |
| `CHECK_POLICY` | 高风险且未确认 | `WAIT_CONFIRM` |
| `CHECK_POLICY` | 可直接执行 | `EXECUTE` |
| `WAIT_CONFIRM` | 用户确认通过 | `EXECUTE` |
| `WAIT_CONFIRM` | 用户拒绝或超时 | `CANCELLED` |
| `EXECUTE` | 调用成功 | `VERIFY` |
| `EXECUTE` | 超时或上游错误 | `RETRY_OR_FAIL` |
| `EXECUTE` | 非重试类错误 | `FAILED` |
| `RETRY_OR_FAIL` | 未超过重试上限 | `EXECUTE` |
| `RETRY_OR_FAIL` | 超过重试上限 | `FAILED` |
| `VERIFY` | 状态与目标一致 | `DONE` |
| `VERIFY` | 状态读取失败或不一致 | `DONE_UNVERIFIED` |

## 3. 策略细则

## 3.1 实体解析策略
- 查询模板：`location + device_type`。
- 优先 `domain` 过滤（如灯只搜 `light`）。
- 首项分数低于阈值（建议 `0.35~0.5`）时进入 `CLARIFY`。

## 3.2 重试策略
- 仅 `UPSTREAM_TIMEOUT`、`UPSTREAM_ERROR` 进入重试。
- 最大重试次数：`2`。
- 建议退避：`100ms -> 300ms`。

## 3.3 幂等策略
- 幂等键：`user_id + intent + entity_id + service + value`。
- 幂等窗口：`20~30` 秒。
- 命中幂等后返回最近成功结果，不重复下发。

## 3.4 核验策略
- `VERIFY` 仅做“确认”，不再次控制。
- 核验失败返回 `DONE_UNVERIFIED`，并写审计与告警。

## 4. 终态定义

| 终态 | 对用户返回 |
|---|---|
| `DONE` | 操作成功且已确认状态 |
| `DONE_UNVERIFIED` | 操作已发送，但状态确认失败 |
| `FAILED` | 操作失败，给出错误原因 |
| `CLARIFY` | 请求补充设备/位置信息 |
| `CANCELLED` | 已取消本次操作 |

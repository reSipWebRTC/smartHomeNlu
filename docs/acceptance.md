# SmartHome NLU 最小闭环验收用例（v1）

## 1. 验收范围
覆盖最小控制闭环：
- 搜索实体：`ha_search_entities`
- 执行控制：`ha_call_service`
- 状态验证：`ha_get_entity`

## 2. 前置条件
- `ha_gateway` 可访问并已连接 Home Assistant。
- 具备可测试实体：
  - `light.test_lamp`
  - `switch.test_plug`（可选）
- 测试账号拥有最小白名单工具权限。

## 3. 用例清单

## TC-01 正常开灯
| 项 | 内容 |
|---|---|
| 输入 | “打开客厅灯” |
| 预期流程 | `ha_search_entities -> ha_call_service -> ha_get_entity` |
| 通过标准 | 最终返回 `DONE`，实体状态为 `on` |

## TC-02 正常关灯
| 项 | 内容 |
|---|---|
| 输入 | “关闭客厅灯” |
| 预期流程 | `ha_search_entities -> ha_call_service -> ha_get_entity` |
| 通过标准 | 最终返回 `DONE`，实体状态为 `off` |

## TC-03 设备名不存在
| 项 | 内容 |
|---|---|
| 输入 | “打开银河系灯” |
| 预期流程 | `ha_search_entities` 无命中 |
| 通过标准 | 返回 `CLARIFY`，不触发 `ha_call_service` |

## TC-04 上游超时重试
| 项 | 内容 |
|---|---|
| 输入 | 任一控制指令（模拟上游超时） |
| 预期流程 | `EXECUTE -> RETRY_OR_FAIL -> EXECUTE` |
| 通过标准 | 重试次数不超过配置上限；最终成功或明确失败 |

## TC-05 权限不足
| 项 | 内容 |
|---|---|
| 输入 | 普通用户触发管理类工具 |
| 预期流程 | `CHECK_POLICY -> FAILED` |
| 通过标准 | 返回 `FORBIDDEN`，无真实控制调用 |

## TC-06 重复指令幂等
| 项 | 内容 |
|---|---|
| 输入 | 同一用户 30 秒内连续发送同一控制语句 |
| 预期流程 | 第二次命中幂等 |
| 通过标准 | 第二次不重复下发，返回 `idempotent_hit=true` |

## TC-07 高风险确认流
| 项 | 内容 |
|---|---|
| 输入 | “把前门解锁” |
| 预期流程 | `CHECK_POLICY -> WAIT_CONFIRM -> EXECUTE` |
| 通过标准 | 未确认前不执行；确认后才执行 |

## 4. 通用通过标准（DoD）
- 控制路径成功率：>= 95%（20 次连续测试）。
- 实体误匹配率：< 5%。
- 错误可分类：`ENTITY_NOT_FOUND/FORBIDDEN/UPSTREAM_TIMEOUT` 可区分。
- 所有调用都有审计记录：`trace_id + tool_name + result + latency`。

## 5. 失败记录模板

| 字段 | 说明 |
|---|---|
| `case_id` | 用例编号 |
| `trace_id` | 链路 ID |
| `input_text` | 原始输入 |
| `tool_sequence` | 工具调用序列 |
| `actual_result` | 实际结果 |
| `expected_result` | 预期结果 |
| `root_cause` | 根因分析 |
| `fix_plan` | 修复建议 |

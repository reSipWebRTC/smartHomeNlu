# SmartHome NLU 模块接口清单

## 文档信息
- 版本：v1.0
- 日期：2026-04-03
- 基线：`smarthome_nlu_architecture_module_design_v1.md`
- 目标：定义运行时与离线链路的模块接口、事件契约、错误码和超时重试规范

## 1. 接口设计约定

### 1.1 协议与命名
1. 外部接口：HTTP/JSON，前缀 `/api/v1/...`。
2. 内部接口：HTTP/JSON，前缀 `/internal/v1/...`。
3. 事件总线：Redis Streams，命名 `evt.<domain>.<event>.v1`。
4. 契约版本：通过路径版本控制（`v1`），破坏性变更新增 `v2`。

### 1.2 公共请求头
| Header | 必填 | 说明 |
|---|---|---|
| `X-Trace-Id` | 是 | 全链路追踪 ID |
| `X-Request-Id` | 是 | 单请求 ID |
| `X-User-Id` | 外部接口必填 | 用户标识（脱敏） |
| `Authorization` | 外部接口必填 | Bearer Token |
| `Content-Type` | 是 | `application/json` |

### 1.3 通用响应格式
```json
{
  "trace_id": "trc_01J...",
  "code": "OK",
  "message": "success",
  "retryable": false,
  "data": {}
}
```

### 1.4 通用错误码
| code | 含义 | retryable |
|---|---|---|
| `OK` | 成功 | 否 |
| `BAD_REQUEST` | 参数错误 | 否 |
| `UNAUTHORIZED` | 认证失败 | 否 |
| `FORBIDDEN` | 权限不足 | 否 |
| `NOT_FOUND` | 资源不存在 | 否 |
| `CONFLICT` | 幂等冲突/状态冲突 | 否 |
| `UPSTREAM_TIMEOUT` | 上游超时 | 是 |
| `UPSTREAM_ERROR` | 上游 5xx | 是 |
| `ENTITY_NOT_FOUND` | 未匹配到实体 | 否 |
| `POLICY_CONFIRM_REQUIRED` | 需二次确认 | 否 |
| `INTERNAL_ERROR` | 内部错误 | 是 |

### 1.5 超时与重试基线
1. 网关到内部服务超时：`1200ms`。
2. `nlu-main` 超时：`80ms`；`nlu-fallback` 超时：`900ms`。
3. 执行层超时：`1500ms`。
4. 仅 `UPSTREAM_TIMEOUT/UPSTREAM_ERROR` 可自动重试。
5. 默认指数退避：`50ms, 150ms, 500ms`，最多 3 次。

## 2. 接口总览清单

| 模块 | 对外协议 | 提供接口数 | 消费事件 | 产出事件 |
|---|---|---:|---|---|
| `api-gateway` | HTTP | 3 | - | `evt.request.received.v1` |
| `nlu-router` | HTTP | 1 | - | `evt.nlu.routed.v1` |
| `nlu-main` | HTTP | 1 | - | `evt.nlu.main.predicted.v1` |
| `nlu-fallback` | HTTP | 1 | - | `evt.nlu.fallback.predicted.v1` |
| `dst-service` | HTTP | 3 | `evt.dialog.turn.updated.v1` | `evt.dst.updated.v1` |
| `entity-resolver` | HTTP | 2 | - | `evt.entity.resolved.v1` |
| `policy-engine` | HTTP | 3 | - | `evt.policy.evaluated.v1` |
| `executor` | HTTP | 2 | - | `evt.execution.result.v1` |
| `ha-gateway-adapter` | HTTP | 3 | - | `evt.ha.call.result.v1` |
| `response-service` | HTTP | 1 | `evt.execution.result.v1` | `evt.response.rendered.v1` |
| `observability` | HTTP + Stream | 1 | 全量事件 | - |
| `hard-example-collector` | Stream Worker | 0 | `evt.execution.result.v1` | `evt.data.hard_example.v1` |
| `data-pipeline` | Batch Job | 0 | `evt.data.hard_example.v1` | `evt.data.dataset.ready.v1` |
| `teacher-labeling` | Batch Job | 1 | `evt.data.dataset.ready.v1` | `evt.data.labeled.ready.v1` |
| `distill-trainer` | Batch Job | 1 | `evt.data.labeled.ready.v1` | `evt.model.candidate.ready.v1` |
| `eval-gate` | Batch Job | 1 | `evt.model.candidate.ready.v1` | `evt.model.gate.result.v1` |
| `model-registry` | HTTP + Batch | 2 | `evt.model.gate.result.v1` | `evt.model.released.v1` |

## 3. 运行时接口清单

## 3.1 `api-gateway`

### `POST /api/v1/command`
用途：统一入口，接收用户指令并返回执行结果或澄清问题。

请求：
```json
{
  "session_id": "sess_001",
  "user_id": "usr_001",
  "text": "把客厅灯调到50%",
  "channel": "voice",
  "client_ts": "2026-04-03T10:00:00Z"
}
```

响应：
```json
{
  "trace_id": "trc_001",
  "code": "OK",
  "message": "success",
  "retryable": false,
  "data": {
    "status": "ok",
    "reply_text": "已将客厅灯亮度调到50%",
    "intent": "CONTROL",
    "sub_intent": "adjust_brightness"
  }
}
```

### `POST /api/v1/confirm`
用途：高风险指令二次确认提交。

### `GET /api/v1/health`
用途：网关健康检查。

## 3.2 `nlu-router`

### `POST /internal/v1/nlu/route`
请求：
```json
{
  "trace_id": "trc_001",
  "session_id": "sess_001",
  "text": "把客厅灯调到50%",
  "context": {},
  "threshold": {
    "main_pass": 0.85,
    "fallback_trigger": 0.60,
    "clarify_trigger": 0.65
  }
}
```

响应：
```json
{
  "trace_id": "trc_001",
  "code": "OK",
  "retryable": false,
  "data": {
    "route": "main",
    "intent_json": {},
    "need_clarify": false
  }
}
```

## 3.3 `nlu-main`

### `POST /internal/v1/nlu/main/predict`
输出：`intent/sub_intent/slots/confidence`。

## 3.4 `nlu-fallback`

### `POST /internal/v1/nlu/fallback/predict`
输出：与 `nlu-main` 同结构，要求 JSON 100% 可解析。

## 3.5 `dst-service`

### `GET /internal/v1/dst/session/{session_id}`
用途：读取会话状态。

### `PATCH /internal/v1/dst/session/{session_id}`
用途：更新会话字段。

### `POST /internal/v1/dst/session/{session_id}/clear`
用途：清理会话上下文。

## 3.6 `entity-resolver`

### `POST /internal/v1/entity/resolve`
请求：
```json
{
  "trace_id": "trc_001",
  "slots": {
    "device_type": "灯",
    "location": "客厅"
  },
  "domain_hint": "light",
  "top_k": 3
}
```

响应：
```json
{
  "trace_id": "trc_001",
  "code": "OK",
  "data": {
    "candidates": [
      {"entity_id": "light.living_room_main", "score": 0.94}
    ]
  }
}
```

### `POST /internal/v1/entity/reindex`
用途：刷新实体索引（全量同步）。

## 3.7 `policy-engine`

### `POST /internal/v1/policy/evaluate`
输出：`allow/deny/confirm`、风险等级、重试策略、幂等键。

### `POST /internal/v1/policy/confirm/start`
输出：确认 token 与过期时间。

### `POST /internal/v1/policy/confirm/commit`
输出：确认结果。

## 3.8 `executor`

### `POST /internal/v1/executor/run`
请求含 `intent_json + resolved_entity + policy`，输出执行结果。

### `POST /internal/v1/executor/retry`
用于按策略重试可重试错误。

## 3.9 `ha-gateway-adapter`

### `POST /internal/v1/ha/tool-call`
用途：通用工具调用。

### `POST /internal/v1/ha/service-call`
用途：封装 `ha_call_service`。

### `GET /internal/v1/ha/entities/sync`
用途：同步实体列表到本地索引。

## 3.10 `response-service`

### `POST /internal/v1/response/render`
输入执行结果，输出 `reply_text/tts_text`。

## 3.11 `observability`

### `POST /internal/v1/obs/audit`
用途：写入审计日志。

## 4. 事件接口清单（Redis Streams）

| Topic | Producer | Consumer | 关键字段 |
|---|---|---|---|
| `evt.request.received.v1` | `api-gateway` | `observability` | `trace_id,user_id,text` |
| `evt.nlu.routed.v1` | `nlu-router` | `observability` | `route,confidence` |
| `evt.entity.resolved.v1` | `entity-resolver` | `executor,observability` | `candidates,selected` |
| `evt.policy.evaluated.v1` | `policy-engine` | `executor,observability` | `decision,risk,idempotency_key` |
| `evt.execution.result.v1` | `executor` | `response-service,hard-example-collector,observability` | `status,error_code,latency_ms` |
| `evt.response.rendered.v1` | `response-service` | `observability` | `reply_type,reply_text` |
| `evt.data.hard_example.v1` | `hard-example-collector` | `data-pipeline` | `utterance,nlu_output,ha_error` |
| `evt.data.dataset.ready.v1` | `data-pipeline` | `teacher-labeling` | `dataset_uri,stats` |
| `evt.data.labeled.ready.v1` | `teacher-labeling` | `distill-trainer` | `labeled_dataset_uri` |
| `evt.model.candidate.ready.v1` | `distill-trainer` | `eval-gate` | `model_uri,metrics` |
| `evt.model.gate.result.v1` | `eval-gate` | `model-registry` | `pass/fail,reasons` |
| `evt.model.released.v1` | `model-registry` | `api-gateway,observability` | `model_version,rollout` |

## 5. 关键 Schema 清单

### 5.1 `IntentJson`
```json
{
  "intent": "CONTROL",
  "sub_intent": "adjust_brightness",
  "slots": {},
  "confidence": 0.94
}
```

### 5.2 `PolicyDecision`
```json
{
  "decision": "allow",
  "risk_level": "medium",
  "requires_confirmation": false,
  "idempotency_key": "idem:a1b2c3d4",
  "retry_policy": {"max_retries": 2, "backoff_ms": [100, 300]}
}
```

### 5.3 `ExecutionResult`
```json
{
  "status": "success",
  "tool_name": "ha_call_service",
  "entity_id": "light.living_room_main",
  "latency_ms": 312,
  "error_code": null
}
```

## 6. 接口验收检查项
1. 全部 HTTP 接口需返回统一响应格式。
2. 所有请求必须透传 `X-Trace-Id`。
3. 可重试错误必须带 `retryable=true`。
4. 所有执行请求必须生成并记录 `idempotency_key`。
5. P0/P1 风险指令必须先走确认接口。
6. `nlu-fallback` 输出 JSON 解析成功率必须为 100%。
7. `evt.execution.result.v1` 事件字段完整率必须为 100%。

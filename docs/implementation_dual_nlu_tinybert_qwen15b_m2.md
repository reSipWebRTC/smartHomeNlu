# 双路 NLU 实施方案（TinyBERT ONNX 主路 + Qwen2.5-1.5B 兜底）

## 1. 目标与部署边界
- 主流程机（当前工程运行机）负责：ASR 文本接入、主路 NLU、实体解析、策略校验、工具执行。
- 边缘机（Mac mini M2 8G，`192.168.3.44`）负责：兜底 LLM NLU（Qwen2.5-1.5B）。
- 路由策略：仅当主路低置信时调用兜底，避免 8G 机器被高并发压垮。

## 2. 目标拓扑
1. `Android ASR -> /api/v1/command (主流程机)`
2. 主流程机内部：`TinyBERT ONNX -> 置信度路由`
3. 若低置信：主流程机请求 `http://192.168.3.44:11434`（Qwen2.5-1.5B）
4. 输出统一结构化 JSON -> Policy -> Executor -> HA

## 3. 统一 NLU 输出契约
新增 `NLUResult`（主路与兜底共用）：
```json
{
  "intent": "CONTROL|QUERY|SCENE|SYSTEM|CHITCHAT",
  "sub_intent": "power_on|power_off|adjust_brightness|...",
  "slots": {
    "location": "客厅",
    "device_type": "灯",
    "value": 50,
    "value_unit": "%",
    "entity_id": "light.living_room"
  },
  "confidence": 0.91,
  "source": "main_onnx|fallback_qwen",
  "need_clarify": false
}
```

## 4. 路由规则（建议默认）
- `confidence >= 0.85`：主路结果直出。
- `0.60 <= confidence < 0.85`：主路直出 + 异步入难例队列。
- `confidence < 0.60`：调用 Qwen 兜底。
- 兜底结果 `confidence < 0.65`：返回澄清，不执行控制。

## 5. 代码改造清单（本仓库）
1. 新增文件
- `runtime/nlu_main_onnx.py`：加载 ONNX Runtime + TinyBERT 推理。
- `runtime/nlu_fallback_qwen.py`：调用 `192.168.3.44` 的 Qwen 服务。
- `runtime/nlu_schema.py`：`NLUResult` schema 校验（含错误码）。

2. 修改文件
- `runtime/nlu_router.py`：接入 `NluMainOnnx` + `NluFallbackQwen`。
- `runtime/api_gateway.py`：保留现有执行流，仅替换 NLU 来源。
- `runtime/server.py`：新增 `POST /api/v1/nlu/parse`（调试与压测专用）。
- `runtime/contracts.py`：补充 `NLU_SCHEMA_INVALID`、`LLM_TIMEOUT` 等错误码。

## 6. Qwen 兜底接口约束
- 请求超时：`800ms`（硬超时 `1200ms`）。
- 并发：`1`。
- 上下文：`num_ctx <= 1024`。
- 输出约束：
  - 优先使用模型服务的结构化 JSON 模式。
  - 服务端必须二次校验 schema，不合法时进行 1 次修复重试。

## 7. 环境变量模板（主流程机）
```bash
# 主路
SMARTHOME_NLU_MAIN_PROVIDER=onnx
SMARTHOME_NLU_MAIN_MODEL_PATH=/opt/models/tinybert_nlu_int8.onnx
SMARTHOME_NLU_MAIN_LABEL_PATH=/opt/models/labels.json

# 兜底
SMARTHOME_NLU_FALLBACK_PROVIDER=qwen_remote
SMARTHOME_NLU_FALLBACK_URL=http://192.168.3.44:11434/api/chat
SMARTHOME_NLU_FALLBACK_MODEL=qwen2.5:1.5b
SMARTHOME_NLU_FALLBACK_TIMEOUT_MS=800
SMARTHOME_NLU_FALLBACK_MAX_RETRY=1

# 路由阈值
SMARTHOME_NLU_MAIN_PASS=0.85
SMARTHOME_NLU_FALLBACK_TRIGGER=0.60
SMARTHOME_NLU_CLARIFY_TRIGGER=0.65
```

## 8. 性能与容量（M2 8G）
- 主路 ONNX 常驻内存小，可稳定低延迟。
- Qwen2.5-1.5B 只做兜底时，P95 通常可控在 `300~900ms`（视 prompt 长度与冷启动）。
- 避免多并发请求同时打到兜底机；使用队列或信号量限流。

## 9. 验收标准
1. 主路 P95 `< 60ms`。
2. 兜底 P95 `< 900ms`，超时率 `< 2%`。
3. NLU JSON 合法率 `100%`（含修复重试后）。
4. 高频家居指令意图准确率 `>= 95%`。
5. 高风险操作确认覆盖率 `100%`。

## 10. 发布与回滚
- 发布顺序：先灰度 `nlu/parse`，再切 `command` 主路径。
- 回滚开关：`SMARTHOME_NLU_FALLBACK_PROVIDER=disabled` 时仅主路+澄清。
- 紧急降级：保留当前 `nlu_main.py + nlu_fallback.py` 规则路由作为兜底。

## 11. 当前实施优先级
1. 落地 `runtime/nlu_fallback_qwen.py`（先打通远程 Qwen 调用）。
2. 增加 `NLUResult` schema 校验与错误码。
3. 接入 `nlu_router` 新路由并加压测脚本。
4. 最后上线 `POST /api/v1/nlu/parse` 与监控指标。

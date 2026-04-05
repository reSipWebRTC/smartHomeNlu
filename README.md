# SmartHome NLU Runtime

面向智能家居控制的本地运行时，提供：
- NLU 路由（`rule -> TinyBERT ONNX -> Qwen fallback`）
- 策略与确认流（RBAC / 高风险确认 / 幂等）
- 执行层（`ha_gateway` / `ha_mcp` 双通道）
- Web 调试台与会话历史

## 快速启动

### 1. 安装依赖
```bash
python3 -m pip install -r requirements.txt
```

### 2. 一键本地运行（推荐）
```bash
./run_local.sh up
```

服务默认地址：
- API: `http://127.0.0.1:8000`
- Web Console: `http://127.0.0.1:8000/`

### 3. 基础验证
```bash
curl -sS http://127.0.0.1:8000/api/v1/health
curl -sS -X POST 'http://127.0.0.1:8000/api/v1/command' \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"sess_demo","user_id":"usr_demo","text":"打开客厅灯"}'
```

## 常用命令

```bash
./run_local.sh up      # 启动 redis + runtime
./run_local.sh check   # 跑验收检查
./run_local.sh down    # 停止本地服务
```

日志文件：
- `.runtime_local/runtime.log`
- `.runtime_local/redis.log`

## NLU 模式切换

默认是规则主路。启用 ONNX + Qwen 兜底可参考：

```bash
bash scripts/start_local_tinybert_onnx.sh
```

## 关键环境变量

- `SMARTHOME_HA_CONTROL_MODE`: `auto | ha_gateway | ha_mcp`
- `SMARTHOME_HA_GATEWAY_URL`
- `SMARTHOME_HA_MCP_URL`, `SMARTHOME_HA_MCP_TOKEN`
- `SMARTHOME_NLU_MAIN_PROVIDER`, `SMARTHOME_NLU_MAIN_MODEL_PATH`
- `SMARTHOME_NLU_FALLBACK_PROVIDER`, `SMARTHOME_NLU_FALLBACK_URL`
- `SMARTHOME_LOG_LEVEL`, `SMARTHOME_DEBUG_FLOW`
- `SMARTHOME_EVENT_BUS_MAX_PER_TOPIC`（EventBus ring buffer，默认 300）

## 测试

```bash
PYTHONPATH=. uv run pytest -q
```

## 文档导航

- 架构与数据流：`docs/architecture_flow_and_dfd.md`
- ONNX + Qwen 实施：`docs/implementation_flow_main_v1_onnx_fallback_qwen.md`
- 联调手册：`docs/integration_guide.md`

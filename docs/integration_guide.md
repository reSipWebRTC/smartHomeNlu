# 联调手册（HA MCP + Runtime）

本文档用于端到端联调：`ha-mcp-web` + `SmartHome Runtime` + `Web Console`。

## 1. 启动 ha-mcp-web（终端 1）

```bash
cd /home/david/Work/smartHomeNlu/ha-mcp
export HOMEASSISTANT_URL=http://127.0.0.1:8123
export HOMEASSISTANT_TOKEN='你的HA长效Token'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
export NO_PROXY=127.0.0.1,localhost,::1
uv run ha-mcp-web
```

默认监听：`http://127.0.0.1:8086/mcp`

## 2. 启动 Runtime（终端 2）

### 2.1 基础联调（走 ha_mcp）
```bash
cd /home/david/Work/smartHomeNlu
source .venv/bin/activate
pip install -r requirements.txt

export SMARTHOME_HA_CONTROL_MODE=ha_mcp
export SMARTHOME_HA_MCP_URL=http://127.0.0.1:8086/mcp
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
export NO_PROXY=127.0.0.1,localhost,::1

export SMARTHOME_DEBUG_FLOW=1
export SMARTHOME_LOG_LEVEL=DEBUG
./run_local.sh up
tail -f .runtime_local/runtime.log
```

### 2.2 启用 TinyBERT ONNX + 远程 Qwen fallback
```bash
cd /home/david/Work/smartHomeNlu
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
export NO_PROXY=127.0.0.1,localhost,::1,192.168.3.44

export SMARTHOME_DEBUG_FLOW=1
export SMARTHOME_LOG_LEVEL=DEBUG
export SMARTHOME_NLU_MAIN_PROVIDER=onnx
export SMARTHOME_NLU_MAIN_MODEL_PATH=.runtime_local/models/tinybert_nlu_multitask_v1/model.onnx
export SMARTHOME_NLU_MAIN_LABEL_PATH=.runtime_local/models/tinybert_nlu_multitask_v1/labels.json
export SMARTHOME_NLU_MAIN_VOCAB_PATH=.runtime_local/models/tinybert_nlu_multitask_v1/vocab.txt
export SMARTHOME_NLU_FALLBACK_PROVIDER=qwen
export SMARTHOME_NLU_FALLBACK_URL=http://192.168.3.44:11434/api/chat
export SMARTHOME_NLU_FALLBACK_MODEL=qwen2.5:1.5b
export SMARTHOME_NLU_FALLBACK_TIMEOUT_MS=2500
./run_local.sh up
```

## 3. 联调验证

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
curl -sS 'http://127.0.0.1:8000/api/v1/entities?limit=20'
curl -sS 'http://127.0.0.1:8000/api/v1/entities?domain=switch&limit=50'
curl -sS -X POST 'http://127.0.0.1:8000/api/v1/command' \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"sess_test_01","user_id":"usr_test_01","text":"打开插座"}'
```

Web 控制台：
- `http://127.0.0.1:8000/`

## 4. 常见问题

1. `route` 一直是 `main` 且模型版本为 `nlu-main-v1`  
未启用 ONNX provider，检查 `SMARTHOME_NLU_MAIN_PROVIDER` 与模型路径。

2. Qwen fallback 频繁失败  
优先检查 `NO_PROXY` 是否包含远端 IP，确认 `curl http://192.168.3.44:11434/api/tags` 可达。

3. 日志过多  
调低日志级别：`SMARTHOME_LOG_LEVEL=INFO`；或保留 DEBUG 并限制噪声 logger。  

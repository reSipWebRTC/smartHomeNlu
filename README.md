# SmartHome NLU Runtime
# codex --dangerously-bypass-approvals-and-sandbox
## Single Machine Quick Start

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Start Redis (local):

```bash
redis-server --port 6379
```

3. Start FastAPI runtime:

```bash
SMARTHOME_REDIS_URL=redis://127.0.0.1:6379/0 uvicorn runtime.server:app --host 0.0.0.0 --port 8000
```

Runtime supports two HA control channels in parallel:
- `ha_gateway` (WebSocket gateway)
- `ha_mcp` (MCP server)

`SMARTHOME_HA_CONTROL_MODE` can force one channel: `ha_gateway` or `ha_mcp`.
If omitted (`auto`), runtime prefers `SMARTHOME_HA_GATEWAY_URL`, then `SMARTHOME_HA_MCP_URL`.

Optional: connect to real `ha_gateway` (`ws://.../ws`):

```bash
SMARTHOME_REDIS_URL=redis://127.0.0.1:6379/0 \
SMARTHOME_HA_GATEWAY_URL=ws://127.0.0.1:8124/ws \
uvicorn runtime.server:app --host 0.0.0.0 --port 8000
```

Optional: connect to real `ha_mcp` (`/mcp`):

```bash
SMARTHOME_REDIS_URL=redis://127.0.0.1:6379/0 \
SMARTHOME_HA_CONTROL_MODE=ha_mcp \
SMARTHOME_HA_MCP_URL=http://127.0.0.1:8086/mcp \
SMARTHOME_HA_MCP_TOKEN=your_token_if_needed \
uvicorn runtime.server:app --host 0.0.0.0 --port 8000
```

Note: `ha_mcp` channel needs MCP Python client support in runtime environment
(`pip install mcp`).

4. Run tests:

```bash
python3 -m unittest discover -s tests -v
python3 -m pytest -q
```

## One-Click Local Run

You can use the helper script at repo root:

```bash
./run_local.sh all
```

Common commands:

```bash
./run_local.sh up
./run_local.sh check
./run_local.sh down
```

Optional env overrides:
- `HOST`, `APP_PORT`, `REDIS_HOST`, `REDIS_PORT`
- `SMARTHOME_REDIS_URL`
- `SMARTHOME_HA_CONTROL_MODE` (`auto` | `ha_gateway` | `ha_mcp`)
- `SMARTHOME_HA_GATEWAY_URL`, `SMARTHOME_HA_GATEWAY_TIMEOUT_SEC`
- `SMARTHOME_HA_MCP_URL`, `SMARTHOME_HA_MCP_TOKEN`, `SMARTHOME_HA_MCP_TIMEOUT_SEC`, `SMARTHOME_HA_MCP_TIMEOUT_RETRIES`
- `SMARTHOME_HA_MCP_SYNC_DOMAINS`, `SMARTHOME_HA_MCP_SYNC_LIMIT_PER_DOMAIN`

`ha_mcp` client behavior notes:
- If `SMARTHOME_HA_MCP_URL` is provided as `http://host:port`, runtime auto-normalizes it to `http://host:port/mcp`.
- On timeout, runtime retries tool calls (`SMARTHOME_HA_MCP_TIMEOUT_RETRIES`, default `1`).

Runtime logs and pid files are written under `.runtime_local/`.

## Web Client

After starting the server, open:

```text
http://127.0.0.1:8000/
```

The Web page supports:
- entering natural-language intent text
- sending `/api/v1/command` requests
- one-click dual-channel compare via `/api/v1/compare-channels` (`ha_gateway` vs `ha_mcp`)
- handling `POLICY_CONFIRM_REQUIRED` and submitting `/api/v1/confirm`
- listing devices via `/api/v1/entities` and generating one-click templates
- loading/clearing session history via `/api/v1/history` (server-side persistence)
- viewing raw JSON response and interaction timeline

`/api/v1/entities` supports:
- `limit` (default `200`, max `1000`)
- `hide_default` (default `true`, hides common HA built-in default entities such as `sun.sun` and `update.home_assistant_*`)

## Live HA Gateway Smoke Tests (Opt-in)

Live smoke tests are skipped by default. They run only when `LIVE_HA_GATEWAY_TEST=1`.

```bash
LIVE_HA_GATEWAY_TEST=1 \
SMARTHOME_HA_GATEWAY_URL=ws://127.0.0.1:8124/ws \
LIVE_HA_GATEWAY_SWITCH_ENTITY_ID=switch.your_test_switch \
python3 -m pytest -q tests/test_live_ha_gateway_smoke.py
```


 按这组命令跑就行：

  # 终端1：启动 ha-mcp-web
  cd /home/david/Work/smartHomeNlu/ha-mcp
  export HOMEASSISTANT_URL=http://127.0.0.1:8123
  export HOMEASSISTANT_TOKEN='你的HA长效Token'
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
  export NO_PROXY=127.0.0.1,localhost,::1
  uv run ha-mcp-web

  # 终端2：启动 SmartHome runtime（走 ha_mcp）
  cd /home/david/Work/smartHomeNlu
  source .venv/bin/activate
  pip install -r requirements.txt

  export SMARTHOME_HA_CONTROL_MODE=ha_mcp
  export SMARTHOME_HA_MCP_URL=http://127.0.0.1:8086/mcp
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
  export NO_PROXY=127.0.0.1,localhost,::1

  bash scripts/start_local_tinybert_onnx.sh

  验证：

  curl -sS http://127.0.0.1:8000/api/v1/entities?limit=20
  curl -sS 'http://127.0.0.1:8000/api/v1/entities?domain=switch&limit=50'
  curl -sS -X POST 'http://127.0.0.1:8000/api/v1/command' \
    -H 'Content-Type: application/json' \
    -d '{"session_id":"sess_test_01","user_id":"usr_test_01","text":"打开插座"}'


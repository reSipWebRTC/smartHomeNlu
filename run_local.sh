#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.runtime_local"
mkdir -p "${RUNTIME_DIR}"

ACTION="${1:-all}"
HOST="${HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

REDIS_URL="redis://${REDIS_HOST}:${REDIS_PORT}/0"
HEALTH_URL="http://${HOST}:${APP_PORT}/api/v1/health"
COMMAND_URL="http://${HOST}:${APP_PORT}/api/v1/command"
CONFIRM_URL="http://${HOST}:${APP_PORT}/api/v1/confirm"

REDIS_PID_FILE="${RUNTIME_DIR}/redis.pid"
APP_PID_FILE="${RUNTIME_DIR}/runtime.pid"
REDIS_LOG="${RUNTIME_DIR}/redis.log"
APP_LOG="${RUNTIME_DIR}/runtime.log"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

if [[ -x "${ROOT_DIR}/.venv/bin/uvicorn" ]]; then
  UVICORN_BIN="${ROOT_DIR}/.venv/bin/uvicorn"
else
  UVICORN_BIN="$(command -v uvicorn || true)"
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ERROR] Missing command: ${cmd}" >&2
    exit 1
  fi
}

is_port_open() {
  local host="$1"
  local port="$2"
  ${PYTHON_BIN} - "$host" "$port" <<'PY'
import socket
import sys
host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    s.connect((host, port))
except OSError:
    print("0")
else:
    print("1")
finally:
    s.close()
PY
}

wait_for_port() {
  local host="$1"
  local port="$2"
  local timeout_sec="${3:-15}"
  local i=0
  while (( i < timeout_sec * 10 )); do
    if [[ "$(is_port_open "$host" "$port")" == "1" ]]; then
      return 0
    fi
    sleep 0.1
    ((i+=1))
  done
  return 1
}

start_redis() {
  require_cmd redis-server

  if [[ "$(is_port_open "$REDIS_HOST" "$REDIS_PORT")" == "1" ]]; then
    echo "[INFO] Redis already listening on ${REDIS_HOST}:${REDIS_PORT}"
    return 0
  fi

  echo "[INFO] Starting Redis on ${REDIS_HOST}:${REDIS_PORT}"
  nohup redis-server --port "$REDIS_PORT" >"$REDIS_LOG" 2>&1 &
  local pid=$!
  echo "$pid" >"$REDIS_PID_FILE"

  if ! wait_for_port "$REDIS_HOST" "$REDIS_PORT" 20; then
    echo "[ERROR] Redis failed to start. Log: ${REDIS_LOG}" >&2
    exit 1
  fi

  echo "[OK] Redis started (pid=${pid})"
}

start_runtime() {
  require_cmd curl
  if [[ -z "${UVICORN_BIN}" ]]; then
    echo "[ERROR] uvicorn not found. Install deps first: python3 -m pip install -r requirements.txt" >&2
    exit 1
  fi

  if [[ "$(is_port_open "$HOST" "$APP_PORT")" == "1" ]]; then
    echo "[INFO] Runtime already listening on ${HOST}:${APP_PORT}"
    return 0
  fi

  echo "[INFO] Starting Runtime on ${HOST}:${APP_PORT}"
  local -a env_args
  env_args=("SMARTHOME_REDIS_URL=${SMARTHOME_REDIS_URL:-$REDIS_URL}")

  # Ensure local HA/MCP endpoints are not routed through global HTTP proxies.
  local no_proxy_value="${NO_PROXY:-${no_proxy:-}}"
  if [[ -z "${no_proxy_value}" ]]; then
    no_proxy_value="127.0.0.1,localhost,::1"
  else
    case ",${no_proxy_value}," in
      *,127.0.0.1,* ) ;;
      * ) no_proxy_value="${no_proxy_value},127.0.0.1" ;;
    esac
    case ",${no_proxy_value}," in
      *,localhost,* ) ;;
      * ) no_proxy_value="${no_proxy_value},localhost" ;;
    esac
    case ",${no_proxy_value}," in
      *,::1,* ) ;;
      * ) no_proxy_value="${no_proxy_value},::1" ;;
    esac
  fi
  env_args+=("NO_PROXY=${no_proxy_value}" "no_proxy=${no_proxy_value}")

  if [[ -n "${SMARTHOME_HA_CONTROL_MODE:-}" ]]; then
    env_args+=("SMARTHOME_HA_CONTROL_MODE=${SMARTHOME_HA_CONTROL_MODE}")
  fi
  if [[ -n "${SMARTHOME_HA_GATEWAY_URL:-}" ]]; then
    env_args+=("SMARTHOME_HA_GATEWAY_URL=${SMARTHOME_HA_GATEWAY_URL}")
  fi
  if [[ -n "${SMARTHOME_HA_GATEWAY_TIMEOUT_SEC:-}" ]]; then
    env_args+=("SMARTHOME_HA_GATEWAY_TIMEOUT_SEC=${SMARTHOME_HA_GATEWAY_TIMEOUT_SEC}")
  fi
  if [[ -n "${SMARTHOME_HA_MCP_URL:-}" ]]; then
    env_args+=("SMARTHOME_HA_MCP_URL=${SMARTHOME_HA_MCP_URL}")
  fi
  if [[ -n "${SMARTHOME_HA_MCP_TOKEN:-}" ]]; then
    env_args+=("SMARTHOME_HA_MCP_TOKEN=${SMARTHOME_HA_MCP_TOKEN}")
  fi
  if [[ -n "${SMARTHOME_HA_MCP_TIMEOUT_SEC:-}" ]]; then
    env_args+=("SMARTHOME_HA_MCP_TIMEOUT_SEC=${SMARTHOME_HA_MCP_TIMEOUT_SEC}")
  fi
  if [[ -n "${SMARTHOME_HA_MCP_TIMEOUT_RETRIES:-}" ]]; then
    env_args+=("SMARTHOME_HA_MCP_TIMEOUT_RETRIES=${SMARTHOME_HA_MCP_TIMEOUT_RETRIES}")
  fi

  env "${env_args[@]}" nohup "$UVICORN_BIN" runtime.server:app --host "$HOST" --port "$APP_PORT" >"$APP_LOG" 2>&1 &
  echo $! >"$APP_PID_FILE"

  if ! wait_for_port "$HOST" "$APP_PORT" 30; then
    echo "[ERROR] Runtime failed to start. Log: ${APP_LOG}" >&2
    exit 1
  fi

  echo "[OK] Runtime started (pid=$(cat "$APP_PID_FILE" 2>/dev/null || echo unknown))"
}

json_value() {
  local path="$1"
  local raw_json="$2"
  ${PYTHON_BIN} - "$path" "$raw_json" <<'PY'
import json
import sys

path = sys.argv[1].split(".")
try:
    obj = json.loads(sys.argv[2])
except Exception:
    sys.exit(2)
for key in path:
    if isinstance(obj, dict):
        if key not in obj:
            sys.exit(3)
        obj = obj[key]
    else:
        sys.exit(4)
if isinstance(obj, (dict, list)):
    print(json.dumps(obj, ensure_ascii=False))
else:
    print(obj)
PY
}

assert_http_json_code() {
  local method="$1"
  local url="$2"
  local payload="$3"
  local expected_code="$4"

  local response
  if [[ -n "$payload" ]]; then
    if ! response="$(curl -sS -m 8 -X "$method" "$url" -H 'Content-Type: application/json' -d "$payload" -w $'\n%{http_code}')"; then
      echo "[ERROR] ${method} ${url} request failed" >&2
      exit 1
    fi
  else
    if ! response="$(curl -sS -m 8 -X "$method" "$url" -w $'\n%{http_code}')"; then
      echo "[ERROR] ${method} ${url} request failed" >&2
      exit 1
    fi
  fi

  local http_status="${response##*$'\n'}"
  local body="${response%$'\n'*}"
  local code
  if ! code="$(json_value "code" "$body" 2>/dev/null)"; then
    echo "[ERROR] ${method} ${url} returned non-JSON body or missing code (http=${http_status})" >&2
    echo "[ERROR] Body: ${body}" >&2
    exit 1
  fi

  if [[ "$code" != "$expected_code" ]]; then
    echo "[ERROR] ${method} ${url} expected code=${expected_code}, got code=${code}, http=${http_status}" >&2
    echo "[ERROR] Body: ${body}" >&2
    exit 1
  fi

  echo "$body"
}

check_flow() {
  require_cmd curl

  echo "[INFO] Running acceptance checks"

  local health_body
  health_body="$(assert_http_json_code GET "$HEALTH_URL" "" "OK")"
  local health_state
  health_state="$(json_value "data.status" "$health_body")"
  if [[ "$health_state" != "up" ]]; then
    echo "[ERROR] health.data.status expected up, got ${health_state}" >&2
    exit 1
  fi

  local cmd_body
  cmd_body="$(assert_http_json_code POST "$COMMAND_URL" '{"session_id":"sess_local_001","user_id":"usr_local_001","text":"把客厅灯调到50%"}' "OK")"
  local cmd_status
  cmd_status="$(json_value "data.status" "$cmd_body")"
  if [[ "$cmd_status" != "ok" ]]; then
    echo "[ERROR] command data.status expected ok, got ${cmd_status}" >&2
    exit 1
  fi

  local risk_body
  risk_body="$(assert_http_json_code POST "$COMMAND_URL" '{"session_id":"sess_local_002","user_id":"usr_local_002","user_role":"normal_user","text":"把前门解锁"}' "POLICY_CONFIRM_REQUIRED")"
  local token
  token="$(json_value "data.confirm_token" "$risk_body")"

  local confirm_body
  confirm_body="$(assert_http_json_code POST "$CONFIRM_URL" "{\"confirm_token\":\"${token}\",\"accept\":true}" "OK")"
  local confirm_status
  confirm_status="$(json_value "data.status" "$confirm_body")"
  if [[ "$confirm_status" != "ok" ]]; then
    echo "[ERROR] confirm data.status expected ok, got ${confirm_status}" >&2
    exit 1
  fi

  echo "[OK] Acceptance checks passed"
}

stop_pid_file() {
  local pid_file="$1"
  local name="$2"

  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  rm -f "$pid_file"

  if [[ -z "$pid" ]]; then
    return 0
  fi

  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "[INFO] Stopping ${name} (pid=${pid})"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 0.3
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi
}

down() {
  stop_pid_file "$APP_PID_FILE" "runtime"
  stop_pid_file "$REDIS_PID_FILE" "redis"
  echo "[OK] Local services stopped (if owned by script)"
}

usage() {
  cat <<'EOF'
Usage:
  ./run_local.sh all    # start + acceptance check (default)
  ./run_local.sh up     # start redis + runtime
  ./run_local.sh check  # run acceptance checks only
  ./run_local.sh down   # stop services started by this script

Optional env:
  HOST, APP_PORT, REDIS_HOST, REDIS_PORT
  SMARTHOME_REDIS_URL
  SMARTHOME_HA_CONTROL_MODE  # auto | ha_gateway | ha_mcp
  SMARTHOME_HA_GATEWAY_URL, SMARTHOME_HA_GATEWAY_TIMEOUT_SEC
  SMARTHOME_HA_MCP_URL, SMARTHOME_HA_MCP_TOKEN, SMARTHOME_HA_MCP_TIMEOUT_SEC
EOF
}

case "$ACTION" in
  all)
    start_redis
    start_runtime
    check_flow
    ;;
  up)
    start_redis
    start_runtime
    ;;
  check)
    check_flow
    ;;
  down)
    down
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "[ERROR] Unknown action: ${ACTION}" >&2
    usage
    exit 1
    ;;
esac

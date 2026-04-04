import time

from fastapi.testclient import TestClient

from runtime.server import create_app


class FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}

    @staticmethod
    def _now() -> float:
        return time.time()

    def ping(self) -> bool:
        return True

    def _cleanup(self, key: str) -> None:
        item = self._data.get(key)
        if not item:
            return
        expires_at, _ = item
        if self._now() > expires_at:
            self._data.pop(key, None)

    def setex(self, key: str, ttl_sec: int, value: str) -> bool:
        self._data[key] = (self._now() + int(ttl_sec), value)
        return True

    def get(self, key: str):
        self._cleanup(key)
        item = self._data.get(key)
        if not item:
            return None
        _, value = item
        return value

    def delete(self, key: str) -> int:
        existed = key in self._data
        self._data.pop(key, None)
        return 1 if existed else 0


def _client() -> TestClient:
    app = create_app(redis_client=FakeRedis())
    return TestClient(app)


def test_http_health() -> None:
    client = _client()
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "OK"
    assert body["data"]["components"]["state_store"]["mode"] == "redis"


def test_http_web_index() -> None:
    client = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "SmartHome Intent Console" in resp.text


def test_http_web_app_js() -> None:
    client = _client()
    resp = client.get("/web/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers.get("content-type", "")
    assert "submitCommand" in resp.text


def test_http_entities_list() -> None:
    client = _client()
    resp = client.get("/api/v1/entities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "OK"
    assert body["data"]["count"] >= 1
    assert body["data"]["items"][0]["entity_id"]


def test_http_bad_request() -> None:
    client = _client()
    resp = client.post(
        "/api/v1/command",
        json={
            "session_id": "sess_bad_001",
            "text": "把客厅灯调到50%",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "BAD_REQUEST"


def test_http_command_success() -> None:
    client = _client()
    resp = client.post(
        "/api/v1/command",
        json={
            "session_id": "sess_http_001",
            "user_id": "usr_http_001",
            "text": "把客厅灯调到55%",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "OK"
    assert body["data"]["status"] == "ok"


def test_http_confirm_flow() -> None:
    client = _client()
    first = client.post(
        "/api/v1/command",
        json={
            "session_id": "sess_http_002",
            "user_id": "usr_http_002",
            "user_role": "normal_user",
            "text": "把前门解锁",
        },
    )
    assert first.status_code == 409
    payload = first.json()
    assert payload["code"] == "POLICY_CONFIRM_REQUIRED"
    token = payload["data"]["confirm_token"]

    second = client.post(
        "/api/v1/confirm",
        json={
            "confirm_token": token,
            "accept": True,
        },
    )
    assert second.status_code == 200
    assert second.json()["code"] == "OK"


def test_http_idempotency_with_redis_backend() -> None:
    client = _client()
    req = {
        "session_id": "sess_http_003",
        "user_id": "usr_http_003",
        "text": "把客厅灯调到50%",
    }
    first = client.post("/api/v1/command", json=req)
    second = client.post("/api/v1/command", json=req)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["idempotent_hit"] is True


def test_http_history_roundtrip_and_clear() -> None:
    client = _client()
    session_id = "sess_http_hist_001"
    user_id = "usr_http_hist_001"

    cmd = client.post(
        "/api/v1/command",
        json={
            "session_id": session_id,
            "user_id": user_id,
            "text": "把客厅灯调到42%",
        },
    )
    assert cmd.status_code == 200
    assert cmd.json()["code"] == "OK"

    history = client.get("/api/v1/history", params={"session_id": session_id, "limit": 20})
    assert history.status_code == 200
    body = history.json()
    assert body["code"] == "OK"
    assert body["data"]["count"] >= 1
    latest = body["data"]["items"][-1]
    assert latest["action"] == "command"
    assert latest["session_id"] == session_id
    assert latest["user_id"] == user_id

    cleared = client.delete("/api/v1/history", params={"session_id": session_id})
    assert cleared.status_code == 200
    assert cleared.json()["code"] == "OK"

    after = client.get("/api/v1/history", params={"session_id": session_id})
    assert after.status_code == 200
    assert after.json()["data"]["count"] == 0


def test_http_compare_channels(monkeypatch) -> None:
    for key in (
        "SMARTHOME_HA_CONTROL_MODE",
        "SMARTHOME_HA_GATEWAY_URL",
        "SMARTHOME_HA_MCP_URL",
        "SMARTHOME_HA_MCP_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)

    client = _client()
    resp = client.post(
        "/api/v1/compare-channels",
        json={
            "session_id": "sess_http_cmp_001",
            "user_id": "usr_http_cmp_001",
            "text": "把客厅灯调到50%",
            "user_role": "normal_user",
            "top_k": 3,
            "isolate_session": True,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "OK"
    report = body["data"]
    assert "channels" in report
    assert "ha_gateway" in report["channels"]
    assert "ha_mcp" in report["channels"]
    assert "response" in report["channels"]["ha_gateway"]
    assert "response" in report["channels"]["ha_mcp"]
    assert "consistency" in report
    assert isinstance(report["consistency"].get("checks", []), list)


def test_http_nlu_parse() -> None:
    client = _client()
    resp = client.post(
        "/api/v1/nlu/parse",
        json={
            "session_id": "sess_nlu_parse_001",
            "user_id": "usr_nlu_parse_001",
            "text": "打开客厅灯",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "OK"
    assert body["data"]["status"] in {"ok", "clarify"}
    assert body["data"]["route"] in {"main", "fallback"}
    intent_json = body["data"]["intent_json"]
    assert "intent" in intent_json
    assert "sub_intent" in intent_json
    assert "slots" in intent_json
    assert "confidence" in intent_json

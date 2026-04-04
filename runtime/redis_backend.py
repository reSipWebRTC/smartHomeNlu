from __future__ import annotations

import json
import time
from typing import Any, Dict, List


class RedisStateBackend:
    """State backend for session/dedup/confirm data.

    When Redis is configured and reachable, state is persisted in Redis.
    Otherwise it falls back to in-process memory so the runtime still works.
    """

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._redis: Any | None = None
        self._mode = "memory"
        self._last_error: str | None = None

        self._memory_sessions: Dict[str, Dict[str, Any]] = {}
        self._memory_confirm: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._memory_dedup: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._memory_pending_command: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._memory_history: Dict[str, List[Dict[str, Any]]] = {}

        if redis_client is not None:
            try:
                redis_client.ping()
                self._redis = redis_client
                self._mode = "redis"
            except Exception as exc:  # pragma: no cover - defensive
                self._last_error = str(exc)
        elif redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self._redis = client
                self._mode = "redis"
            except Exception as exc:
                self._last_error = str(exc)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def health(self) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "redis_connected": self._mode == "redis",
            "redis_error": self._last_error,
        }

    @staticmethod
    def _json_dumps(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _json_loads(raw: str | bytes | None) -> Dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not raw:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        return parsed

    @staticmethod
    def _is_expired(expires_at: float) -> bool:
        return time.time() > expires_at

    @staticmethod
    def _normalize_history(raw: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        if not raw:
            return []
        items = raw.get("items")
        if not isinstance(items, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                normalized.append(dict(item))
        return normalized

    # Session state
    def _session_key(self, session_id: str) -> str:
        return f"smarthome:session:{session_id}"

    def get_session(self, session_id: str) -> Dict[str, Any] | None:
        if self._redis is not None:
            raw = self._redis.get(self._session_key(session_id))
            return self._json_loads(raw)
        return self._memory_sessions.get(session_id)

    def set_session(self, session_id: str, payload: Dict[str, Any], ttl_sec: int) -> None:
        if self._redis is not None:
            self._redis.setex(self._session_key(session_id), ttl_sec, self._json_dumps(payload))
            return
        self._memory_sessions[session_id] = dict(payload)

    def clear_session(self, session_id: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._session_key(session_id))
            return
        self._memory_sessions.pop(session_id, None)

    # Confirm token
    def _confirm_key(self, token: str) -> str:
        return f"smarthome:confirm:{token}"

    def get_confirm(self, token: str) -> Dict[str, Any] | None:
        if self._redis is not None:
            raw = self._redis.get(self._confirm_key(token))
            return self._json_loads(raw)

        cached = self._memory_confirm.get(token)
        if not cached:
            return None
        expires_at, payload = cached
        if self._is_expired(expires_at):
            self._memory_confirm.pop(token, None)
            return None
        return dict(payload)

    def set_confirm(self, token: str, payload: Dict[str, Any], ttl_sec: int) -> None:
        ttl_sec = max(1, int(ttl_sec))
        if self._redis is not None:
            self._redis.setex(self._confirm_key(token), ttl_sec, self._json_dumps(payload))
            return
        self._memory_confirm[token] = (time.time() + ttl_sec, dict(payload))

    def delete_confirm(self, token: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._confirm_key(token))
            return
        self._memory_confirm.pop(token, None)

    # Pending command for confirm flow
    def _pending_command_key(self, token: str) -> str:
        return f"smarthome:pending_command:{token}"

    def get_pending_command(self, token: str) -> Dict[str, Any] | None:
        if self._redis is not None:
            raw = self._redis.get(self._pending_command_key(token))
            return self._json_loads(raw)

        cached = self._memory_pending_command.get(token)
        if not cached:
            return None
        expires_at, payload = cached
        if self._is_expired(expires_at):
            self._memory_pending_command.pop(token, None)
            return None
        return dict(payload)

    def set_pending_command(self, token: str, payload: Dict[str, Any], ttl_sec: int) -> None:
        ttl_sec = max(1, int(ttl_sec))
        if self._redis is not None:
            self._redis.setex(self._pending_command_key(token), ttl_sec, self._json_dumps(payload))
            return
        self._memory_pending_command[token] = (time.time() + ttl_sec, dict(payload))

    def delete_pending_command(self, token: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._pending_command_key(token))
            return
        self._memory_pending_command.pop(token, None)

    # Dedup cache
    def _dedup_key(self, key: str) -> str:
        return f"smarthome:dedup:{key}"

    def get_dedup(self, key: str) -> Dict[str, Any] | None:
        if self._redis is not None:
            raw = self._redis.get(self._dedup_key(key))
            return self._json_loads(raw)

        cached = self._memory_dedup.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if self._is_expired(expires_at):
            self._memory_dedup.pop(key, None)
            return None
        return dict(payload)

    def set_dedup(self, key: str, payload: Dict[str, Any], ttl_sec: int) -> None:
        ttl_sec = max(1, int(ttl_sec))
        if self._redis is not None:
            self._redis.setex(self._dedup_key(key), ttl_sec, self._json_dumps(payload))
            return
        self._memory_dedup[key] = (time.time() + ttl_sec, dict(payload))

    # Session history
    def _history_key(self, session_id: str) -> str:
        return f"smarthome:history:{session_id}"

    def append_history(
        self,
        session_id: str,
        item: Dict[str, Any],
        *,
        max_items: int = 120,
        ttl_sec: int = 86400,
    ) -> None:
        max_items = max(10, min(int(max_items), 500))
        ttl_sec = max(60, int(ttl_sec))

        if self._redis is not None:
            key = self._history_key(session_id)
            existing = self._normalize_history(self._json_loads(self._redis.get(key)))
            existing.append(dict(item))
            trimmed = existing[-max_items:]
            self._redis.setex(key, ttl_sec, self._json_dumps({"items": trimmed}))
            return

        existing = list(self._memory_history.get(session_id, []))
        existing.append(dict(item))
        self._memory_history[session_id] = existing[-max_items:]

    def get_history(self, session_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 200))

        if self._redis is not None:
            key = self._history_key(session_id)
            items = self._normalize_history(self._json_loads(self._redis.get(key)))
            return [dict(item) for item in items[-limit:]]

        items = self._memory_history.get(session_id, [])
        return [dict(item) for item in items[-limit:]]

    def clear_history(self, session_id: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._history_key(session_id))
            return
        self._memory_history.pop(session_id, None)

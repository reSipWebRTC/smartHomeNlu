from __future__ import annotations

from typing import Any, Dict

from .contracts import SessionState
from .redis_backend import RedisStateBackend


class DstService:
    def __init__(self, state_backend: RedisStateBackend | None = None, session_ttl_sec: int = 300) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._state_backend = state_backend
        self._session_ttl_sec = session_ttl_sec

    def _save(self, state: SessionState) -> None:
        if self._state_backend is None:
            self._sessions[state.session_id] = state
            return
        self._state_backend.set_session(state.session_id, state.as_dict(), ttl_sec=self._session_ttl_sec)

    def get_session(self, session_id: str, user_id: str) -> SessionState:
        state: SessionState | None = None
        if self._state_backend is None:
            state = self._sessions.get(session_id)
        else:
            raw = self._state_backend.get_session(session_id)
            if raw is not None:
                state = SessionState(**raw)

        if state is None:
            state = SessionState(session_id=session_id, user_id=user_id)
            self._save(state)
        elif state.user_id != user_id:
            state.user_id = user_id
            self._save(state)
        return state

    def patch_session(self, session_id: str, user_id: str, updates: Dict[str, Any]) -> SessionState:
        state = self.get_session(session_id, user_id)
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
        self._save(state)
        return state

    def clear_session(self, session_id: str, user_id: str) -> SessionState:
        if self._state_backend is None:
            self._sessions[session_id] = SessionState(session_id=session_id, user_id=user_id)
            return self._sessions[session_id]
        self._state_backend.clear_session(session_id)
        state = SessionState(session_id=session_id, user_id=user_id)
        self._save(state)
        return state

    def inherit_slots(self, session_id: str, user_id: str, slots: Dict[str, Any]) -> Dict[str, Any]:
        state = self.get_session(session_id, user_id)
        inherited = dict(slots)
        if "location" not in inherited and state.last_location:
            inherited["location"] = state.last_location
        if "device_type" not in inherited and state.last_device_type:
            inherited["device_type"] = state.last_device_type
        return inherited

    def mark_low_confidence(self, session_id: str, user_id: str) -> int:
        state = self.get_session(session_id, user_id)
        state.low_conf_streak += 1
        state.turn_count += 1
        self._save(state)
        return state.low_conf_streak

    def mark_success_turn(
        self,
        session_id: str,
        user_id: str,
        *,
        intent: str,
        slots: Dict[str, Any],
        entity_id: str | None,
        result: str,
    ) -> SessionState:
        state = self.get_session(session_id, user_id)
        state.last_intent = intent
        state.last_device_id = entity_id
        state.last_device_type = slots.get("device_type")
        state.last_location = slots.get("location")
        state.last_attribute = slots.get("attribute")
        state.last_ha_result = result
        state.low_conf_streak = 0
        state.turn_count += 1
        self._save(state)
        return state

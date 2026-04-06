from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Tuple

from .contracts import PolicyDecision
from .debug_log import get_logger
from .event_bus import InMemoryEventBus
from .redis_backend import RedisStateBackend
from .utils import new_id


ROLE_WHITELIST = {
    "normal_user": {
        "ha_search_entities",
        "ha_call_service",
        "ha_get_entity",
        "ha_bulk_control",
        "ha_overview",
    },
    "admin": {
        "ha_search_entities",
        "ha_call_service",
        "ha_get_entity",
        "ha_bulk_control",
        "ha_overview",
        "ha_create_automation",
        "ha_update_automation",
        "ha_create_backup",
    },
}


class PolicyEngine:
    def __init__(self, event_bus: InMemoryEventBus, state_backend: RedisStateBackend | None = None) -> None:
        self.event_bus = event_bus
        self._state_backend = state_backend
        self._confirm_tokens: Dict[str, Dict[str, Any]] = {}
        self._logger = get_logger("policy")

    def _plan_tool(self, intent_json: Dict[str, Any]) -> str:
        intent = intent_json["intent"]
        sub_intent = intent_json["sub_intent"]

        if intent == "SYSTEM" and sub_intent == "backup":
            return "ha_create_backup"
        if intent in {"SCHEDULE", "AUTOMATION"}:
            return "ha_create_automation"
        if intent == "QUERY":
            return "ha_get_entity"
        return "ha_call_service"

    def _risk_level(self, intent_json: Dict[str, Any]) -> str:
        intent = intent_json["intent"]
        sub_intent = intent_json["sub_intent"]
        if sub_intent == "unlock":
            return "critical"
        if intent == "SYSTEM":
            return "high"
        if intent in {"SCHEDULE", "AUTOMATION"}:
            return "medium"
        return "low"

    def _make_idempotency_key(self, user_id: str, intent_json: Dict[str, Any]) -> str:
        key_data = {
            "user_id": user_id,
            "intent": intent_json.get("intent", ""),
            "sub_intent": intent_json.get("sub_intent", ""),
            "entity_id": str(intent_json.get("slots", {}).get("entity_id", "")),
            "attribute": str(intent_json.get("slots", {}).get("attribute", "")),
            "value": str(intent_json.get("slots", {}).get("value", "")),
        }
        raw = json.dumps(key_data, sort_keys=True)
        return "idem:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def evaluate(
        self,
        *,
        trace_id: str,
        user_id: str,
        user_role: str,
        intent_json: Dict[str, Any],
    ) -> PolicyDecision:
        tool_name = self._plan_tool(intent_json)
        risk_level = self._risk_level(intent_json)
        idempotency_key = self._make_idempotency_key(user_id, intent_json)
        self._logger.debug(
            "evaluate start trace_id=%s user_id=%s role=%s tool=%s risk=%s idem=%s intent=%s/%s",
            trace_id,
            user_id,
            user_role,
            tool_name,
            risk_level,
            idempotency_key,
            intent_json.get("intent"),
            intent_json.get("sub_intent"),
        )

        if user_role != "super_admin":
            allowed = ROLE_WHITELIST.get(user_role, set())
            if tool_name not in allowed:
                decision = PolicyDecision(
                    decision="deny",
                    risk_level=risk_level,
                    requires_confirmation=False,
                    idempotency_key=idempotency_key,
                    retry_policy={"max_retries": 0, "backoff_ms": []},
                    tool_name=tool_name,
                )
                self.event_bus.publish(
                    "evt.policy.evaluated.v1",
                    {
                        "trace_id": trace_id,
                        "decision": decision.decision,
                        "risk": decision.risk_level,
                        "idempotency_key": decision.idempotency_key,
                    },
                )
                self._logger.info(
                    "evaluate deny trace_id=%s user_id=%s role=%s tool=%s",
                    trace_id,
                    user_id,
                    user_role,
                    tool_name,
                )
                return decision

        requires_confirmation = risk_level in {"high", "critical"}
        decision = PolicyDecision(
            decision="confirm" if requires_confirmation else "allow",
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            idempotency_key=idempotency_key,
            retry_policy={"max_retries": 3, "backoff_ms": [50, 150, 500]},
            tool_name=tool_name,
        )

        self.event_bus.publish(
            "evt.policy.evaluated.v1",
            {
                "trace_id": trace_id,
                "decision": decision.decision,
                "risk": decision.risk_level,
                "idempotency_key": decision.idempotency_key,
            },
        )
        self._logger.debug(
            "evaluate result trace_id=%s decision=%s requires_confirmation=%s risk=%s",
            trace_id,
            decision.decision,
            decision.requires_confirmation,
            decision.risk_level,
        )
        return decision

    def confirm_start(self, *, idempotency_key: str, risk_level: str) -> Dict[str, Any]:
        ttl_sec = 10 if risk_level == "critical" else 15
        token = new_id("cfm")
        record = {
            "idempotency_key": idempotency_key,
            "expires_at": time.time() + ttl_sec,
            "risk_level": risk_level,
            "confirmed": False,
        }
        if self._state_backend is None:
            self._confirm_tokens[token] = record
        else:
            self._state_backend.set_confirm(token, record, ttl_sec=ttl_sec)
        self._logger.info("confirm_start token=%s risk=%s ttl=%s", token, risk_level, ttl_sec)
        return {"confirm_token": token, "expires_in_sec": ttl_sec}

    def confirm_commit(self, token: str) -> Tuple[bool, str]:
        if self._state_backend is None:
            record = self._confirm_tokens.get(token)
        else:
            record = self._state_backend.get_confirm(token)
        if not record:
            self._logger.info("confirm_commit token=%s result=NOT_FOUND", token)
            return False, "NOT_FOUND"
        if time.time() > record["expires_at"]:
            if self._state_backend is None:
                del self._confirm_tokens[token]
            else:
                self._state_backend.delete_confirm(token)
            self._logger.info("confirm_commit token=%s result=EXPIRED", token)
            return False, "CONFIRM_TOKEN_EXPIRED"
        record["confirmed"] = True
        if self._state_backend is None:
            self._confirm_tokens[token] = record
        else:
            ttl_sec = max(1, int(record["expires_at"] - time.time()))
            self._state_backend.set_confirm(token, record, ttl_sec=ttl_sec)
        self._logger.info("confirm_commit token=%s result=OK", token)
        return True, "OK"

    def consume_confirm_token(self, token: str) -> Dict[str, Any] | None:
        if self._state_backend is None:
            record = self._confirm_tokens.get(token)
        else:
            record = self._state_backend.get_confirm(token)
        if not record or not record.get("confirmed"):
            return None
        if self._state_backend is None:
            return self._confirm_tokens.pop(token)
        self._state_backend.delete_confirm(token)
        return record

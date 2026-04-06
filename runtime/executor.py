from __future__ import annotations

import time
from typing import Any, Dict, Tuple

from .contracts import ExecutionResult, PolicyDecision
from .debug_log import compact, get_logger
from .event_bus import InMemoryEventBus
from .observability import Observability
from .redis_backend import RedisStateBackend
from .utils import intent_to_domain, monotonic_ms

RETRYABLE_CODES = {"UPSTREAM_TIMEOUT", "UPSTREAM_ERROR"}


class Executor:
    def __init__(
        self,
        *,
        event_bus: InMemoryEventBus,
        adapter: Any,
        observability: Observability,
        state_backend: RedisStateBackend | None = None,
        dedup_window_sec: int = 30,
    ) -> None:
        self.event_bus = event_bus
        self.adapter = adapter
        self.observability = observability
        self._state_backend = state_backend
        self.dedup_window_sec = dedup_window_sec
        self._dedup_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._logger = get_logger("executor")

    def _dedup_get(self, key: str) -> Dict[str, Any] | None:
        if self._state_backend is not None:
            return self._state_backend.get_dedup(key)

        cached = self._dedup_cache.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if time.time() > expires_at:
            del self._dedup_cache[key]
            return None
        return dict(payload)

    def _dedup_set(self, key: str, payload: Dict[str, Any]) -> None:
        if self._state_backend is not None:
            self._state_backend.set_dedup(key, payload, ttl_sec=self.dedup_window_sec)
            return
        self._dedup_cache[key] = (time.time() + self.dedup_window_sec, dict(payload))

    def _build_call(self, intent_json: Dict[str, Any], entity_id: str | None) -> Dict[str, Any]:
        intent = intent_json["intent"]
        sub_intent = intent_json["sub_intent"]
        slots = intent_json.get("slots", {})

        if intent == "SYSTEM" and sub_intent == "backup":
            return {
                "tool_name": "ha_create_backup",
                "service_name": "system.create_backup",
                "mode": "tool",
                "params": {},
                "entity_id": None,
            }

        if intent == "QUERY":
            return {
                "tool_name": "ha_get_entity",
                "service_name": "entity.get",
                "mode": "tool",
                "params": {"entity_id": entity_id},
                "entity_id": entity_id,
            }

        domain = entity_id.split(".")[0] if entity_id and "." in entity_id else intent_to_domain(sub_intent, slots)
        service = "turn_on"
        params: Dict[str, Any] = {}

        if sub_intent == "adjust_brightness":
            service = "turn_on"
            if "value" in slots:
                params["brightness_pct"] = int(slots["value"])
        elif sub_intent == "power_on":
            service = "turn_on"
        elif sub_intent == "power_off":
            service = "turn_off"
        elif sub_intent == "set_temperature":
            domain = "climate"
            service = "set_temperature"
            if "value" in slots:
                params["temperature"] = int(slots["value"])
        elif sub_intent == "unlock":
            domain = "lock"
            service = "unlock"
        elif sub_intent == "activate_scene":
            domain = "scene"
            service = "turn_on"

        return {
            "tool_name": "ha_call_service",
            "service_name": f"{domain}.{service}",
            "mode": "service",
            "domain": domain,
            "service": service,
            "params": params,
            "entity_id": entity_id,
        }

    def _invoke_adapter(self, call_plan: Dict[str, Any]) -> Dict[str, Any]:
        if call_plan["mode"] == "tool":
            return self.adapter.tool_call(call_plan["tool_name"], call_plan["params"])
        return self.adapter.call_service(
            domain=call_plan["domain"],
            service=call_plan["service"],
            entity_id=call_plan["entity_id"] or "",
            params=call_plan["params"],
        )

    def _execute_with_retry(self, call_plan: Dict[str, Any], retry_policy: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        max_retries = int(retry_policy.get("max_retries", 0))
        backoff_ms = list(retry_policy.get("backoff_ms", []))

        attempt = 0
        while True:
            attempt += 1
            raw = self._invoke_adapter(call_plan)
            self._logger.debug(
                "invoke attempt=%d tool=%s service=%s success=%s raw=%s",
                attempt,
                call_plan.get("tool_name"),
                call_plan.get("service_name"),
                bool(raw.get("success")),
                compact(raw),
            )
            if raw.get("success"):
                return raw, attempt

            code = str(raw.get("error_code", "UPSTREAM_ERROR"))
            if code not in RETRYABLE_CODES:
                return raw, attempt
            if attempt > max_retries:
                return raw, attempt

            delay_ms = backoff_ms[attempt - 1] if attempt - 1 < len(backoff_ms) else (backoff_ms[-1] if backoff_ms else 0)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

    def run(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str,
        intent_json: Dict[str, Any],
        policy: PolicyDecision,
        resolved_entity_id: str | None,
        confirmed: bool,
    ) -> Dict[str, Any]:
        self._logger.debug(
            "run start trace_id=%s session_id=%s user_id=%s policy=%s intent=%s resolved_entity=%s confirmed=%s",
            trace_id,
            session_id,
            user_id,
            policy.decision,
            f"{intent_json.get('intent')}/{intent_json.get('sub_intent')}",
            resolved_entity_id,
            confirmed,
        )
        if policy.decision == "deny":
            result = ExecutionResult(
                status="blocked",
                tool_name=policy.tool_name,
                entity_id=resolved_entity_id,
                latency_ms=0,
                error_code="FORBIDDEN",
                upstream_status_code=403,
            )
            return {"code": "FORBIDDEN", "execution_result": result}

        if policy.requires_confirmation and not confirmed:
            result = ExecutionResult(
                status="blocked",
                tool_name=policy.tool_name,
                entity_id=resolved_entity_id,
                latency_ms=0,
                error_code="POLICY_CONFIRM_REQUIRED",
                upstream_status_code=409,
            )
            return {"code": "POLICY_CONFIRM_REQUIRED", "execution_result": result}

        cached = self._dedup_get(policy.idempotency_key)
        if cached:
            result = ExecutionResult(
                status=cached["status"],
                tool_name=cached["tool_name"],
                entity_id=cached.get("entity_id"),
                latency_ms=0,
                error_code=cached.get("error_code"),
                upstream_status_code=cached.get("upstream_status_code"),
                deduplicated=True,
            )
            self.event_bus.publish(
                "evt.execution.result.v1",
                {
                    "trace_id": trace_id,
                    "status": result.status,
                    "error_code": result.error_code,
                    "latency_ms": result.latency_ms,
                    "tool_name": result.tool_name,
                    "entity_id": result.entity_id,
                    "deduplicated": True,
                },
            )
            return {"code": "OK", "execution_result": result}

        start_ms = monotonic_ms()
        call_plan = self._build_call(intent_json, resolved_entity_id)
        raw, attempts = self._execute_with_retry(call_plan, policy.retry_policy)

        success = bool(raw.get("success"))
        code = "OK" if success else str(raw.get("error_code", "UPSTREAM_ERROR"))
        latency_ms = max(1, monotonic_ms() - start_ms)

        result = ExecutionResult(
            status="success" if success else "failure",
            tool_name=call_plan["tool_name"],
            entity_id=call_plan.get("entity_id"),
            latency_ms=latency_ms,
            error_code=None if success else code,
            upstream_status_code=raw.get("status_code"),
        )
        self._logger.info(
            "run result trace_id=%s code=%s status=%s tool=%s entity_id=%s latency_ms=%s attempts=%s",
            trace_id,
            code,
            result.status,
            result.tool_name,
            result.entity_id,
            result.latency_ms,
            attempts,
        )

        self.event_bus.publish(
            "evt.execution.result.v1",
            {
                "trace_id": trace_id,
                "status": result.status,
                "error_code": result.error_code,
                "latency_ms": result.latency_ms,
                "tool_name": result.tool_name,
                "entity_id": result.entity_id,
                "upstream_status_code": result.upstream_status_code,
                "attempts": attempts,
            },
        )

        self.observability.write_audit(
            user_id=user_id,
            session_id=session_id,
            tool_name=result.tool_name,
            entity_id=result.entity_id or "",
            service=call_plan["service_name"],
            params=call_plan.get("params", {}),
            nlu_intent=f"{intent_json['intent']}/{intent_json['sub_intent']}",
            nlu_confidence=float(intent_json.get("confidence", 0.0)),
            result=result.status,
            latency_ms=result.latency_ms,
            idempotency_key=policy.idempotency_key,
        )

        if success:
            self._dedup_set(
                policy.idempotency_key,
                {
                    "status": result.status,
                    "tool_name": result.tool_name,
                    "entity_id": result.entity_id,
                    "error_code": result.error_code,
                    "upstream_status_code": result.upstream_status_code,
                },
            )

        return {"code": code, "execution_result": result}

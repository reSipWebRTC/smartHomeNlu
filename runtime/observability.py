from __future__ import annotations

from typing import Any, Dict, List

from .utils import short_hash, utc_now_iso


REQUIRED_AUDIT_FIELDS = {
    "timestamp",
    "user_id",
    "session_id",
    "tool_name",
    "entity_id",
    "service",
    "params_hash",
    "nlu_intent",
    "nlu_confidence",
    "result",
    "latency_ms",
    "idempotency_key",
}


class Observability:
    def __init__(self) -> None:
        self._audit_logs: List[Dict[str, Any]] = []

    def write_audit(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        entity_id: str,
        service: str,
        params: Dict[str, Any],
        nlu_intent: str,
        nlu_confidence: float,
        result: str,
        latency_ms: int,
        idempotency_key: str,
        high_risk_extra: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        log = {
            "timestamp": utc_now_iso(),
            "user_id": user_id,
            "session_id": session_id,
            "tool_name": tool_name,
            "entity_id": entity_id,
            "service": service,
            "params_hash": short_hash({k: str(v) for k, v in params.items()}),
            "nlu_intent": nlu_intent,
            "nlu_confidence": round(float(nlu_confidence), 3),
            "result": result,
            "latency_ms": int(latency_ms),
            "idempotency_key": idempotency_key,
        }
        if high_risk_extra:
            log.update(high_risk_extra)
        self._audit_logs.append(log)
        return log

    def validate_latest_audit_fields(self) -> bool:
        if not self._audit_logs:
            return False
        return REQUIRED_AUDIT_FIELDS.issubset(set(self._audit_logs[-1].keys()))

    @property
    def audit_logs(self) -> List[Dict[str, Any]]:
        return list(self._audit_logs)

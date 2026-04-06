from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


ERROR_RETRYABLE: Dict[str, bool] = {
    "OK": False,
    "BAD_REQUEST": False,
    "UNAUTHORIZED": False,
    "FORBIDDEN": False,
    "NOT_FOUND": False,
    "CONFLICT": False,
    "UPSTREAM_TIMEOUT": True,
    "UPSTREAM_ERROR": True,
    "ENTITY_NOT_FOUND": False,
    "POLICY_CONFIRM_REQUIRED": False,
    "CONFIRM_TOKEN_EXPIRED": False,
    "NLU_FALLBACK_PARSE_ERROR": False,
    "INTERNAL_ERROR": True,
}


def is_retryable(code: str) -> bool:
    return ERROR_RETRYABLE.get(code, False)


def make_response(
    trace_id: str,
    code: str = "OK",
    message: str = "success",
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "trace_id": trace_id,
        "code": code,
        "message": message,
        "retryable": is_retryable(code),
        "data": data or {},
    }


@dataclass
class IntentJson:
    intent: str
    sub_intent: str
    slots: Dict[str, Any]
    confidence: float
    multi_commands: Optional[List[Dict[str, Any]]] = None

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 3)
        return payload


@dataclass
class PolicyDecision:
    decision: str
    risk_level: str
    requires_confirmation: bool
    idempotency_key: str
    retry_policy: Dict[str, Any]
    tool_name: str
    confirm_token: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResult:
    status: str
    tool_name: str
    entity_id: Optional[str]
    latency_ms: int
    error_code: Optional[str]
    upstream_status_code: Optional[int] = None
    deduplicated: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionState:
    session_id: str
    user_id: str
    last_intent: Optional[str] = None
    last_device_id: Optional[str] = None
    last_device_type: Optional[str] = None
    last_location: Optional[str] = None
    last_attribute: Optional[str] = None
    last_ha_result: Optional[str] = None
    turn_count: int = 0
    low_conf_streak: int = 0
    pending_slots: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntityCandidate:
    entity_id: str
    score: float
    name: str
    area: str

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["score"] = round(float(self.score), 3)
        return payload

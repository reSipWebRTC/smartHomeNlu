from __future__ import annotations

from typing import Any, Dict

from .event_bus import InMemoryEventBus


class HardExampleCollector:
    def __init__(self, event_bus: InMemoryEventBus) -> None:
        self.event_bus = event_bus

    def _publish(self, payload: Dict[str, Any]) -> None:
        self.event_bus.publish("evt.data.hard_example.v1", payload)

    def collect_low_confidence(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str,
        text: str,
        route: str,
        reason: str,
        intent_json: Dict[str, Any],
    ) -> None:
        self._publish(
            {
                "trace_id": trace_id,
                "sample_type": "low_confidence",
                "reason": reason,
                "route": route,
                "session_id": session_id,
                "user_id": user_id,
                "utterance": text,
                "intent": intent_json.get("intent"),
                "sub_intent": intent_json.get("sub_intent"),
                "confidence": round(float(intent_json.get("confidence", 0.0)), 3),
                "slots": dict(intent_json.get("slots", {})),
            }
        )

    def collect_execution_failure(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str,
        text: str,
        error_code: str,
        intent_json: Dict[str, Any],
        tool_name: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        self._publish(
            {
                "trace_id": trace_id,
                "sample_type": "execution_failure",
                "reason": "ha_execution_failed",
                "session_id": session_id,
                "user_id": user_id,
                "utterance": text,
                "intent": intent_json.get("intent"),
                "sub_intent": intent_json.get("sub_intent"),
                "confidence": round(float(intent_json.get("confidence", 0.0)), 3),
                "slots": dict(intent_json.get("slots", {})),
                "tool_name": tool_name,
                "entity_id": entity_id,
                "error_code": error_code,
            }
        )

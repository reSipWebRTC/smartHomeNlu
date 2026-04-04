from __future__ import annotations

from typing import Any, Dict

from .contracts import IntentJson
from .event_bus import InMemoryEventBus
from .nlu_fallback import NluFallback
from .nlu_main import NluMain


DEFAULT_THRESHOLD = {
    "main_pass": 0.85,
    "fallback_trigger": 0.60,
    "clarify_trigger": 0.65,
}


class NluRouter:
    def __init__(self, event_bus: InMemoryEventBus) -> None:
        self.nlu_main = NluMain()
        self.nlu_fallback = NluFallback()
        self.event_bus = event_bus

    def route(
        self,
        *,
        trace_id: str,
        text: str,
        context: Dict[str, Any] | None = None,
        threshold: Dict[str, float] | None = None,
    ) -> Dict[str, Any]:
        threshold = {**DEFAULT_THRESHOLD, **(threshold or {})}
        context = context or {}

        main_result = self.nlu_main.predict(text, context)

        if main_result.confidence >= threshold["main_pass"]:
            route = "main"
            intent_json = main_result
            need_clarify = False
            model_version = "nlu-main-v1"
        elif main_result.confidence >= threshold["fallback_trigger"]:
            route = "main"
            intent_json = main_result
            need_clarify = False
            model_version = "nlu-main-v1"
        else:
            fallback_result = self.nlu_fallback.predict(text, context)
            route = "fallback"
            intent_json = fallback_result
            need_clarify = fallback_result.confidence < threshold["clarify_trigger"]
            model_version = "nlu-fallback-v1"

        self.event_bus.publish(
            "evt.nlu.routed.v1",
            {
                "trace_id": trace_id,
                "route": route,
                "confidence": round(float(intent_json.confidence), 3),
                "intent": intent_json.intent,
                "model_version": model_version,
            },
        )

        return {
            "route": route,
            "intent_json": intent_json,
            "need_clarify": need_clarify,
            "model_version": model_version,
            "threshold": threshold,
        }

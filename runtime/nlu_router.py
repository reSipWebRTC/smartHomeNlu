from __future__ import annotations

import os
from typing import Any, Dict

from .contracts import IntentJson
from .event_bus import InMemoryEventBus
from .nlu_fallback import NluFallback
from .nlu_fallback_qwen import NluFallbackQwen
from .nlu_main import NluMain
from .nlu_main_onnx import NluMainOnnx


DEFAULT_THRESHOLD = {
    "main_pass": 0.85,
    "fallback_trigger": 0.60,
    "clarify_trigger": 0.65,
}


class NluRouter:
    def __init__(self, event_bus: InMemoryEventBus) -> None:
        self.nlu_main, self.main_model_version = self._build_main()
        self.nlu_fallback, self.fallback_model_version = self._build_fallback()
        self.event_bus = event_bus

    @staticmethod
    def _build_main() -> tuple[Any, str]:
        provider = (os.getenv("SMARTHOME_NLU_MAIN_PROVIDER") or "rule").strip().lower()
        if provider in {"onnx", "tinybert", "tinybert_onnx"}:
            predictor = NluMainOnnx()
            return predictor, predictor.model_version
        return NluMain(), "nlu-main-v1"

    @staticmethod
    def _build_fallback() -> tuple[Any, str]:
        provider = (os.getenv("SMARTHOME_NLU_FALLBACK_PROVIDER") or "rule").strip().lower()
        if provider in {"qwen", "qwen_remote", "ollama"}:
            return NluFallbackQwen(), "nlu-fallback-qwen-v1"
        return NluFallback(), "nlu-fallback-v1"

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
            model_version = self.main_model_version
        elif main_result.confidence >= threshold["fallback_trigger"]:
            route = "main"
            intent_json = main_result
            need_clarify = False
            model_version = self.main_model_version
        else:
            fallback_result = self.nlu_fallback.predict(text, context)
            route = "fallback"
            intent_json = fallback_result
            need_clarify = fallback_result.confidence < threshold["clarify_trigger"]
            model_version = self.fallback_model_version

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

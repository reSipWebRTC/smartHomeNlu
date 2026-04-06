from __future__ import annotations

import os
import re
from typing import Any, Dict

from .contracts import IntentJson
from .nlu_canonicalizer import canonicalize_intent
from .debug_log import get_logger
from .event_bus import InMemoryEventBus
from .hot_words_lexicon import get_hot_words_lexicon
from .nlu_fallback import NluFallback
from .nlu_fallback_qwen import NluFallbackQwen
from .nlu_main import NluMain
from .nlu_main_onnx import NluMainOnnx
from .phonetic_corrector import PhoneticCorrector


DEFAULT_THRESHOLD = {
    "rule_pass": 0.88,
    "main_pass": 0.85,
    "fallback_trigger": 0.60,
    "clarify_trigger": 0.65,
}

_MULTI_ACTION_PATTERN = re.compile(r"(打开|开启|关掉|关闭|关上|调到|调成|调高|调低|设为|调为|查询|解锁|开锁)")
_HOT_WORDS = get_hot_words_lexicon()
_MULTI_CONNECTORS = tuple(
    sorted(
        {
            "并且",
            "然后",
            "再",
            "同时",
            "接着",
            "还有",
            "以及",
            "和",
            "把",
            *tuple(_HOT_WORDS.connectors),
        },
        key=len,
        reverse=True,
    )
)
_MULTI_SEPARATOR_PATTERN = re.compile(r"(；|;|，|,|" + "|".join(re.escape(item) for item in _MULTI_CONNECTORS) + r")")


class NluRouter:
    def __init__(self, event_bus: InMemoryEventBus) -> None:
        self.nlu_rule = NluMain()
        self.rule_model_version = "nlu-rule-v1"
        self.nlu_main, self.main_model_version = self._build_main()
        self.nlu_fallback, self.fallback_model_version = self._build_fallback()
        self.event_bus = event_bus
        self._phonetic_corrector = PhoneticCorrector()
        self._init_phonetic_vocabulary()
        self._logger = get_logger("nlu_router")
        self._logger.info(
            "router init rule_model=%s main_model=%s fallback_model=%s",
            self.rule_model_version,
            self.main_model_version,
            self.fallback_model_version,
        )

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

    def _init_phonetic_vocabulary(self) -> None:
        """Build vocabulary for phonetic correction from hot words."""
        vocab: set[str] = set()
        for token, _ in _HOT_WORDS.action_terms:
            if token:
                vocab.add(token)
        for token, _ in _HOT_WORDS.device_terms:
            if token:
                vocab.add(token)
        for token in _HOT_WORDS.location_terms:
            if token:
                vocab.add(token)
        vocab.update(_HOT_WORDS.set_terms)
        vocab.update(_HOT_WORDS.temperature_terms)
        vocab.update(_HOT_WORDS.brightness_terms)
        vocab.update(_HOT_WORDS.query_terms)
        vocab.update(_HOT_WORDS.scene_terms)
        vocab.update(_HOT_WORDS.connectors)
        for extra_terms in _HOT_WORDS.device_type_terms.values():
            vocab.update(extra_terms)
        self._phonetic_corrector.update_vocabulary(vocab)

    @staticmethod
    def _has_target(slots: Dict[str, Any]) -> bool:
        return bool(slots.get("entity_id") or slots.get("device_type") or slots.get("scene_name"))

    @classmethod
    def _missing_required_slots(cls, intent_json: IntentJson) -> bool:
        intent = str(intent_json.intent or "").upper()
        sub_intent = str(intent_json.sub_intent or "")
        slots = intent_json.slots or {}
        sub_intent_norm = sub_intent.strip().lower()

        if intent == "CHITCHAT":
            return False
        if intent == "SYSTEM":
            return False
        if intent == "SCENE":
            return not cls._has_target(slots)
        if intent == "QUERY":
            return not cls._has_target(slots)
        if intent == "CONTROL":
            if sub_intent_norm == "set_temperature":
                # Temperature setting requires explicit value.
                return slots.get("value") in (None, "")
            if sub_intent_norm == "adjust_brightness":
                # Relative commands like "调亮一点" can be valid without a number.
                return False
            return not cls._has_target(slots)
        return True

    @classmethod
    def _accept_rule(cls, result: IntentJson, threshold: Dict[str, float]) -> bool:
        if float(result.confidence) < float(threshold["rule_pass"]):
            return False
        if str(result.intent or "").upper() == "CHITCHAT" and str(result.sub_intent or "") in {"unknown", "clarify_needed"}:
            return False
        return not cls._missing_required_slots(result)

    @classmethod
    def _accept_main(cls, result: IntentJson, threshold: Dict[str, float]) -> bool:
        confidence = float(result.confidence)
        if confidence < float(threshold["fallback_trigger"]):
            return False
        if str(result.intent or "").upper() == "CHITCHAT" and str(result.sub_intent or "") in {"unknown", "clarify_needed"}:
            return False
        return not cls._missing_required_slots(result)

    @staticmethod
    def _rule_should_escalate(text: str, result: IntentJson) -> bool:
        raw = str(text or "")
        slots = result.slots or {}
        sub_intent = str(result.sub_intent or "").strip().lower()
        action_hits = len(_MULTI_ACTION_PATTERN.findall(raw))
        has_separators = bool(_MULTI_SEPARATOR_PATTERN.search(raw))

        # A high-confidence rule result from a likely multi-command sentence is
        # often over-compressed to a single intent.
        if action_hits >= 2 and has_separators:
            return True

        # power_on/off should not carry temperature/brightness numeric payload;
        # this usually means slots leaked from another clause.
        if sub_intent in {"power_on", "power_off"} and any(key in slots for key in ("value", "value_unit", "attribute")):
            return True
        return False

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

        self._logger.debug(
            "route start trace_id=%s text=%s threshold=%s",
            trace_id,
            text,
            threshold,
        )

        # Phonetic correction: fix ASR errors before NLU parsing
        corrected_text = self._phonetic_corrector.correct(text)
        if corrected_text != text:
            self._logger.info(
                "route phonetic_corrected trace_id=%s original=%s corrected=%s",
                trace_id,
                text,
                corrected_text,
            )

        rule_result = self.nlu_rule.predict(corrected_text, context)
        rule_result = canonicalize_intent(rule_result)
        route_stage = "rule"

        has_multi = bool(rule_result.multi_commands and len(rule_result.multi_commands) > 1)
        if self._accept_rule(rule_result, threshold) and (has_multi or not self._rule_should_escalate(corrected_text, rule_result)):
            route = "main"
            intent_json = rule_result
            need_clarify = False
            model_version = self.rule_model_version
        else:
            main_result = self.nlu_main.predict(corrected_text, context)
            main_result = canonicalize_intent(main_result)
            route_stage = "tinybert"
            if self._accept_main(main_result, threshold):
                route = "main"
                intent_json = main_result
                need_clarify = False
                model_version = self.main_model_version
            else:
                fallback_result = self.nlu_fallback.predict(corrected_text, context)
                fallback_result = canonicalize_intent(fallback_result)
                route_stage = "qwen"
                route = "fallback"
                intent_json = fallback_result
                need_clarify = bool(
                    float(fallback_result.confidence) < float(threshold["clarify_trigger"])
                    or self._missing_required_slots(fallback_result)
                )
                model_version = self.fallback_model_version

        self._logger.debug(
            "route result trace_id=%s route=%s stage=%s intent=%s/%s confidence=%.3f model=%s clarify=%s",
            trace_id,
            route,
            route_stage,
            intent_json.intent,
            intent_json.sub_intent,
            float(intent_json.confidence),
            model_version,
            bool(need_clarify),
        )

        self.event_bus.publish(
            "evt.nlu.routed.v1",
            {
                "trace_id": trace_id,
                "route": route,
                "route_stage": route_stage,
                "confidence": round(float(intent_json.confidence), 3),
                "intent": intent_json.intent,
                "model_version": model_version,
            },
        )

        return {
            "route": route,
            "route_stage": route_stage,
            "intent_json": intent_json,
            "need_clarify": need_clarify,
            "model_version": model_version,
            "threshold": threshold,
        }

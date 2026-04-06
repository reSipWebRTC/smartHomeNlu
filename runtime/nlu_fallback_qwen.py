from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

import httpx

from .contracts import IntentJson
from .debug_log import compact, get_logger
from .nlu_fallback import NluFallback


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _clamp_confidence(value: Any, default: float = 0.70) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        f = default
    if f < 0:
        return 0.0
    if f > 1:
        return 1.0
    return f


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _fix_unquoted_keys(raw: str) -> str:
    return re.sub(r'(\b[a-zA-Z_]\w*\b)\s*:', r'"\1":', raw)


def _extract_json_object(raw: str) -> str | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    return match.group(0)


def _to_slots(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _normalize_sub_intent(action: str) -> str:
    action_l = action.strip().lower()
    if action_l in {"on", "turn_on", "open", "power_on"}:
        return "power_on"
    if action_l in {"off", "turn_off", "close", "power_off"}:
        return "power_off"
    if action_l in {"set_temperature", "temperature"}:
        return "set_temperature"
    if action_l in {"adjust_brightness", "brightness"}:
        return "adjust_brightness"
    if action_l in {"unlock", "open_lock"}:
        return "unlock"
    return action.strip() or "unknown"


def _infer_sub_intent_from_payload(intent: str, slots: Dict[str, Any], payload: Dict[str, Any]) -> str:
    action = str(payload.get("action") or payload.get("sub_action") or "").strip()
    if action:
        return _normalize_sub_intent(action)

    merged_text = json.dumps({"slots": slots, "payload": payload}, ensure_ascii=False).lower()
    if any(token in merged_text for token in ("温度", "temperature", "temp")):
        return "set_temperature"
    if any(token in merged_text for token in ("亮度", "brightness", "brightness_pct", "%")):
        return "adjust_brightness"
    if any(token in merged_text for token in ("解锁", "开锁", "unlock")):
        return "unlock"
    if intent == "QUERY":
        return "query_status"
    if intent == "SCENE":
        return "activate_scene"
    if intent == "SYSTEM":
        return "backup"
    if intent == "CONTROL":
        return "power_on"
    return "unknown"


class NluFallbackQwen:
    """
    兜底解析器：远程调用 Qwen（Ollama API），失败时回退到本地规则解析器。
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        model: str | None = None,
        timeout_ms: int | None = None,
        max_retry: int | None = None,
        temperature: float | None = None,
        num_ctx: int | None = None,
        local_fallback: NluFallback | None = None,
    ) -> None:
        self.url = (url or os.getenv("SMARTHOME_NLU_FALLBACK_URL") or "http://127.0.0.1:11434/api/chat").strip()
        self.model = (model or os.getenv("SMARTHOME_NLU_FALLBACK_MODEL") or "qwen2.5:1.5b").strip()
        self.timeout_ms = timeout_ms if timeout_ms is not None else _env_int("SMARTHOME_NLU_FALLBACK_TIMEOUT_MS", 800)
        self.max_retry = max_retry if max_retry is not None else _env_int("SMARTHOME_NLU_FALLBACK_MAX_RETRY", 1)
        self.temperature = (
            temperature if temperature is not None else _env_float("SMARTHOME_NLU_FALLBACK_TEMPERATURE", 0.1)
        )
        self.num_ctx = num_ctx if num_ctx is not None else _env_int("SMARTHOME_NLU_FALLBACK_NUM_CTX", 1024)
        self.keep_alive = (os.getenv("SMARTHOME_NLU_FALLBACK_KEEP_ALIVE") or "5m").strip()
        self.response_format = (os.getenv("SMARTHOME_NLU_FALLBACK_FORMAT") or "json").strip()
        self.local_fallback = local_fallback or NluFallback()
        self._logger = get_logger("nlu_fallback_qwen")
        self._logger.info(
            "fallback init url=%s model=%s timeout_ms=%s retries=%s",
            self.url,
            self.model,
            self.timeout_ms,
            self.max_retry,
        )

    def predict(self, text: str, context: Dict[str, Any] | None = None) -> IntentJson:
        context = context or {}
        attempts = max(0, int(self.max_retry)) + 1
        self._logger.debug("predict start text=%s attempts=%s", text, attempts)

        for _ in range(attempts):
            try:
                response = self._request_remote(text, context)
                parsed = self._parse_ollama_response(response)
                self._logger.debug("predict remote_ok parsed=%s", compact(parsed, max_len=800))
                return self._intent_from_payload(parsed)
            except Exception:
                self._logger.warning("predict remote_failed; trying next attempt")
                continue

        # 远程兜底失败时，保证行为可用
        self._logger.warning("predict fallback_to_rule text=%s", text)
        return self.local_fallback.predict(text, context)

    def _request_remote(self, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        timeout = max(1, self.timeout_ms) / 1000.0
        payload = self._build_payload(text, context)
        self._logger.debug("request_remote url=%s timeout=%.3f payload=%s", self.url, timeout, compact(payload, max_len=1200))
        # Ignore global proxy envs (e.g. socks://...) to keep LAN Ollama calls stable.
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.post(self.url, json=payload)
            resp.raise_for_status()
            return dict(resp.json())

    def _build_payload(self, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = (
            "你是智能家居 NLU 兜底模型。"
            "只输出 JSON，不要输出解释。"
            "字段必须包含 intent, sub_intent, slots, confidence。"
            "intent 仅允许 CONTROL, QUERY, SCENE, SYSTEM, CHITCHAT。"
            "confidence 为 0~1 的小数。"
        )

        user_payload = {
            "text": text,
            "context": {
                "last_intent": context.get("last_intent"),
                "last_device_type": context.get("last_device_type"),
                "last_location": context.get("last_location"),
            },
            "output_schema": {
                "intent": "string",
                "sub_intent": "string",
                "slots": "object",
                "confidence": "float(0..1)",
            },
        }

        payload: Dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
            },
        }
        if self.response_format:
            payload["format"] = self.response_format
        return payload

    def _parse_ollama_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        message = response.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = str(message["content"])
        elif isinstance(response.get("response"), str):
            content = str(response["response"])
        else:
            raise ValueError("missing response content")
        return self._parse_json_payload(content)

    def _parse_json_payload(self, content: str) -> Dict[str, Any]:
        text = _clean_json_text(content)

        for candidate in (text, _fix_unquoted_keys(text), _extract_json_object(text) or ""):
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
        raise ValueError("invalid json payload")

    def _intent_from_payload(self, payload: Dict[str, Any]) -> IntentJson:
        intent = str(payload.get("intent", "")).strip().upper()
        sub_intent = str(payload.get("sub_intent", "")).strip()
        slots = _to_slots(payload.get("slots"))
        confidence = _clamp_confidence(payload.get("confidence"), default=0.72)

        if intent:
            if not sub_intent:
                sub_intent = _infer_sub_intent_from_payload(intent, slots, payload)
            return IntentJson(
                intent=intent if intent in {"CONTROL", "QUERY", "SCENE", "SYSTEM", "CHITCHAT"} else "CHITCHAT",
                sub_intent=sub_intent or "unknown",
                slots=slots,
                confidence=confidence,
            )

        # 兼容 command-style 输出（commands/c）
        commands = payload.get("commands")
        if not isinstance(commands, list):
            commands = payload.get("c")
        if isinstance(commands, list) and commands:
            cmd = commands[0] if isinstance(commands[0], dict) else {}
            action = str(cmd.get("action") or cmd.get("a") or "").strip()
            device = cmd.get("device") or cmd.get("d")
            location = cmd.get("location") or cmd.get("l")
            parameters = cmd.get("parameters") or cmd.get("p")
            slots = {}
            if device:
                slots["device_type"] = str(device)
            if location:
                slots["location"] = str(location)
            if isinstance(parameters, dict):
                slots.update(parameters)
            return IntentJson(
                intent="CONTROL",
                sub_intent=_normalize_sub_intent(action),
                slots=slots,
                confidence=confidence,
            )

        raise ValueError("unsupported payload shape")

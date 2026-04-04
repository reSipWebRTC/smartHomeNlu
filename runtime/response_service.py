from __future__ import annotations

from typing import Any, Dict

from .contracts import ExecutionResult


class ResponseService:
    def render(
        self,
        *,
        intent_json: Dict[str, Any],
        execution_result: ExecutionResult | None,
        clarify_text: str | None = None,
    ) -> Dict[str, Any]:
        if clarify_text:
            return {
                "status": "clarify",
                "reply_text": clarify_text,
                "tts_text": clarify_text,
                "intent": intent_json.get("intent", ""),
                "sub_intent": intent_json.get("sub_intent", ""),
            }

        if execution_result is None:
            return {
                "status": "ok",
                "reply_text": "好的。",
                "tts_text": "好的。",
                "intent": intent_json.get("intent", ""),
                "sub_intent": intent_json.get("sub_intent", ""),
            }

        if execution_result.status == "success":
            slots = intent_json.get("slots", {})
            if intent_json.get("sub_intent") == "adjust_brightness":
                value = slots.get("value")
                location = slots.get("location", "")
                return {
                    "status": "ok",
                    "reply_text": f"已将{location}灯亮度调到{value}%" if value is not None else "已调整灯光亮度",
                    "tts_text": f"已将{location}灯亮度调到{value}%" if value is not None else "已调整灯光亮度",
                    "intent": intent_json.get("intent", ""),
                    "sub_intent": intent_json.get("sub_intent", ""),
                    "idempotent_hit": execution_result.deduplicated,
                }
            return {
                "status": "ok",
                "reply_text": "指令已执行",
                "tts_text": "指令已执行",
                "intent": intent_json.get("intent", ""),
                "sub_intent": intent_json.get("sub_intent", ""),
                "idempotent_hit": execution_result.deduplicated,
            }

        error_reply_map = {
            "FORBIDDEN": "当前账号没有该操作权限。",
            "ENTITY_NOT_FOUND": "没有找到目标设备，请确认设备名称。",
            "NOT_FOUND": "没有找到对应资源，请确认目标是否存在。",
            "CONFLICT": "当前资源状态冲突，请稍后重试。",
            "BAD_REQUEST": "请求参数有误，请检查后重试。",
        }
        reply = error_reply_map.get(execution_result.error_code or "", "操作失败，已记录错误。")

        return {
            "status": "failed",
            "reply_text": reply,
            "tts_text": reply,
            "intent": intent_json.get("intent", ""),
            "sub_intent": intent_json.get("sub_intent", ""),
            "idempotent_hit": execution_result.deduplicated,
        }

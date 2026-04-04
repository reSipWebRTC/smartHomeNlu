from __future__ import annotations

from runtime.contracts import ExecutionResult
from runtime.response_service import ResponseService


def _failed_result(error_code: str) -> ExecutionResult:
    return ExecutionResult(
        status="failure",
        tool_name="ha_call_service",
        entity_id="light.demo",
        latency_ms=10,
        error_code=error_code,
        upstream_status_code=400,
    )


def test_render_failure_reply_for_bad_request() -> None:
    service = ResponseService()
    payload = service.render(
        intent_json={"intent": "CONTROL", "sub_intent": "power_on", "slots": {}},
        execution_result=_failed_result("BAD_REQUEST"),
    )
    assert payload["status"] == "failed"
    assert payload["reply_text"] == "请求参数有误，请检查后重试。"


def test_render_failure_reply_for_not_found() -> None:
    service = ResponseService()
    payload = service.render(
        intent_json={"intent": "QUERY", "sub_intent": "query_status", "slots": {}},
        execution_result=_failed_result("NOT_FOUND"),
    )
    assert payload["status"] == "failed"
    assert payload["reply_text"] == "没有找到对应资源，请确认目标是否存在。"


def test_render_failure_reply_for_conflict() -> None:
    service = ResponseService()
    payload = service.render(
        intent_json={"intent": "CONTROL", "sub_intent": "unlock", "slots": {}},
        execution_result=_failed_result("CONFLICT"),
    )
    assert payload["status"] == "failed"
    assert payload["reply_text"] == "当前资源状态冲突，请稍后重试。"


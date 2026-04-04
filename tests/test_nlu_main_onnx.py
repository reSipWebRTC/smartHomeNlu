from __future__ import annotations

from runtime.nlu_main_onnx import NluMainOnnx


def test_nlu_main_onnx_falls_back_to_rule_when_model_missing() -> None:
    model = NluMainOnnx(model_path="/tmp/does_not_exist_tinybert.onnx")
    intent = model.predict("打开客厅灯")

    assert model.enabled is False
    assert model.model_version == "nlu-main-rule-v1"
    assert intent.intent == "CONTROL"
    assert intent.sub_intent == "power_on"
    assert intent.slots.get("device_type") == "灯"


def test_nlu_main_onnx_infer_sub_intent_helper() -> None:
    assert NluMainOnnx._infer_sub_intent("CONTROL", "关闭卧室灯", {}) == "power_off"
    assert NluMainOnnx._infer_sub_intent("QUERY", "客厅空调状态", {}) == "query_status"

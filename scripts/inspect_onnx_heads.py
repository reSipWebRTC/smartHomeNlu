#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect ONNX model inputs/outputs for NLU head mapping.")
    parser.add_argument("--model", required=True, help="Path to ONNX model file")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        raise SystemExit(f"model not found: {model_path}")

    try:
        import onnxruntime as ort  # type: ignore
    except Exception as exc:
        raise SystemExit(f"onnxruntime import failed: {exc}") from exc

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    inputs = [
        {
            "name": i.name,
            "type": i.type,
            "shape": i.shape,
        }
        for i in session.get_inputs()
    ]
    outputs = [
        {
            "name": o.name,
            "type": o.type,
            "shape": o.shape,
        }
        for o in session.get_outputs()
    ]

    print("== ONNX Model ==")
    print(model_path)
    print("\n== Inputs ==")
    print(json.dumps(inputs, ensure_ascii=False, indent=2))
    print("\n== Outputs ==")
    print(json.dumps(outputs, ensure_ascii=False, indent=2))

    print("\n== Suggested env mapping ==")
    if outputs:
        print("# Replace output names below with your real NLU heads")
        print(f'export SMARTHOME_NLU_MAIN_MODEL_PATH="{model_path}"')
        print('export SMARTHOME_NLU_MAIN_PROVIDER="onnx"')
        print('export SMARTHOME_NLU_MAIN_INTENT_OUTPUT="<intent_logits_output_name>"')
        print('export SMARTHOME_NLU_MAIN_SUB_INTENT_OUTPUT="<sub_intent_logits_output_name>"')
        print('export SMARTHOME_NLU_MAIN_SLOT_OUTPUT="<slot_logits_output_name>"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

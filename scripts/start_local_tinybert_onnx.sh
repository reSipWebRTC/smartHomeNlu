#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${ROOT_DIR}/.runtime_local/models/tinybert_nlu_multitask_v1"

export SMARTHOME_NLU_MAIN_PROVIDER="onnx"
export SMARTHOME_NLU_MAIN_MODEL_PATH="${MODEL_DIR}/model.onnx"
export SMARTHOME_NLU_MAIN_LABEL_PATH="${MODEL_DIR}/labels.json"
export SMARTHOME_NLU_MAIN_VOCAB_PATH="${MODEL_DIR}/vocab.txt"

# 兜底路：远程 Qwen2.5-1.5B（Mac mini）
export SMARTHOME_NLU_FALLBACK_PROVIDER="qwen_remote"
export SMARTHOME_NLU_FALLBACK_URL="${SMARTHOME_NLU_FALLBACK_URL:-http://192.168.3.44:11434/api/chat}"
export SMARTHOME_NLU_FALLBACK_MODEL="${SMARTHOME_NLU_FALLBACK_MODEL:-qwen2.5:1.5b}"

cd "${ROOT_DIR}"
./run_local.sh down
./run_local.sh up

echo "[OK] Runtime started with TinyBERT ONNX main config"

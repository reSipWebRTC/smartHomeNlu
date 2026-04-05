# 主路 v1 ONNX + 兜底远程 Qwen 实施流程

## 1. 目标
在当前工程落地双路 NLU：
- 主路：本机 `TinyBERT 多头 v1 ONNX`
- 兜底：远程 `Qwen2.5-1.5B`（Mac mini，`192.168.3.44`）

目标效果：高频指令走低延迟主路，低置信指令自动切换远程兜底，统一输出结构化 `intent_json`。

## 2. 架构与关键文件
- 路由：`runtime/nlu_router.py`
- 主路 ONNX：`runtime/nlu_main_onnx.py`
- 兜底 Qwen：`runtime/nlu_fallback_qwen.py`
- 调试接口：`POST /api/v1/nlu/parse`（`runtime/api_gateway.py` + `runtime/server.py`）
- 一键启动脚本：`scripts/start_local_tinybert_onnx.sh`

默认阈值（代码内）：
- `main_pass=0.85`
- `fallback_trigger=0.60`
- `clarify_trigger=0.65`

## 3. 前置条件
1. 本机已创建 `.venv` 并安装依赖：
```bash
pip install -r requirements.txt
```
2. Mac mini 已启动 Ollama + 模型：`qwen2.5:1.5b`
3. 网络可达 `http://192.168.3.44:11434`

远程可达性检查（本机执行）：
```bash
curl -sS http://192.168.3.44:11434/api/tags
```

## 4. 步骤 A：准备主路 v1 ONNX（如已存在可跳过）
生成 seed 语料：
```bash
python3 scripts/build_seed_corpus_v1.py
```

训练并导出 v1 多头 ONNX：
```bash
PYTHONPATH=. .venv/bin/python scripts/train_export_multitask_nlu_onnx.py
```

预期产物：
- `.runtime_local/models/tinybert_nlu_multitask_v1/model.onnx`
- `.runtime_local/models/tinybert_nlu_multitask_v1/labels.json`
- `.runtime_local/models/tinybert_nlu_multitask_v1/vocab.txt`

检查 ONNX 头：
```bash
PYTHONPATH=. .venv/bin/python scripts/inspect_onnx_heads.py \
  --model .runtime_local/models/tinybert_nlu_multitask_v1/model.onnx
```
应看到输出头：`intent_logits`、`sub_intent_logits`、`slot_logits`。

## 5. 步骤 B：启动双路 NLU
使用现成脚本启动（已默认指向 v1 + 远程 Qwen）：
```bash
bash scripts/start_local_tinybert_onnx.sh
```

脚本会设置：
- `SMARTHOME_NLU_MAIN_PROVIDER=onnx`
- `SMARTHOME_NLU_MAIN_MODEL_PATH=.runtime_local/models/tinybert_nlu_multitask_v1/model.onnx`
- `SMARTHOME_NLU_FALLBACK_PROVIDER=qwen_remote`
- `SMARTHOME_NLU_FALLBACK_URL=http://192.168.3.44:11434/api/chat`
- `SMARTHOME_NLU_FALLBACK_MODEL=qwen2.5:1.5b`

## 6. 步骤 C：验收（必须做）
1. 健康检查：
```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

2. NLU 主路验证：
```bash
curl -sS http://127.0.0.1:8000/api/v1/nlu/parse \
  -H 'Content-Type: application/json' \
  -d '{"text":"把客厅灯调到50%"}'
```
检查返回：
- `code=OK`
- `data.route=main`
- `data.model_version=nlu-main-onnx-v1`

3. 兜底链路验证（强制触发 fallback）：
```bash
curl -sS http://127.0.0.1:8000/api/v1/nlu/parse \
  -H 'Content-Type: application/json' \
  -d '{
    "text":"帮我处理这个",
    "threshold":{"main_pass":1.1,"fallback_trigger":1.05,"clarify_trigger":0.65}
  }'
```
检查返回：`data.route=fallback`。

4. 回归测试：
```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_nlu_fallback_qwen.py \
  tests/test_nlu_main_onnx.py \
  tests/test_fastapi_server.py
```

## 7. 运维与回滚
- 临时关闭远程兜底（只走规则 fallback）：
```bash
export SMARTHOME_NLU_FALLBACK_PROVIDER=rule
```
- 主路 ONNX 不可用时，系统会自动回退到规则主路（`model_version` 会变成 `nlu-main-rule-v1`）。

## 8. 常见问题
1. 返回 `nlu-main-rule-v1`：ONNX 文件路径、labels、vocab 或 `onnxruntime` 依赖异常。
2. fallback 一直超时：检查 `192.168.3.44:11434` 联通性和模型是否已拉起。
3. JSON 结构不稳定：Qwen 输出会做一次修复解析，仍失败会回退本地规则兜底。

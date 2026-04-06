from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .contracts import IntentJson
from .debug_log import get_logger
from .nlu_main import NluMain
from .utils import normalize_text


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _softmax(values: List[float]) -> List[float]:
    if not values:
        return []
    m = max(values)
    exps = [pow(2.718281828, v - m) for v in values]
    s = sum(exps)
    if s <= 0:
        return [0.0 for _ in exps]
    return [v / s for v in exps]


def _argmax(values: List[float]) -> Tuple[int, float]:
    if not values:
        return 0, 0.0
    best_idx = 0
    best_val = values[0]
    for i in range(1, len(values)):
        if values[i] > best_val:
            best_idx = i
            best_val = values[i]
    return best_idx, float(best_val)


class NluMainOnnx:
    """
    主路 ONNX 解析器。

    说明：
    - 仅当模型存在且输出包含结构化头（intent/slot logits）时启用 ONNX 预测。
    - 否则自动回退到现有规则主路 NLU，保证链路稳定。
    """

    DEFAULT_INTENT_LABELS = ["CONTROL", "QUERY", "SCENE", "SYSTEM", "CHITCHAT"]

    def __init__(
        self,
        *,
        model_path: str | None = None,
        label_path: str | None = None,
        vocab_path: str | None = None,
        local_fallback: NluMain | None = None,
    ) -> None:
        self.local_fallback = local_fallback or NluMain()
        self._logger = get_logger("nlu_main_onnx")
        self.model_path = (model_path or os.getenv("SMARTHOME_NLU_MAIN_MODEL_PATH") or "").strip()
        self.label_path = (label_path or os.getenv("SMARTHOME_NLU_MAIN_LABEL_PATH") or "").strip()
        self.vocab_path = (vocab_path or os.getenv("SMARTHOME_NLU_MAIN_VOCAB_PATH") or "").strip()

        self.max_seq_len = max(8, _env_int("SMARTHOME_NLU_MAIN_MAX_SEQ_LEN", 64))
        self.intra_threads = _env_int("SMARTHOME_NLU_MAIN_INTRA_THREADS", 2)
        self.inter_threads = _env_int("SMARTHOME_NLU_MAIN_INTER_THREADS", 1)

        self.intent_labels: List[str] = list(self.DEFAULT_INTENT_LABELS)
        self.sub_intent_labels: List[str] = []
        self.slot_labels: List[str] = []

        self.vocab: Dict[str, int] = {}
        self.unk_id = 100
        self.cls_id = 101
        self.sep_id = 102

        self.session: Any | None = None
        self.input_names: List[str] = []
        self.intent_output_name: str | None = (os.getenv("SMARTHOME_NLU_MAIN_INTENT_OUTPUT") or "").strip() or None
        self.sub_intent_output_name: str | None = (os.getenv("SMARTHOME_NLU_MAIN_SUB_INTENT_OUTPUT") or "").strip() or None
        self.slot_output_name: str | None = (os.getenv("SMARTHOME_NLU_MAIN_SLOT_OUTPUT") or "").strip() or None

        self.enabled = False
        self.model_version = "nlu-main-rule-v1"

        self._load_labels()
        self._load_vocab()
        self._try_init_onnx()
        self._logger.info(
            "main_onnx init enabled=%s model_version=%s model_path=%s",
            self.enabled,
            self.model_version,
            self.model_path or "(unset)",
        )

    def predict(self, text: str, context: Dict[str, Any] | None = None) -> IntentJson:
        context = context or {}
        if not self.enabled or self.session is None:
            self._logger.debug("predict fallback_to_rule enabled=%s", self.enabled)
            return self.local_fallback.predict(text, context)

        try:
            inputs, token_chars = self._build_inputs(text)
            raw_outputs = self.session.run(None, inputs)
            output_map: Dict[str, Any] = {}
            for idx, name in enumerate(self._output_names()):
                output_map[name] = raw_outputs[idx]
            parsed = self._intent_from_outputs(text=text, outputs=output_map, token_chars=token_chars)
            if parsed is not None:
                self._logger.debug(
                    "predict onnx_ok intent=%s/%s conf=%.3f",
                    parsed.intent,
                    parsed.sub_intent,
                    float(parsed.confidence),
                )
                return parsed
        except Exception:
            self._logger.warning("predict onnx_failed fallback_to_rule")
            pass

        return self.local_fallback.predict(text, context)

    def _try_init_onnx(self) -> None:
        if not self.model_path:
            return
        model_file = Path(self.model_path)
        if not model_file.exists():
            return

        try:
            import onnxruntime as ort  # type: ignore
        except Exception:
            return

        try:
            sess_opts = ort.SessionOptions()
            sess_opts.intra_op_num_threads = self.intra_threads
            sess_opts.inter_op_num_threads = self.inter_threads
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self.session = ort.InferenceSession(str(model_file), sess_options=sess_opts, providers=["CPUExecutionProvider"])
            self.input_names = [item.name for item in self.session.get_inputs()]
            self._detect_output_heads()
        except Exception:
            self.session = None
            self.input_names = []
            return

        # 只在检测到结构化输出头时启用 ONNX 主路
        if self.intent_output_name or self.slot_output_name or self.sub_intent_output_name:
            self.enabled = True
            self.model_version = "nlu-main-onnx-v1"

    def _output_names(self) -> List[str]:
        if self.session is None:
            return []
        return [item.name for item in self.session.get_outputs()]

    def _detect_output_heads(self) -> None:
        if self.session is None:
            return

        output_items = list(self.session.get_outputs())
        output_names = {item.name for item in output_items}

        # 优先使用显式配置，便于兼容训练导出的任意命名。
        if self.intent_output_name and self.intent_output_name not in output_names:
            self.intent_output_name = None
        if self.sub_intent_output_name and self.sub_intent_output_name not in output_names:
            self.sub_intent_output_name = None
        if self.slot_output_name and self.slot_output_name not in output_names:
            self.slot_output_name = None

        for item in self.session.get_outputs():
            name = item.name
            lname = name.lower()
            dims = len(item.shape or [])
            if self.intent_output_name is None and "intent" in lname and "logit" in lname and dims == 2:
                self.intent_output_name = name
            elif self.sub_intent_output_name is None and "sub" in lname and "intent" in lname and dims == 2:
                self.sub_intent_output_name = name
            elif self.slot_output_name is None and ("slot" in lname or "ner" in lname) and "logit" in lname and dims >= 3:
                self.slot_output_name = name

    def _load_labels(self) -> None:
        if not self.label_path:
            return
        path = Path(self.label_path)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return

        if isinstance(payload.get("intent_labels"), list):
            self.intent_labels = [str(v) for v in payload["intent_labels"]]
        if isinstance(payload.get("sub_intent_labels"), list):
            self.sub_intent_labels = [str(v) for v in payload["sub_intent_labels"]]
        if isinstance(payload.get("slot_labels"), list):
            self.slot_labels = [str(v) for v in payload["slot_labels"]]

    def _load_vocab(self) -> None:
        candidate_paths: List[Path] = []
        if self.vocab_path:
            candidate_paths.append(Path(self.vocab_path))
        if self.model_path:
            model_dir = Path(self.model_path).parent
            candidate_paths.append(model_dir / "vocab.txt")
            candidate_paths.append(model_dir.parent / "vocab.txt")

        vocab_file = next((p for p in candidate_paths if p.exists()), None)
        if vocab_file is None:
            return

        try:
            tokens = vocab_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            return

        self.vocab = {tok.strip(): idx for idx, tok in enumerate(tokens) if tok.strip()}
        if "[UNK]" in self.vocab:
            self.unk_id = self.vocab["[UNK]"]
        if "[CLS]" in self.vocab:
            self.cls_id = self.vocab["[CLS]"]
        if "[SEP]" in self.vocab:
            self.sep_id = self.vocab["[SEP]"]

    def _token_to_id(self, token: str) -> int:
        if not self.vocab:
            # 无词表时给出稳定伪 id，避免崩溃
            return 1000 + (abs(hash(token)) % 30000)
        return self.vocab.get(token, self.unk_id)

    def _build_inputs(self, text: str) -> Tuple[Dict[str, Any], List[str]]:
        try:
            import numpy as np  # type: ignore
        except Exception as exc:
            raise RuntimeError("numpy unavailable for onnx inputs") from exc

        normalized = normalize_text(str(text or ""))
        token_chars = [ch for ch in normalized if not ch.isspace()]
        token_chars = token_chars[: max(1, self.max_seq_len - 2)]

        token_ids = [self.cls_id] + [self._token_to_id(ch) for ch in token_chars] + [self.sep_id]
        seq_len = len(token_ids)

        input_ids = np.array([token_ids], dtype=np.int64)
        attention_mask = np.ones((1, seq_len), dtype=np.int64)
        token_type_ids = np.zeros((1, seq_len), dtype=np.int64)

        feed: Dict[str, Any] = {}
        for name in self.input_names:
            lname = name.lower()
            if "mask" in lname:
                feed[name] = attention_mask
            elif "type" in lname:
                feed[name] = token_type_ids
            else:
                feed[name] = input_ids
        return feed, token_chars

    def _intent_from_outputs(
        self,
        *,
        text: str,
        outputs: Dict[str, Any],
        token_chars: List[str],
    ) -> IntentJson | None:
        intent_label = ""
        sub_intent = ""
        confidence_intent = 0.0

        if self.intent_output_name and self.intent_output_name in outputs:
            logits = self._vector_from_logits(outputs[self.intent_output_name])
            probs = _softmax(logits)
            idx, p = _argmax(probs)
            if self.intent_labels and idx < len(self.intent_labels):
                intent_label = str(self.intent_labels[idx]).strip().upper()
            confidence_intent = p

        if self.sub_intent_output_name and self.sub_intent_output_name in outputs:
            logits = self._vector_from_logits(outputs[self.sub_intent_output_name])
            probs = _softmax(logits)
            idx, _ = _argmax(probs)
            if self.sub_intent_labels and idx < len(self.sub_intent_labels):
                sub_intent = str(self.sub_intent_labels[idx]).strip()

        slots: Dict[str, Any] = {}
        slot_conf = 0.0
        if self.slot_output_name and self.slot_output_name in outputs:
            slots, slot_conf = self._decode_slots(outputs[self.slot_output_name], token_chars)

        if not intent_label:
            return None
        if intent_label not in {"CONTROL", "QUERY", "SCENE", "SYSTEM", "CHITCHAT"}:
            intent_label = "CHITCHAT"

        if not sub_intent:
            sub_intent = self._infer_sub_intent(intent_label, text, slots)

        if slot_conf > 0:
            confidence = 0.7 * confidence_intent + 0.3 * slot_conf
        else:
            confidence = confidence_intent
        confidence = max(0.0, min(1.0, float(confidence)))

        return IntentJson(
            intent=intent_label,
            sub_intent=sub_intent,
            slots=slots,
            confidence=confidence,
        )

    @staticmethod
    def _vector_from_logits(raw: Any) -> List[float]:
        # 支持 ndarray / list / tuple
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        if isinstance(raw, list) and raw and isinstance(raw[0], list):
            raw = raw[0]
        if not isinstance(raw, list):
            return []
        return [_safe_float(v, 0.0) for v in raw]

    def _decode_slots(self, raw: Any, token_chars: List[str]) -> Tuple[Dict[str, Any], float]:
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        # 期望 shape: [1, seq_len, num_labels]
        if not (isinstance(raw, list) and raw and isinstance(raw[0], list)):
            return {}, 0.0
        seq_logits = raw[0]
        if not (isinstance(seq_logits, list) and seq_logits):
            return {}, 0.0
        if not self.slot_labels:
            return {}, 0.0

        label_at_pos: List[str] = []
        conf_at_pos: List[float] = []
        # 跳过 [CLS] 和 [SEP]
        for idx, vec in enumerate(seq_logits[1 : 1 + len(token_chars)]):
            if not isinstance(vec, list):
                continue
            probs = _softmax([_safe_float(v, 0.0) for v in vec])
            label_idx, conf = _argmax(probs)
            if label_idx >= len(self.slot_labels):
                continue
            label_at_pos.append(self.slot_labels[label_idx])
            conf_at_pos.append(conf)

        slots: Dict[str, Any] = {}
        spans: Dict[str, List[str]] = {}
        current_key = ""
        current_chars: List[str] = []

        def flush() -> None:
            nonlocal current_key, current_chars
            if current_key and current_chars:
                spans.setdefault(current_key, []).append("".join(current_chars))
            current_key = ""
            current_chars = []

        for ch, raw_label in zip(token_chars, label_at_pos):
            label = str(raw_label).strip()
            upper = label.upper()
            if upper == "O" or not label:
                flush()
                continue
            if "-" in label:
                prefix, key = label.split("-", 1)
            else:
                prefix, key = "B", label
            key = key.strip().lower()
            prefix = prefix.strip().upper()
            if prefix == "B" or key != current_key:
                flush()
                current_key = key
                current_chars = [ch]
            else:
                current_chars.append(ch)
        flush()

        for key, values in spans.items():
            if not values:
                continue
            value = values[0]
            if "loc" in key:
                slots["location"] = value
            elif "device" in key:
                slots["device_type"] = value
            elif "scene" in key:
                slots["scene_name"] = value
            elif "attr" in key:
                slots["attribute"] = value
            elif "value" in key:
                slots["value"] = value
            else:
                slots[key] = value

        avg_conf = sum(conf_at_pos) / len(conf_at_pos) if conf_at_pos else 0.0
        return slots, float(avg_conf)

    @staticmethod
    def _infer_sub_intent(intent: str, text: str, slots: Dict[str, Any]) -> str:
        raw = str(text or "")
        if intent == "SYSTEM" and "备份" in raw:
            return "backup"
        if intent == "SCENE":
            return "activate_scene"
        if intent == "QUERY":
            return "query_status"
        if intent == "CONTROL":
            if "解锁" in raw or "开锁" in raw:
                return "unlock"
            if "亮度" in raw or "%" in raw:
                return "adjust_brightness"
            if "温度" in raw:
                return "set_temperature"
            if any(k in raw for k in ("关掉", "关闭", "关上")):
                return "power_off"
            if any(k in raw for k in ("打开", "开启")):
                return "power_on"
        if intent == "CHITCHAT":
            return "chitchat"
        return "unknown"

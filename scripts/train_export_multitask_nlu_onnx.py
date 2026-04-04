#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


INTENT_LABELS = ["CONTROL", "QUERY", "SCENE", "SYSTEM", "CHITCHAT"]
SUB_INTENT_LABELS = [
    "power_on",
    "power_off",
    "adjust_brightness",
    "set_temperature",
    "query_status",
    "unlock",
    "backup",
    "activate_scene",
    "chitchat",
    "unknown",
]
SLOT_LABELS = [
    "O",
    "B-location",
    "I-location",
    "B-device_type",
    "I-device_type",
    "B-value",
    "I-value",
    "B-attribute",
    "I-attribute",
    "B-scene_name",
    "I-scene_name",
]

INTENT2ID = {k: i for i, k in enumerate(INTENT_LABELS)}
SUB2ID = {k: i for i, k in enumerate(SUB_INTENT_LABELS)}
SLOT2ID = {k: i for i, k in enumerate(SLOT_LABELS)}

LOCATIONS = ["客厅", "卧室", "书房", "厨房", "阳台", "儿童房", "主卧"]
DEVICES = ["灯", "空调", "开关", "插座", "门锁"]
SCENES = ["观影模式", "睡眠模式", "离家模式", "回家模式"]
CHAT_TEXTS = [
    "你好",
    "谢谢你",
    "今天天气怎么样",
    "讲个笑话",
    "再见",
]


@dataclass
class Sample:
    text: str
    intent: str
    sub_intent: str
    slots: Dict[str, str]


def load_seed_corpus(path: Path) -> Tuple[List[Sample], int]:
    if not path.exists():
        return [], 0
    rows = 0
    samples: List[Sample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        rows += 1
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        text = str(item.get("text", "")).strip()
        intent = str(item.get("intent", "")).strip().upper()
        sub_intent = str(item.get("sub_intent", "")).strip()
        slots_raw = item.get("slots", {})
        slots: Dict[str, str] = {}
        if isinstance(slots_raw, dict):
            for key, value in slots_raw.items():
                if value is None:
                    continue
                slots[str(key)] = str(value).strip()

        if not text or intent not in INTENT2ID or sub_intent not in SUB2ID:
            continue
        samples.append(Sample(text=text, intent=intent, sub_intent=sub_intent, slots=slots))
    skipped = max(0, rows - len(samples))
    return samples, skipped


def _mark_slot(tags: List[str], text: str, value: str, slot_key: str) -> None:
    if not value:
        return
    pos = text.find(value)
    if pos < 0:
        return
    tags[pos] = f"B-{slot_key}"
    for i in range(pos + 1, pos + len(value)):
        if 0 <= i < len(tags):
            tags[i] = f"I-{slot_key}"


def _to_slot_tags(text: str, slots: Dict[str, str]) -> List[str]:
    tags = ["O"] * len(text)
    for key in ("location", "device_type", "value", "attribute", "scene_name"):
        value = slots.get(key, "")
        _mark_slot(tags, text, value, key)
    return tags


def _gen_control_on() -> Sample:
    loc = random.choice(LOCATIONS)
    dev = random.choice(["灯", "开关", "插座"])
    txt = random.choice(
        [
            f"打开{loc}{dev}",
            f"开启{loc}的{dev}",
            f"把{loc}{dev}打开",
        ]
    )
    return Sample(txt, "CONTROL", "power_on", {"location": loc, "device_type": dev})


def _gen_control_off() -> Sample:
    loc = random.choice(LOCATIONS)
    dev = random.choice(["灯", "开关", "插座"])
    txt = random.choice(
        [
            f"关闭{loc}{dev}",
            f"关掉{loc}的{dev}",
            f"把{loc}{dev}关上",
        ]
    )
    return Sample(txt, "CONTROL", "power_off", {"location": loc, "device_type": dev})


def _gen_brightness() -> Sample:
    loc = random.choice(LOCATIONS)
    val = str(random.choice([20, 30, 40, 50, 60, 70, 80]))
    txt = random.choice(
        [
            f"把{loc}灯亮度调到{val}%",
            f"{loc}灯调成{val}%",
            f"将{loc}的灯亮度设置为{val}%",
        ]
    )
    return Sample(
        txt,
        "CONTROL",
        "adjust_brightness",
        {"location": loc, "device_type": "灯", "attribute": "亮度", "value": val},
    )


def _gen_temperature() -> Sample:
    loc = random.choice(LOCATIONS)
    val = str(random.choice([22, 23, 24, 25, 26, 27]))
    txt = random.choice(
        [
            f"把{loc}空调温度调到{val}度",
            f"{loc}空调设置{val}度",
            f"将{loc}的空调温度设为{val}度",
        ]
    )
    return Sample(
        txt,
        "CONTROL",
        "set_temperature",
        {"location": loc, "device_type": "空调", "attribute": "温度", "value": val},
    )


def _gen_query() -> Sample:
    loc = random.choice(LOCATIONS)
    dev = random.choice(["空调", "灯", "门锁", "插座"])
    txt = random.choice(
        [
            f"查询{loc}{dev}状态",
            f"{loc}{dev}现在怎么样",
            f"{loc}的{dev}状态是多少",
        ]
    )
    return Sample(txt, "QUERY", "query_status", {"location": loc, "device_type": dev})


def _gen_unlock() -> Sample:
    loc = random.choice(["前门", "大门", "入户门"])
    txt = random.choice([f"把{loc}解锁", f"开锁{loc}", f"打开{loc}门锁"])
    return Sample(txt, "CONTROL", "unlock", {"location": loc, "device_type": "门锁"})


def _gen_scene() -> Sample:
    scene = random.choice(SCENES)
    txt = random.choice([f"打开{scene}", f"开启{scene}", f"切换到{scene}"])
    return Sample(txt, "SCENE", "activate_scene", {"scene_name": scene})


def _gen_backup() -> Sample:
    txt = random.choice(["备份一下HA", "执行系统备份", "现在开始备份"])
    return Sample(txt, "SYSTEM", "backup", {})


def _gen_chat() -> Sample:
    txt = random.choice(CHAT_TEXTS)
    return Sample(txt, "CHITCHAT", "chitchat", {})


def _gen_unknown() -> Sample:
    txt = random.choice(["这个弄一下", "帮我处理这个", "随便来一个"])
    return Sample(txt, "CHITCHAT", "unknown", {})


def build_dataset(n: int, seed: int) -> List[Sample]:
    random.seed(seed)
    builders = [
        _gen_control_on,
        _gen_control_off,
        _gen_brightness,
        _gen_temperature,
        _gen_query,
        _gen_unlock,
        _gen_scene,
        _gen_backup,
        _gen_chat,
        _gen_unknown,
    ]
    data: List[Sample] = []
    for _ in range(n):
        fn = random.choice(builders)
        data.append(fn())
    return data


def build_vocab(samples: Sequence[Sample]) -> Dict[str, int]:
    chars = set()
    for s in samples:
        chars.update(c for c in s.text if c.strip())

    vocab: Dict[str, int] = {"[PAD]": 0, "[UNK]": 100, "[CLS]": 101, "[SEP]": 102}
    idx = 103
    for ch in sorted(chars):
        if ch in vocab:
            continue
        vocab[ch] = idx
        idx += 1
    return vocab


def encode_sample(sample: Sample, vocab: Dict[str, int], max_len: int) -> Tuple[List[int], List[int], int, int]:
    chars = [c for c in sample.text if c.strip()]
    chars = chars[: max_len - 2]

    ids = [vocab["[CLS]"]] + [vocab.get(c, vocab["[UNK]"]) for c in chars] + [vocab["[SEP]"]]
    mask = [1] * len(ids)
    slot_tags = _to_slot_tags("".join(chars), sample.slots)
    slot_ids = [SLOT2ID["O"]] + [SLOT2ID.get(t, SLOT2ID["O"]) for t in slot_tags] + [SLOT2ID["O"]]

    while len(ids) < max_len:
        ids.append(vocab["[PAD]"])
        mask.append(0)
        slot_ids.append(-100)

    return ids, slot_ids, INTENT2ID[sample.intent], SUB2ID[sample.sub_intent]


class TinyMultiTaskNLU(nn.Module):
    def __init__(self, vocab_size: int, emb_dim: int, hidden_dim: int, n_intent: int, n_sub: int, n_slot: int) -> None:
        super().__init__()
        self.emb = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.encoder = nn.LSTM(
            input_size=emb_dim,
            hidden_size=hidden_dim,
            num_layers=1,
            batch_first=True,
            bidirectional=True,
        )
        self.intent_head = nn.Linear(hidden_dim * 2, n_intent)
        self.sub_head = nn.Linear(hidden_dim * 2, n_sub)
        self.slot_head = nn.Linear(hidden_dim * 2, n_slot)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor, token_type_ids: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        _ = token_type_ids
        x = self.emb(input_ids)
        seq_out, _ = self.encoder(x)

        mask = attention_mask.unsqueeze(-1).float()
        masked = seq_out * mask
        denom = mask.sum(dim=1).clamp(min=1.0)
        pooled = masked.sum(dim=1) / denom

        intent_logits = self.intent_head(pooled)
        sub_logits = self.sub_head(pooled)
        slot_logits = self.slot_head(seq_out)
        return intent_logits, sub_logits, slot_logits


def train_model(samples: Sequence[Sample], vocab: Dict[str, int], max_len: int, epochs: int, batch_size: int, lr: float, seed: int) -> TinyMultiTaskNLU:
    torch.manual_seed(seed)
    random.seed(seed)

    xs: List[List[int]] = []
    ms: List[List[int]] = []
    ts: List[List[int]] = []
    yi: List[int] = []
    ys: List[int] = []
    for s in samples:
        input_ids, slot_ids, intent_id, sub_id = encode_sample(s, vocab, max_len)
        xs.append(input_ids)
        ms.append([1 if v != 0 else 0 for v in input_ids])
        ts.append([0] * max_len)
        yi.append(intent_id)
        ys.append(sub_id)

    x = torch.tensor(xs, dtype=torch.long)
    m = torch.tensor(ms, dtype=torch.long)
    t = torch.tensor(ts, dtype=torch.long)
    y_intent = torch.tensor(yi, dtype=torch.long)
    y_sub = torch.tensor(ys, dtype=torch.long)
    y_slot = torch.tensor(ts, dtype=torch.long)

    # replace with true slot ids
    for i, s in enumerate(samples):
        _, slot_ids, _, _ = encode_sample(s, vocab, max_len)
        y_slot[i] = torch.tensor(slot_ids, dtype=torch.long)

    model = TinyMultiTaskNLU(
        vocab_size=max(vocab.values()) + 1,
        emb_dim=64,
        hidden_dim=64,
        n_intent=len(INTENT_LABELS),
        n_sub=len(SUB_INTENT_LABELS),
        n_slot=len(SLOT_LABELS),
    )
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    model.train()
    n = x.size(0)
    for ep in range(epochs):
        perm = torch.randperm(n)
        total_loss = 0.0
        for i in range(0, n, batch_size):
            idx = perm[i : i + batch_size]
            bx, bm, bt = x[idx], m[idx], t[idx]
            bi, bs, bslot = y_intent[idx], y_sub[idx], y_slot[idx]
            intent_logits, sub_logits, slot_logits = model(bx, bm, bt)
            loss_i = F.cross_entropy(intent_logits, bi)
            loss_s = F.cross_entropy(sub_logits, bs)
            loss_slot = F.cross_entropy(slot_logits.view(-1, slot_logits.size(-1)), bslot.view(-1), ignore_index=-100)
            loss = loss_i + loss_s + loss_slot
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += float(loss.item()) * bx.size(0)
        avg_loss = total_loss / max(1, n)
        print(f"epoch={ep+1}/{epochs} loss={avg_loss:.4f}")

    model.eval()
    with torch.no_grad():
        li, ls, _ = model(x, m, t)
        pred_i = li.argmax(dim=-1)
        pred_s = ls.argmax(dim=-1)
        acc_i = (pred_i == y_intent).float().mean().item()
        acc_s = (pred_s == y_sub).float().mean().item()
        print(f"train_intent_acc={acc_i:.4f} train_sub_intent_acc={acc_s:.4f}")
    return model


def export_onnx(model: TinyMultiTaskNLU, out_path: Path, max_len: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dummy_ids = torch.zeros((1, max_len), dtype=torch.long)
    dummy_mask = torch.ones((1, max_len), dtype=torch.long)
    dummy_type = torch.zeros((1, max_len), dtype=torch.long)
    torch.onnx.export(
        model,
        (dummy_ids, dummy_mask, dummy_type),
        str(out_path),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["intent_logits", "sub_intent_logits", "slot_logits"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "token_type_ids": {0: "batch_size", 1: "sequence_length"},
            "slot_logits": {0: "batch_size", 1: "sequence_length"},
        },
        opset_version=17,
    )


def save_assets(out_dir: Path, vocab: Dict[str, int]) -> None:
    labels = {
        "intent_labels": INTENT_LABELS,
        "sub_intent_labels": SUB_INTENT_LABELS,
        "slot_labels": SLOT_LABELS,
    }
    (out_dir / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")

    inv = {idx: tok for tok, idx in vocab.items()}
    max_idx = max(inv) if inv else 0
    vocab_lines: List[str] = []
    for i in range(max_idx + 1):
        vocab_lines.append(inv.get(i, f"[UNUSED_{i}]"))
    (out_dir / "vocab.txt").write_text("\n".join(vocab_lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and export a multi-head NLU ONNX model (v1).")
    parser.add_argument("--out-dir", default=".runtime_local/models/tinybert_nlu_multitask_v1")
    parser.add_argument("--samples", type=int, default=2400)
    parser.add_argument("--seed-corpus", default="data/nlu_seed_v1.jsonl")
    parser.add_argument("--seed-repeat", type=int, default=12)
    parser.add_argument("--max-len", type=int, default=48)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=2e-3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    synthetic = build_dataset(n=args.samples, seed=args.seed)
    seed_path = Path(args.seed_corpus).resolve()
    seed_samples, skipped = load_seed_corpus(seed_path)

    samples = list(synthetic)
    if seed_samples and args.seed_repeat > 0:
        for _ in range(args.seed_repeat):
            samples.extend(seed_samples)
    random.Random(args.seed).shuffle(samples)

    vocab = build_vocab(samples)
    print(
        "samples_total=%d synthetic=%d seed=%d seed_repeat=%d seed_skipped=%d vocab_size=%d out_dir=%s"
        % (len(samples), len(synthetic), len(seed_samples), args.seed_repeat, skipped, len(vocab), out_dir)
    )

    model = train_model(
        samples=samples,
        vocab=vocab,
        max_len=args.max_len,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
    )
    model_path = out_dir / "model.onnx"
    export_onnx(model, model_path, args.max_len)
    save_assets(out_dir, vocab)
    print(f"exported: {model_path}")
    print(f"exported: {out_dir / 'labels.json'}")
    print(f"exported: {out_dir / 'vocab.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

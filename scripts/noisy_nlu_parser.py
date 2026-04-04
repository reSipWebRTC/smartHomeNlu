#!/usr/bin/env python3
"""
噪声智能家居语音指令解析器
过滤语气词、口吃、脏话，纠正同音错字，解析为结构化指令。
"""

import re
import json
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class SmartHomeCommand:
    intent: str          # turn_on, turn_off, set_temperature, ...
    device: str          # 射灯, 窗帘, 新风系统, 灯, ...
    location: Optional[str] = None   # 二楼, 客厅, 小孩房间, 厨房, ...
    value: Optional[str] = None      # 26, 30, ...
    raw: str = ""        # 原始片段
    cleaned: str = ""    # 清洗后文本


# ── 脏话词典 ──
PROFANITY_PATTERNS = [
    r"他妈的?", r"你妈的?", r"tmd", r"tm(?=小孩|房间|温度)",
    r"操你?", r"卧槽", r"我靠",
]
# ── 语气词 / 口吃模式 ──
FILLER_PATTERNS = [
    (r"(啊+)", ""),          # 啊啊啊
    (r"(嗯+)", ""),          # 嗯嗯
    (r"(哦+)", ""),          # 哦哦
    (r"(呃|额|俄|阿)", ""),   # 填充词
    (r"(的){2,}", ""),        # 的的的
    (r"吧(?=[，。；]|$)", ""), # 句末语气词"吧"
]

# ── 同音错字纠错表 ──
HOMOPHONE_CORRECTIONS = {
    "窗连": "窗帘",
    "窗链": "窗帘",
    "窗廉": "窗帘",
    "社等": "射灯",
    "设等": "射灯",
    "森环系统": "新风系统",
    "声环系统": "新风系统",
    "生还的系统": "新风系统",  # 极度模糊，按上下文猜测
    "声还的系统": "新风系统",
    "新风系统": "新风系统",    # 正确写法也收录，保持幂等
}

# ── 设备关键词 ──
DEVICE_KEYWORDS = [
    "新风系统", "射灯", "窗帘", "灯", "空调", "加湿器",
    "电视", "音响", "净水器", "热水器", "扫地机", "暖风机",
]

# ── 位置关键词 ──
LOCATION_KEYWORDS = [
    "小孩房间", "小孩房", "儿童房", "主卧", "次卧", "卧室",
    "客厅", "厨房", "卫生间", "浴室", "阳台", "书房", "餐厅",
    "一楼", "二楼", "三楼", "四楼", "地下室",
]

# ── 意图关键词 ──
INTENT_OPEN = {"打开", "开启", "开", "启动"}
INTENT_CLOSE = {"关闭", "关掉", "关", "合上", "合"}
INTENT_SET_TEMP = {"调为", "调到", "设为", "设置", "调成"}


def filter_profanity(text: str) -> str:
    """移除脏话"""
    for p in PROFANITY_PATTERNS:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    return text


def filter_fillers(text: str) -> str:
    """移除语气词和口吃"""
    for pattern, repl in FILLER_PATTERNS:
        text = re.sub(pattern, repl, text)
    # 清理多余空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


def correct_homophones(text: str) -> str:
    """纠正同音错字"""
    for wrong, correct in HOMOPHONE_CORRECTIONS.items():
        text = text.replace(wrong, correct)
    return text


def remove_stray_de(text: str) -> str:
    """移除口吃残留的单个"的"（如"打开的射灯" → "打开射灯"）"""
    # 动词后的单个"的"是口吃残留，删掉
    verbs = "|".join(re.escape(v) for v in (INTENT_OPEN | INTENT_CLOSE))
    text = re.sub(rf"({verbs})的", r"\1", text)
    # "的"出现在设备名前也是口吃残留（如"的射灯"→"射灯"）
    devices = "|".join(re.escape(d) for d in DEVICE_KEYWORDS if d != "灯")
    text = re.sub(rf"的({devices})", r"\1", text)
    return text


def clean_text(raw: str) -> str:
    """完整清洗流水线"""
    text = filter_profanity(raw)
    text = filter_fillers(text)
    text = remove_stray_de(text)
    text = correct_homophones(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_device(text: str) -> Optional[str]:
    """从文本中提取设备名称"""
    for dev in DEVICE_KEYWORDS:
        if dev in text:
            return dev
    return None


def extract_location(text: str) -> Optional[str]:
    """从文本中提取位置"""
    for loc in LOCATION_KEYWORDS:
        if loc in text:
            return loc
    return None


def extract_temperature(text: str) -> Optional[str]:
    """从文本中提取温度值"""
    m = re.search(r"(\d+)\s*度", text)
    return m.group(1) if m else None


def detect_intent(text: str) -> Optional[str]:
    """检测意图"""
    for kw in INTENT_SET_TEMP:
        if kw in text:
            return "set_temperature"
    for kw in INTENT_OPEN:
        if kw in text:
            return "turn_on"
    for kw in INTENT_CLOSE:
        if kw in text:
            return "turn_off"
    return None


def normalize_verb_order(text: str) -> str:
    """
    归一化语序：处理"位置+设备+动词"的乱序情况
    例如 "三楼射灯打开" → "打开三楼射灯"
    """
    # 检测句尾是否是动词
    all_verbs = INTENT_OPEN | INTENT_CLOSE
    for verb in sorted(all_verbs, key=len, reverse=True):
        if text.endswith(verb):
            # 检查句首是否缺少该动词
            has_open = any(v in text for v in INTENT_OPEN)
            has_close = any(v in text for v in INTENT_CLOSE)
            if not (has_open and has_close):
                # 只有一个动词且在句尾，移到句首
                body = text[: -len(verb)]
                return verb + body
    return text


def split_commands(text: str) -> list[str]:
    """按标点切分多条指令"""
    # 按中文标点和"并且"切分
    parts = re.split(r"[，。；]|并且", text)
    return [p.strip() for p in parts if p.strip()]


def parse_single(raw_segment: str) -> Optional[SmartHomeCommand]:
    """解析单条指令"""
    cleaned = clean_text(raw_segment)
    if not cleaned:
        return None

    # 先归一化语序
    ordered = normalize_verb_order(cleaned)

    intent = detect_intent(ordered)
    if not intent:
        return None

    device = extract_device(ordered)
    location = extract_location(ordered)
    value = extract_temperature(ordered) if intent == "set_temperature" else None

    return SmartHomeCommand(
        intent=intent,
        device=device or "",
        location=location,
        value=value,
        raw=raw_segment.strip(),
        cleaned=cleaned,
    )


def parse(text: str) -> list[SmartHomeCommand]:
    """解析整段语音文本为指令列表"""
    segments = split_commands(text)
    results = []
    for seg in segments:
        cmd = parse_single(seg)
        if cmd and cmd.intent:
            results.append(cmd)
    return results


# ── 测试用例 ──
TEST_CASES = [
    # (原始文本, 预期指令数)
    ("啊啊哦 打开啊啊射灯，打开他妈的的的二楼的啊窗连额，并且把tmd的小孩房间的温度调为26度；打开啊啊客厅的森环系统；打开二楼的社等", 5),
    ("生还的系统打开，啊啊哦打开啊啊的射灯，打开你妈的二楼的啊窗链吧。并且把tm小孩房间的温度调为26度；打开啊啊客厅的森环系统；三楼的阿社等打开", 6),
    ("嗯嗯的的打开厨房灯", 1),
    ("关闭主卧空调，把客厅温度设为22度", 2),
    ("二楼的灯关掉", 1),
]


def run_tests():
    """运行测试用例"""
    print("=" * 60)
    print("智能家居噪声指令解析器 - 测试")
    print("=" * 60)

    all_pass = True
    for i, (text, expected_count) in enumerate(TEST_CASES, 1):
        print(f"\n{'─' * 60}")
        print(f"测试 {i}: {text}")
        print(f"预期指令数: {expected_count}")
        print()

        commands = parse(text)
        actual_count = len(commands)

        for j, cmd in enumerate(commands, 1):
            print(f"  [{j}] raw    : {cmd.raw}")
            print(f"      cleaned: {cmd.cleaned}")
            print(f"      intent : {cmd.intent}")
            print(f"      device : {cmd.device}")
            print(f"      locate : {cmd.location}")
            print(f"      value  : {cmd.value}")
            print()

        passed = actual_count == expected_count
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  结果: {status} (实际 {actual_count} 条)")

    print(f"\n{'=' * 60}")
    print(f"总结: {'全部通过' if all_pass else '存在失败'}")
    print("=" * 60)
    return all_pass


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 交互模式：传入文本直接解析
        text = " ".join(sys.argv[1:])
        commands = parse(text)
        print(json.dumps([asdict(c) for c in commands], ensure_ascii=False, indent=2))
    else:
        # 默认运行测试
        run_tests()

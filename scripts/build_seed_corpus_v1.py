#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


def _row(text: str, intent: str, sub_intent: str, slots: Dict[str, str]) -> Dict[str, object]:
    return {
        "text": text,
        "intent": intent,
        "sub_intent": sub_intent,
        "slots": slots,
    }


def build_rows() -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []

    for loc in ["客厅", "卧室", "书房", "厨房", "阳台", "儿童房", "主卧"]:
        rows.extend(
            [
                _row(f"打开{loc}灯", "CONTROL", "power_on", {"location": loc, "device_type": "灯"}),
                _row(f"关闭{loc}灯", "CONTROL", "power_off", {"location": loc, "device_type": "灯"}),
                _row(f"打开{loc}开关", "CONTROL", "power_on", {"location": loc, "device_type": "开关"}),
                _row(f"关闭{loc}开关", "CONTROL", "power_off", {"location": loc, "device_type": "开关"}),
                _row(f"打开{loc}插座", "CONTROL", "power_on", {"location": loc, "device_type": "插座"}),
                _row(f"关闭{loc}插座", "CONTROL", "power_off", {"location": loc, "device_type": "插座"}),
                _row(f"查询{loc}空调状态", "QUERY", "query_status", {"location": loc, "device_type": "空调"}),
                _row(f"把{loc}灯调到50%", "CONTROL", "adjust_brightness", {"location": loc, "device_type": "灯", "attribute": "亮度", "value": "50"}),
                _row(f"把{loc}空调温度调到26度", "CONTROL", "set_temperature", {"location": loc, "device_type": "空调", "attribute": "温度", "value": "26"}),
            ]
        )

    rows.extend(
        [
            _row("把前门解锁", "CONTROL", "unlock", {"location": "前门", "device_type": "门锁"}),
            _row("打开前门门锁", "CONTROL", "unlock", {"location": "前门", "device_type": "门锁"}),
            _row("开锁入户门", "CONTROL", "unlock", {"location": "入户门", "device_type": "门锁"}),
            _row("备份一下HA", "SYSTEM", "backup", {}),
            _row("执行系统备份", "SYSTEM", "backup", {}),
            _row("现在开始备份", "SYSTEM", "backup", {}),
            _row("打开回家模式", "SCENE", "activate_scene", {"scene_name": "回家模式"}),
            _row("开启观影模式", "SCENE", "activate_scene", {"scene_name": "观影模式"}),
            _row("切换到离家模式", "SCENE", "activate_scene", {"scene_name": "离家模式"}),
            _row("你好", "CHITCHAT", "chitchat", {}),
            _row("谢谢你", "CHITCHAT", "chitchat", {}),
            _row("今天天气怎么样", "CHITCHAT", "chitchat", {}),
            _row("讲个笑话", "CHITCHAT", "chitchat", {}),
            _row("再见", "CHITCHAT", "chitchat", {}),
            _row("这个弄一下", "CHITCHAT", "unknown", {}),
            _row("帮我处理这个", "CHITCHAT", "unknown", {}),
            _row("随便来一个", "CHITCHAT", "unknown", {}),
            _row("打开TYZXl鹊起 延长线插座 None", "CONTROL", "power_on", {"device_type": "插座"}),
            _row("打开TYZXl鹊起 延长线插座 第2路", "CONTROL", "power_on", {"device_type": "插座"}),
            _row("打开TYZXl鹊起 延长线插座 None 第二路", "CONTROL", "power_on", {"device_type": "插座"}),
            _row("把客厅灯调亮", "CONTROL", "adjust_brightness", {"location": "客厅", "device_type": "灯", "attribute": "亮度"}),
            _row("把客厅灯调暗", "CONTROL", "adjust_brightness", {"location": "客厅", "device_type": "灯", "attribute": "亮度"}),
            _row("把空调温度调高", "CONTROL", "set_temperature", {"device_type": "空调", "attribute": "温度"}),
            _row("把空调温度调低", "CONTROL", "set_temperature", {"device_type": "空调", "attribute": "温度"}),
        ]
    )
    return rows


def main() -> int:
    out_path = Path("data/nlu_seed_v1.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

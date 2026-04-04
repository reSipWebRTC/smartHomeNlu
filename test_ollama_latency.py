#!/usr/bin/env python3
"""Test Ollama API latency with various smart home commands."""

import time
import json
import re
import requests
from typing import List, Dict

# Configuration
OLLAMA_URL = "http://192.168.3.44:11434/api/chat"
#MODEL = "smarthome"
MODEL = "smarthome-distilled"
HEADERS = {"Content-Type": "application/json"}

# Key mapping for short format (c/a/d/l/p) to long format
KEY_MAP = {
    "c": "commands",
    "a": "action",
    "d": "device",
    "l": "location",
    "p": "parameters"
}


def fix_json(raw: str) -> str:
    """修复模型常见的 JSON 格式错误"""
    # 修复未加引号的 key：p: {} → "p": {}
    raw = re.sub(r'(\b\w+\b)\s*:', r'"\1":', raw)
    # 去掉重复引号："\"p\"" → "p"
    raw = re.sub(r'""(\w+)""', r'"\1"', raw)
    return raw

# Test cases
TEST_CASES = [
    "打开客厅的灯",
    "关闭卧室的空调",
    "把温度调到26度",
    "打开二楼窗帘",
    "打开客厅的森环系统",
    "关闭射灯",
    "空调温度调高",
    "打开小孩房间的灯",
    "关闭客厅的电视",
    "把湿度调为50%",
    # Complex cases
    "打开客厅灯，关闭卧室空调",
]

# Test with repetitions to check cache effect
REPETITIONS = 3


def call_ollama(content: str) -> Dict:
    """Call Ollama API and return response with timing."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
        "keep_alive": -1
    }

    start = time.perf_counter()
    try:
        response = requests.post(OLLAMA_URL, json=payload, headers=HEADERS, timeout=30)
        elapsed = time.perf_counter() - start

        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "latency_ms": round(elapsed * 1000, 2),
                "response": data.get("message", {}).get("content", ""),
                "prompt_eval_count": data.get("prompt_eval_count", 0),
                "eval_count": data.get("eval_count", 0),
            }
        else:
            return {
                "success": False,
                "latency_ms": round(elapsed * 1000, 2),
                "error": response.text,
            }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "success": False,
            "latency_ms": round(elapsed * 1000, 2),
            "error": str(e),
        }


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f" {text}")
    print(f"{'='*60}")


def parse_commands(response_text: str) -> list:
    """Parse the JSON response and extract commands."""
    # Remove markdown code blocks if present
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]  # Remove ```json
    elif text.startswith("```"):
        text = text[3:]  # Remove ```
    if text.endswith("```"):
        text = text[:-3]  # Remove trailing ```

    text = text.strip()

    # Try to fix common JSON errors before parsing
    text = fix_json(text)

    try:
        data = json.loads(text)
        # Handle both old format (commands) and new format (c)
        commands = data.get("commands", []) or data.get("c", [])
        return commands
    except json.JSONDecodeError as e:
        return [{"raw": f"JSON Error: {e}", "preview": response_text[:100]}]


def normalize_key(cmd: dict, short_key: str, long_key: str) -> str:
    """Get value from command dict, trying both short and long key names."""
    if long_key in cmd:
        return long_key
    if short_key in cmd:
        return short_key
    return None


def format_command(cmd: dict) -> str:
    """Format a single command for display."""
    if "raw" in cmd:
        return cmd["raw"]

    parts = []

    # Find the actual keys in the command (both short and long format)
    action_key = normalize_key(cmd, "a", "action")
    device_key = normalize_key(cmd, "d", "device")
    location_key = normalize_key(cmd, "l", "location")
    params_key = normalize_key(cmd, "p", "parameters")

    action_map = {
        "turn_on": "打开", "turn_off": "关闭", "open": "打开",
        "close": "关闭", "set_temperature": "温度", "set_humidity": "湿度",
        "increase": "调高", "decrease": "调低"
    }

    if action_key:
        action = action_map.get(cmd[action_key], cmd[action_key])
        parts.append(f"动作:{action}")

    if device_key and cmd[device_key]:
        parts.append(f"设备:{cmd[device_key]}")

    if location_key and cmd[location_key]:
        loc = cmd[location_key]
        if loc != "null" and loc is not None:
            parts.append(f"位置:{loc}")

    if params_key and cmd[params_key]:
        params = cmd[params_key]
        if isinstance(params, dict):
            for k, v in params.items():
                if v is not None and v != "null":
                    parts.append(f"{k}:{v}")

    return " ".join(parts) if parts else str(cmd)


def print_result(idx: int, content: str, result: Dict, round_num: int = None):
    prefix = f"[{round_num}] " if round_num else ""
    print(f"\n{prefix}Test {idx}: {content}")

    if result["success"]:
        print(f"  ✓ Latency: {result['latency_ms']:>6} ms")
        if result['prompt_eval_count'] or result['eval_count']:
            print(f"  Tokens: prompt={result['prompt_eval_count']}, output={result['eval_count']}")

        # Parse and display commands
        commands = parse_commands(result['response'])
        if commands:
            print(f"  解析结果 ({len(commands)} 条命令):")
            for i, cmd in enumerate(commands, 1):
                formatted = format_command(cmd)
                print(f"    {i}. {formatted}")
        else:
            print(f"  Response: {result['response'][:100]}...")
    else:
        print(f"  ✗ Latency: {result['latency_ms']:>6} ms")
        print(f"  Error: {result['error']}")


def main():
    print_header("Ollama API Latency Test")
    print(f"URL: {OLLAMA_URL}")
    print(f"Model: {MODEL}")
    print(f"Test cases: {len(TEST_CASES)}")
    print(f"Repetitions: {REPETITIONS}")

    all_results = []

    for round_num in range(1, REPETITIONS + 1):
        print_header(f"Round {round_num}/{REPETITIONS}")

        for idx, content in enumerate(TEST_CASES, 1):
            result = call_ollama(content)
            all_results.append({
                "round": round_num,
                "idx": idx,
                "content": content,
                **result
            })
            print_result(idx, content, result, round_num)
            time.sleep(0.1)  # Small delay between calls

    # Summary
    print_header("Summary Statistics")

    successful = [r for r in all_results if r["success"]]
    failed = [r for r in all_results if not r["success"]]

    print(f"\nTotal requests: {len(all_results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")

    if successful:
        latencies = [r["latency_ms"] for r in successful]
        print(f"\nLatency Statistics:")
        print(f"  Min:    {min(latencies):>6.2f} ms")
        print(f"  Max:    {max(latencies):>6.2f} ms")
        print(f"  Avg:    {sum(latencies)/len(latencies):>6.2f} ms")
        print(f"  Median: {sorted(latencies)[len(latencies)//2]:>6.2f} ms")

    # Per-round breakdown
    print_header("Per-Round Average Latency")
    for round_num in range(1, REPETITIONS + 1):
        round_results = [r for r in successful if r["round"] == round_num]
        if round_results:
            avg = sum(r["latency_ms"] for r in round_results) / len(round_results)
            print(f"  Round {round_num}: {avg:>6.2f} ms (n={len(round_results)})")

    # Cache effect analysis
    if REPETITIONS > 1:
        print_header("Cache Effect Analysis (same content across rounds)")
        for idx, content in enumerate(TEST_CASES, 1):
            content_results = [r for r in all_results if r["idx"] == idx and r["success"]]
            if len(content_results) > 1:
                first_latency = content_results[0]["latency_ms"]
                avg_subsequent = sum(r["latency_ms"] for r in content_results[1:]) / (len(content_results) - 1)
                cache_hit = "✓ CACHE HIT" if avg_subsequent < first_latency * 0.5 else "✗ no cache"
                print(f"  [{idx}] {content[:35]:<35} | 1st: {first_latency:>6}ms | avg: {avg_subsequent:>6.2f}ms | {cache_hit}")

    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()

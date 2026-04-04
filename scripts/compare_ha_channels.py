#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

# Make runtime package importable when executing via:
# `python scripts/compare_ha_channels.py ...`
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime import SmartHomeRuntime
from runtime.ha_gateway_adapter import HaGatewayAdapter
from runtime.ha_mcp_adapter import HaMcpAdapter


@contextmanager
def _without_env(*keys: str) -> Iterator[None]:
    backup: Dict[str, str] = {}
    missing: List[str] = []
    for key in keys:
        if key in os.environ:
            backup[key] = os.environ[key]
            os.environ.pop(key, None)
        else:
            missing.append(key)
    try:
        yield
    finally:
        for key in keys:
            os.environ.pop(key, None)
        for key, value in backup.items():
            os.environ[key] = value
        for key in missing:
            if key not in backup:
                os.environ.pop(key, None)


@dataclass
class ChannelResult:
    channel: str
    adapter_mode: str
    route: Dict[str, Any]
    call_chain: List[Dict[str, Any]]
    response: Dict[str, Any]


def _capture_route(runtime: SmartHomeRuntime) -> Tuple[Dict[str, Any], Any]:
    captured: Dict[str, Any] = {}
    original = runtime.router.route

    def _wrapped_route(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        result = original(*args, **kwargs)
        intent_obj = result.get("intent_json")
        if hasattr(intent_obj, "as_dict"):
            intent_dict = intent_obj.as_dict()
        else:
            intent_dict = {}
        captured.update(
            {
                "route": result.get("route"),
                "need_clarify": bool(result.get("need_clarify", False)),
                "intent": intent_dict.get("intent"),
                "sub_intent": intent_dict.get("sub_intent"),
                "confidence": intent_dict.get("confidence"),
                "threshold": result.get("threshold"),
            }
        )
        return result

    runtime.router.route = _wrapped_route  # type: ignore[assignment]
    return captured, original


def _extract_call_chain(runtime: SmartHomeRuntime) -> List[Dict[str, Any]]:
    events = runtime.event_bus.events("evt.execution.result.v1")
    chain: List[Dict[str, Any]] = []
    for event in events:
        chain.append(
            {
                "tool_name": event.get("tool_name"),
                "status": event.get("status"),
                "error_code": event.get("error_code"),
                "entity_id": event.get("entity_id"),
                "latency_ms": event.get("latency_ms"),
                "attempts": event.get("attempts"),
                "deduplicated": bool(event.get("deduplicated", False)),
            }
        )
    return chain


def _run_channel(channel: str, payload: Dict[str, Any]) -> ChannelResult:
    if channel == "ha_gateway":
        with _without_env("SMARTHOME_HA_GATEWAY_URL", "SMARTHOME_HA_CONTROL_MODE"):
            runtime = SmartHomeRuntime(adapter=HaGatewayAdapter())
    elif channel == "ha_mcp":
        with _without_env("SMARTHOME_HA_MCP_URL", "SMARTHOME_HA_MCP_TOKEN", "SMARTHOME_HA_CONTROL_MODE"):
            runtime = SmartHomeRuntime(adapter=HaMcpAdapter())
    else:
        raise ValueError(f"unsupported channel: {channel}")

    route_capture, original_route = _capture_route(runtime)
    try:
        response = runtime.post_api_v1_command(dict(payload))
    finally:
        runtime.router.route = original_route  # type: ignore[assignment]

    return ChannelResult(
        channel=channel,
        adapter_mode=str(runtime.adapter.mode),
        route=route_capture,
        call_chain=_extract_call_chain(runtime),
        response=response,
    )


def _check_equal(name: str, left: Any, right: Any) -> Dict[str, Any]:
    return {
        "name": name,
        "pass": left == right,
        "left": left,
        "right": right,
    }


def _consistency(gw: ChannelResult, mcp: ChannelResult) -> Dict[str, Any]:
    checks = [
        _check_equal("response.code", gw.response.get("code"), mcp.response.get("code")),
        _check_equal(
            "response.data.status",
            (gw.response.get("data") or {}).get("status"),
            (mcp.response.get("data") or {}).get("status"),
        ),
        _check_equal("route.route", gw.route.get("route"), mcp.route.get("route")),
        _check_equal("route.intent", gw.route.get("intent"), mcp.route.get("intent")),
        _check_equal("route.sub_intent", gw.route.get("sub_intent"), mcp.route.get("sub_intent")),
        _check_equal("call_chain.tool_name", _tool_seq(gw.call_chain), _tool_seq(mcp.call_chain)),
    ]
    return {
        "pass": all(item["pass"] for item in checks),
        "checks": checks,
    }


def _tool_seq(chain: List[Dict[str, Any]]) -> List[str]:
    return [str(item.get("tool_name", "")) for item in chain if item.get("tool_name")]


def _build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "session_id": args.session_id or f"cmp_{int(time.time())}_{uuid.uuid4().hex[:6]}",
        "user_id": args.user_id,
        "text": args.text,
        "user_role": args.user_role,
        "top_k": args.top_k,
    }


def _format_output(payload: Dict[str, Any], gw: ChannelResult, mcp: ChannelResult) -> Dict[str, Any]:
    consistency = _consistency(gw, mcp)
    return {
        "input": payload,
        "channels": {
            "ha_gateway": {
                "adapter_mode": gw.adapter_mode,
                "route": gw.route,
                "call_chain": gw.call_chain,
                "response": gw.response,
            },
            "ha_mcp": {
                "adapter_mode": mcp.adapter_mode,
                "route": mcp.route,
                "call_chain": mcp.call_chain,
                "response": mcp.response,
            },
        },
        "consistency": consistency,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare one intent execution across ha_gateway and ha_mcp channels.",
    )
    parser.add_argument("text", help="Natural-language command to execute.")
    parser.add_argument("--session-id", default="", help="Session ID (auto-generated when omitted).")
    parser.add_argument("--user-id", default="compare_user", help="User ID for runtime call.")
    parser.add_argument("--user-role", default="normal_user", help="Role used by policy engine.")
    parser.add_argument("--top-k", type=int, default=3, help="Top-k candidates for entity resolver.")
    parser.add_argument("--pretty", action="store_true", help="Pretty print JSON output.")
    parser.add_argument("--output", default="", help="Optional output path for JSON report.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code when consistency checks fail.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _build_payload(args)

    gateway_result = _run_channel("ha_gateway", payload)
    mcp_result = _run_channel("ha_mcp", payload)
    report = _format_output(payload, gateway_result, mcp_result)

    text = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None)
    print(text)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")

    if args.strict and not report["consistency"]["pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

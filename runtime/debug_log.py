from __future__ import annotations

import logging
import os
from typing import Any

_CONFIGURED = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_level(name: str, default: str) -> int:
    value = str(os.getenv(name, default)).strip().upper()
    return getattr(logging, value, getattr(logging, default.upper(), logging.INFO))


def _resolve_level_name() -> str:
    explicit = str(os.getenv("SMARTHOME_LOG_LEVEL", "")).strip().upper()
    if explicit:
        return explicit
    if _env_bool("SMARTHOME_DEBUG_FLOW", False):
        return "DEBUG"
    return "INFO"


def configure_logging() -> None:
    global _CONFIGURED
    level_name = _resolve_level_name()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()

    if not _CONFIGURED:
        if not root.handlers:
            logging.basicConfig(
                level=level,
                format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            )
        else:
            root.setLevel(level)
        _CONFIGURED = True
    else:
        root.setLevel(level)

    logging.getLogger("smarthome").setLevel(level)
    # Keep app debug logs, but suppress extremely verbose MCP SSE transport logs.
    mcp_stream_level = _env_level("SMARTHOME_MCP_STREAM_LOG_LEVEL", "INFO")
    logging.getLogger("mcp.client.streamable_http").setLevel(mcp_stream_level)
    logging.getLogger("mcp.client.sse").setLevel(mcp_stream_level)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"smarthome.{name}")


def is_flow_debug_enabled() -> bool:
    return _env_bool("SMARTHOME_DEBUG_FLOW", False)


def compact(obj: Any, max_len: int = 400) -> str:
    text = repr(obj)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."

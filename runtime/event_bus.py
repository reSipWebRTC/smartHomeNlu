from __future__ import annotations

from collections import defaultdict
import os
from typing import Any, DefaultDict, Dict, List

from .debug_log import compact, get_logger, is_flow_debug_enabled
from .utils import utc_now_iso


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class InMemoryEventBus:
    def __init__(self, *, max_events_per_topic: int | None = None) -> None:
        resolved_limit = max_events_per_topic
        if resolved_limit is None:
            resolved_limit = _env_int("SMARTHOME_EVENT_BUS_MAX_PER_TOPIC", 300)
        self._max_events_per_topic = max(1, int(resolved_limit)) if int(resolved_limit) > 0 else 0
        self._events: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._logger = get_logger("event_bus")

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        entry = {"topic": topic, "timestamp": utc_now_iso(), **payload}
        bucket = self._events[topic]
        bucket.append(entry)
        if self._max_events_per_topic > 0 and len(bucket) > self._max_events_per_topic:
            overflow = len(bucket) - self._max_events_per_topic
            del bucket[:overflow]
        if is_flow_debug_enabled():
            self._logger.debug("publish topic=%s payload=%s", topic, compact(payload))

    def events(self, topic: str) -> List[Dict[str, Any]]:
        return list(self._events.get(topic, []))

    def all_events(self) -> Dict[str, List[Dict[str, Any]]]:
        return {k: list(v) for k, v in self._events.items()}

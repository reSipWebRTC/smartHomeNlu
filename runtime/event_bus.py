from __future__ import annotations

from collections import defaultdict
from typing import Any, DefaultDict, Dict, List

from .utils import utc_now_iso


class InMemoryEventBus:
    def __init__(self) -> None:
        self._events: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        entry = {"topic": topic, "timestamp": utc_now_iso(), **payload}
        self._events[topic].append(entry)

    def events(self, topic: str) -> List[Dict[str, Any]]:
        return list(self._events.get(topic, []))

    def all_events(self) -> Dict[str, List[Dict[str, Any]]]:
        return {k: list(v) for k, v in self._events.items()}

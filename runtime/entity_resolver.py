from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, List

from .contracts import EntityCandidate
from .entity_name_utils import build_entity_aliases, clean_entity_name
from .event_bus import InMemoryEventBus


DEVICE_DOMAIN_HINT = {
    "灯": "light",
    "开关": "switch",
    "插座": "switch",
    "空调": "climate",
    "门锁": "lock",
}

DEVICE_TYPE_TERMS = {
    "灯": ("灯", "灯光", "照明"),
    "开关": ("开关",),
    "插座": ("插座", "排插", "插排", "插线板", "延长线"),
    "空调": ("空调",),
    "门锁": ("门锁", "锁"),
}


class EntityResolver:
    def __init__(self, event_bus: InMemoryEventBus, entities: List[Dict[str, Any]] | None = None) -> None:
        self.event_bus = event_bus
        self.entities = self._prepare_entities(entities or [])

    def reindex(self, entities: List[Dict[str, Any]]) -> None:
        self.entities = self._prepare_entities(entities)

    @staticmethod
    def _prepare_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prepared: List[Dict[str, Any]] = []
        for raw in entities:
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity_id", "")).strip()
            if not entity_id:
                continue
            clean_name = clean_entity_name(str(raw.get("name", "")), entity_id)
            clean_area = clean_entity_name(str(raw.get("area", "")))
            aliases = build_entity_aliases(
                name=clean_name,
                entity_id=entity_id,
                area=clean_area,
                device_type_terms=DEVICE_TYPE_TERMS,
            )
            raw_aliases = raw.get("aliases")
            if isinstance(raw_aliases, list):
                for alias in raw_aliases:
                    alias_text = clean_entity_name(str(alias), entity_id)
                    if alias_text and alias_text != clean_name:
                        aliases.append(alias_text)
            aliases = sorted(set(aliases))
            search_text = f"{clean_name} {clean_area} {' '.join(aliases)} {entity_id}".lower()
            prepared.append(
                {
                    "entity_id": entity_id,
                    "name": clean_name,
                    "area": clean_area,
                    "state": raw.get("state"),
                    "aliases": aliases,
                    "_search_text": search_text,
                }
            )
        return prepared

    def resolve(
        self,
        *,
        trace_id: str,
        slots: Dict[str, Any],
        domain_hint: str | None = None,
        top_k: int = 3,
    ) -> List[EntityCandidate]:
        top_k = max(1, min(int(top_k), 5))

        if slots.get("entity_id"):
            candidate = EntityCandidate(
                entity_id=slots["entity_id"],
                score=1.0,
                name=slots.get("entity_id", ""),
                area=slots.get("location", ""),
            )
            return [candidate]

        device_type = str(slots.get("device_type", "") or "")
        location = str(slots.get("location", "") or "")
        query = f"{location}{device_type}".strip()
        query_norm = query.lower()
        location_norm = location.lower()
        device_terms = [token.lower() for token in DEVICE_TYPE_TERMS.get(device_type, (device_type,)) if token]
        coarse_query = bool(device_type) and (not location_norm) and (query_norm in {device_type.lower(), ""} or len(query_norm) <= 1)

        if not domain_hint:
            domain_hint = DEVICE_DOMAIN_HINT.get(device_type)

        scored: List[EntityCandidate] = []
        for entity in self.entities:
            entity_id = entity.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else ""
            if domain_hint and domain != domain_hint:
                continue
            entity_name = str(entity.get("name", ""))
            entity_area = str(entity.get("area", ""))
            haystack = str(entity.get("_search_text") or f"{entity_name} {entity_area} {entity_id}").lower()

            score = SequenceMatcher(None, query_norm, haystack).ratio() if query_norm else 0.0
            if query_norm and query_norm in haystack:
                score += 0.25
            if domain_hint and domain == domain_hint:
                score += 0.25
            if location_norm and location_norm == entity_area.lower():
                score += 0.15
            elif location_norm and location_norm in haystack:
                score += 0.08
            if device_terms and any(term in haystack for term in device_terms):
                score += 0.2
            scored.append(
                EntityCandidate(
                    entity_id=entity_id,
                    score=min(score, 1.0),
                    name=entity.get("name", entity_id),
                    area=entity.get("area", ""),
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        score_threshold = 0.35
        if coarse_query and domain_hint:
            score_threshold = 0.2
        elif query_norm and len(query_norm) <= 2:
            score_threshold = 0.28

        candidates = [candidate for candidate in scored if candidate.score >= score_threshold][:top_k]
        if not candidates and coarse_query and domain_hint:
            candidates = scored[:top_k]

        self.event_bus.publish(
            "evt.entity.resolved.v1",
            {
                "trace_id": trace_id,
                "candidates": [c.as_dict() for c in candidates],
                "selected": candidates[0].entity_id if candidates else None,
            },
        )

        return candidates

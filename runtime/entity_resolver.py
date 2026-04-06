from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, List

from .contracts import EntityCandidate
from .debug_log import compact, get_logger
from .entity_name_utils import build_entity_aliases, clean_entity_name
from .event_bus import InMemoryEventBus
from .hot_words_lexicon import get_hot_words_lexicon

try:
    import pypinyin  # type: ignore
except ImportError:
    pypinyin = None


DEVICE_DOMAIN_HINT = {
    "灯": "light",
    "开关": "switch",
    "插座": "switch",
    "空调": "climate",
    "门锁": "lock",
}

_BASE_DEVICE_TYPE_TERMS = {
    "灯": ("灯", "灯光", "照明"),
    "开关": ("开关",),
    "插座": ("插座", "排插", "插排", "插线板", "延长线"),
    "空调": ("空调",),
    "门锁": ("门锁", "锁"),
}
_HOT_WORDS = get_hot_words_lexicon()


def _merged_device_type_terms() -> Dict[str, tuple[str, ...]]:
    merged: Dict[str, set[str]] = {key: set(values) for key, values in _BASE_DEVICE_TYPE_TERMS.items()}
    for canonical, values in _HOT_WORDS.device_type_terms.items():
        merged.setdefault(canonical, set()).update({str(item).strip() for item in values if str(item).strip()})
    return {
        key: tuple(sorted(values, key=lambda item: len(item), reverse=True))
        for key, values in merged.items()
    }


DEVICE_TYPE_TERMS = _merged_device_type_terms()


def _normalize_device_type(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    hot = _HOT_WORDS.infer_device_type(raw)
    if hot:
        return hot

    lowered = raw.lower()
    if any(token in lowered for token in ("灯", "light", "lamp")):
        return "灯"
    if any(token in lowered for token in ("空调", "climate", "ac")):
        return "空调"
    if any(token in lowered for token in ("门锁", "lock")):
        return "门锁"
    if any(token in lowered for token in ("插座", "socket", "outlet", "plug")):
        return "插座"
    if any(token in lowered for token in ("开关", "switch")):
        return "开关"
    return raw


class EntityResolver:
    def __init__(self, event_bus: InMemoryEventBus, entities: List[Dict[str, Any]] | None = None) -> None:
        self.event_bus = event_bus
        self.entities = self._prepare_entities(entities or [])
        self._logger = get_logger("entity_resolver")

    @staticmethod
    def _pinyin_similarity(a: str, b: str) -> float:
        """Compute pinyin-level similarity between two strings."""
        if pypinyin is None:
            return 0.0
        try:
            py_a = [item[0] for item in pypinyin.pinyin(a, style=pypinyin.NORMAL)]
            py_b = [item[0] for item in pypinyin.pinyin(b, style=pypinyin.NORMAL)]
        except Exception:
            return 0.0
        if not py_a or not py_b:
            return 0.0
        return SequenceMatcher(None, py_a, py_b).ratio()

    def reindex(self, entities: List[Dict[str, Any]]) -> None:
        self.entities = self._prepare_entities(entities)
        self._logger.debug("reindex size=%d", len(self.entities))

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

        device_type_raw = str(slots.get("_original_device_type") or slots.get("device_type", "") or "")
        device_type = _normalize_device_type(str(slots.get("device_type", "") or ""))
        location = str(slots.get("location", "") or "")
        query_device = device_type_raw if device_type_raw and _normalize_device_type(device_type_raw) != device_type else device_type_raw
        query = f"{location}{query_device}".strip()
        query_norm = query.lower()
        location_norm = location.lower()
        device_terms = [token.lower() for token in DEVICE_TYPE_TERMS.get(device_type, (device_type,)) if token]
        if device_type_raw and device_type_raw != device_type:
            device_terms.append(device_type_raw.lower())
        coarse_query = bool(device_type) and (not location_norm) and (query_norm in {device_type.lower(), ""} or len(query_norm) <= 1)

        if not domain_hint:
            domain_hint = DEVICE_DOMAIN_HINT.get(device_type)

        # sub_intent implied domain (e.g. set_temperature→climate) but no
        # explicit device_type; allow returning top entities in this domain.
        domain_only = bool(domain_hint) and not device_type

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

            # Pinyin fallback: when char-level similarity is low,
            # boost based on phonetic (pinyin) similarity
            if score < 0.35 and query_norm and len(query_norm) >= 2:
                py_sim = self._pinyin_similarity(query_norm, haystack)
                if py_sim > 0.5:
                    score += 0.25 * py_sim
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
        elif domain_only:
            score_threshold = 0.2
        elif query_norm and len(query_norm) <= 2:
            score_threshold = 0.28

        candidates = [candidate for candidate in scored if candidate.score >= score_threshold][:top_k]
        if not candidates and (coarse_query and domain_hint or domain_only):
            candidates = scored[:top_k]

        self._logger.debug(
            "resolve trace_id=%s slots=%s domain_hint=%s query=%s threshold=%.2f candidates=%s",
            trace_id,
            compact(slots),
            domain_hint,
            query,
            score_threshold,
            compact([c.as_dict() for c in candidates], max_len=600),
        )

        self.event_bus.publish(
            "evt.entity.resolved.v1",
            {
                "trace_id": trace_id,
                "candidates": [c.as_dict() for c in candidates],
                "selected": candidates[0].entity_id if candidates else None,
            },
        )

        return candidates

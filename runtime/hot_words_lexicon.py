from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _default_hot_words_file() -> Path:
    return Path(__file__).resolve().parents[1] / "hot_words_config.json"


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _sorted_unique(values: List[str]) -> Tuple[str, ...]:
    seen = {item for item in values if item}
    return tuple(sorted(seen, key=lambda item: len(item), reverse=True))


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


@dataclass(frozen=True)
class HotWordsLexicon:
    action_terms: Tuple[Tuple[str, str], ...]
    set_terms: Tuple[str, ...]
    temperature_terms: Tuple[str, ...]
    brightness_terms: Tuple[str, ...]
    query_terms: Tuple[str, ...]
    scene_terms: Tuple[str, ...]
    location_terms: Tuple[str, ...]
    filler_phrases: Tuple[str, ...]
    filler_chars: Tuple[str, ...]
    device_terms: Tuple[Tuple[str, str], ...]
    device_type_terms: Dict[str, Tuple[str, ...]]
    connectors: Tuple[str, ...]

    def strip_fillers(self, text: str) -> str:
        cleaned = str(text or "")
        for phrase in self.filler_phrases:
            cleaned = cleaned.replace(phrase, "")
        for token in self.filler_chars:
            cleaned = cleaned.replace(token, "")
        return cleaned

    def infer_sub_intent(self, text: str) -> str | None:
        cleaned = _normalize_text(self.strip_fillers(text))
        if not cleaned:
            return None

        for token, sub_intent in self.action_terms:
            if token and token in cleaned:
                return sub_intent

        has_set = any(token in cleaned for token in self.set_terms)
        if has_set:
            if any(token in cleaned for token in self.temperature_terms):
                return "set_temperature"
            if any(token in cleaned for token in self.brightness_terms):
                return "adjust_brightness"

        if any(token in cleaned for token in self.query_terms):
            return "query_status"
        if any(token in cleaned for token in self.scene_terms):
            return "activate_scene"
        return None

    def infer_device_type(self, text: str) -> str | None:
        cleaned = _normalize_text(self.strip_fillers(text))
        if not cleaned:
            return None
        for token, device_type in self.device_terms:
            if token and token in cleaned:
                return device_type
        return None

    def infer_location(self, text: str) -> str | None:
        cleaned = _normalize_text(self.strip_fillers(text))
        if not cleaned:
            return None
        for token in self.location_terms:
            if token and token in cleaned:
                return token
        return None


def _map_device_term_to_canonical(term: str, category: str) -> str | None:
    text = _normalize_text(term)
    if not text:
        return None
    if category == "light":
        return "灯"
    if category == "ac":
        return "空调"
    if category == "security":
        if any(token in text for token in ("锁", "门禁", "门铃", "对讲")):
            return "门锁"
        return None

    if any(token in text for token in ("插座", "排插", "插排", "插线板", "延长线")):
        return "插座"
    if "开关" in text:
        return "开关"
    if any(token in text for token in ("锁", "门禁", "门铃", "对讲")):
        return "门锁"
    if any(token in text for token in ("空调", "新风", "地暖", "暖气", "温控")):
        return "空调"
    if any(token in text for token in ("灯", "照明", "筒灯", "吊灯", "射灯")):
        return "灯"
    return None


def _parse_hot_words(payload: Dict[str, Any]) -> HotWordsLexicon:
    actions = payload.get("actions") if isinstance(payload.get("actions"), dict) else {}
    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    semantics = payload.get("semantics") if isinstance(payload.get("semantics"), dict) else {}
    devices = payload.get("devices") if isinstance(payload.get("devices"), dict) else {}
    locations = payload.get("locations") if isinstance(payload.get("locations"), dict) else {}
    filler = payload.get("filler") if isinstance(payload.get("filler"), dict) else {}
    device_aliases = payload.get("device_aliases") if isinstance(payload.get("device_aliases"), dict) else {}
    connectors_raw = _as_str_list(payload.get("connectors"))

    action_group_to_sub_intent = {
        "open": "power_on",
        "close": "power_off",
        "query": "query_status",
        "adjust_up": "adjust_brightness",
        "adjust_down": "adjust_brightness",
    }

    action_pairs: List[Tuple[str, str]] = []
    for group, sub_intent in action_group_to_sub_intent.items():
        values = actions.get(group)
        if isinstance(values, list):
            for item in values:
                token = _normalize_text(item)
                if token:
                    action_pairs.append((token, sub_intent))
    action_pairs = sorted(set(action_pairs), key=lambda item: len(item[0]), reverse=True)

    set_terms = _sorted_unique([_normalize_text(item) for item in _as_str_list(actions.get("set"))])
    temperature_terms = _sorted_unique(
        [_normalize_text(item) for item in _as_str_list(parameters.get("temperature"))]
    )
    brightness_terms = _sorted_unique(
        [_normalize_text(item) for item in _as_str_list(parameters.get("brightness"))]
    )
    query_terms = _sorted_unique([_normalize_text(item) for item in _as_str_list(semantics.get("query"))])
    scene_values = _as_str_list(semantics.get("scene")) + _as_str_list(semantics.get("mode"))
    scene_terms = _sorted_unique([_normalize_text(item) for item in scene_values])

    location_terms_values: List[str] = []
    for group in ("room", "floor", "area"):
        location_terms_values.extend([_normalize_text(item) for item in _as_str_list(locations.get(group))])
    location_terms = _sorted_unique(location_terms_values)

    filler_phrases = _sorted_unique(
        [_normalize_text(item) for item in _as_str_list(filler.get("phrases"))]
    )
    filler_chars = _sorted_unique([_normalize_text(item) for item in _as_str_list(filler.get("chars"))])

    device_pairs: List[Tuple[str, str]] = []
    device_type_terms_raw: Dict[str, List[str]] = {"灯": [], "空调": [], "门锁": [], "开关": [], "插座": []}
    for category, values in devices.items():
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, str):
                continue
            token = _normalize_text(item)
            if not token:
                continue
            mapped = _map_device_term_to_canonical(token, str(category))
            if not mapped:
                continue
            device_pairs.append((token, mapped))
            device_type_terms_raw.setdefault(mapped, []).append(token)

    for alias, canonical in device_aliases.items():
        token = _normalize_text(alias)
        mapped = _map_device_term_to_canonical(canonical, "other")
        if token and mapped:
            device_pairs.append((token, mapped))
            device_type_terms_raw.setdefault(mapped, []).append(token)

    # Keep key canonical terms present even if config misses them.
    for mapped, terms in {
        "灯": ("灯", "灯光"),
        "空调": ("空调", "新风", "温控"),
        "门锁": ("门锁", "智能锁", "指纹锁"),
        "开关": ("开关",),
        "插座": ("插座", "排插", "插排"),
    }.items():
        device_type_terms_raw.setdefault(mapped, []).extend([_normalize_text(item) for item in terms])

    device_pairs = sorted(set(device_pairs), key=lambda item: len(item[0]), reverse=True)
    device_type_terms = {key: _sorted_unique(value) for key, value in device_type_terms_raw.items() if value}
    connectors = _sorted_unique([_normalize_text(item) for item in connectors_raw])

    return HotWordsLexicon(
        action_terms=tuple(action_pairs),
        set_terms=set_terms,
        temperature_terms=temperature_terms,
        brightness_terms=brightness_terms,
        query_terms=query_terms,
        scene_terms=scene_terms,
        location_terms=location_terms,
        filler_phrases=filler_phrases,
        filler_chars=filler_chars,
        device_terms=tuple(device_pairs),
        device_type_terms=device_type_terms,
        connectors=connectors,
    )


def _empty_lexicon() -> HotWordsLexicon:
    return HotWordsLexicon(
        action_terms=(),
        set_terms=(),
        temperature_terms=(),
        brightness_terms=(),
        query_terms=(),
        scene_terms=(),
        location_terms=(),
        filler_phrases=(),
        filler_chars=(),
        device_terms=(),
        device_type_terms={},
        connectors=(),
    )


@lru_cache(maxsize=1)
def get_hot_words_lexicon() -> HotWordsLexicon:
    hot_words_file = Path((os.getenv("SMARTHOME_HOT_WORDS_FILE") or str(_default_hot_words_file()))).resolve()
    if not hot_words_file.exists():
        return _empty_lexicon()
    try:
        payload = json.loads(hot_words_file.read_text(encoding="utf-8"))
    except Exception:
        return _empty_lexicon()
    if not isinstance(payload, dict):
        return _empty_lexicon()
    return _parse_hot_words(payload)

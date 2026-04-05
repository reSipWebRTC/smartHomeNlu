from __future__ import annotations

import re
from typing import Dict, Iterable, List


_NONE_TOKEN_RE = re.compile(r"(?:(?<=\s)|^)(none|null|nil)(?=\s|$)", re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"\s+")
_INDEX_SUFFIX_RE = re.compile(r"_(\d+)$")


def clean_entity_name(raw_name: str, entity_id: str | None = None) -> str:
    text = str(raw_name or "").strip()
    text = text.replace("_", " ")
    text = _NONE_TOKEN_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    if text:
        return text
    fallback = str(entity_id or "").strip()
    return fallback


def normalize_entity_name(raw_name: str) -> str:
    cleaned = clean_entity_name(raw_name)
    return _MULTI_SPACE_RE.sub("", cleaned).lower()


def extract_entity_index(entity_id: str) -> int | None:
    if not entity_id:
        return None
    object_id = str(entity_id).split(".", 1)[-1]
    match = _INDEX_SUFFIX_RE.search(object_id)
    if not match:
        return None
    try:
        index = int(match.group(1))
    except ValueError:
        return None
    if index <= 0:
        return None
    return index


def build_entity_aliases(
    *,
    name: str,
    entity_id: str,
    area: str = "",
    device_type_terms: Dict[str, Iterable[str]] | None = None,
) -> List[str]:
    cleaned_name = clean_entity_name(name, entity_id)
    aliases: set[str] = set()

    def _add(value: str) -> None:
        candidate = clean_entity_name(value)
        if not candidate:
            return
        if candidate == cleaned_name:
            return
        aliases.add(candidate)

    tokens = [tok for tok in cleaned_name.split(" ") if tok]
    if len(tokens) >= 2:
        _add(tokens[-1])
        _add("".join(tokens[-2:]))
    elif tokens:
        _add(tokens[-1])

    if area:
        _add(f"{area}{cleaned_name}")
        if tokens:
            _add(f"{area}{tokens[-1]}")

    if device_type_terms:
        for _, terms in device_type_terms.items():
            terms_list = [str(term).strip() for term in terms if str(term).strip()]
            if not terms_list:
                continue
            if any(term in cleaned_name for term in terms_list):
                for term in terms_list:
                    _add(term)

    object_id = str(entity_id).split(".", 1)[-1].replace("_", " ").strip()
    _add(object_id)

    return sorted(aliases)


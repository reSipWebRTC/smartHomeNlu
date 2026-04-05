from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .entity_name_utils import clean_entity_name


def _default_alias_file() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "entity_aliases.json"


class EntityAliasStore:
    def __init__(self, *, path: str | None = None) -> None:
        self.path = Path((path or os.getenv("SMARTHOME_ENTITY_ALIAS_FILE") or str(_default_alias_file()))).resolve()
        self._cache_mtime: float | None = None
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            self._cache_mtime = None
            self._cache = {}
            return self._cache

        try:
            stat = self.path.stat()
            mtime = float(stat.st_mtime)
        except OSError:
            self._cache_mtime = None
            self._cache = {}
            return self._cache

        if self._cache_mtime is not None and self._cache_mtime == mtime:
            return self._cache

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._cache_mtime = mtime
            self._cache = {}
            return self._cache

        mapping: Dict[str, Dict[str, Any]] = {}

        if isinstance(payload, dict):
            overrides = payload.get("entity_overrides")
            if isinstance(overrides, dict):
                for entity_id, value in overrides.items():
                    if not isinstance(value, dict):
                        continue
                    mapping[str(entity_id)] = dict(value)

            legacy_aliases = payload.get("entity_aliases")
            if isinstance(legacy_aliases, dict):
                for entity_id, aliases in legacy_aliases.items():
                    if not isinstance(aliases, list):
                        continue
                    entry = mapping.setdefault(str(entity_id), {})
                    entry["aliases"] = list(aliases)

            # Allow direct root mapping: {"switch.xxx": {"name": "...", "aliases": [...]}}
            for key, value in payload.items():
                if key in {"entity_overrides", "entity_aliases"}:
                    continue
                if "." not in str(key):
                    continue
                if not isinstance(value, dict):
                    continue
                mapping[str(key)] = dict(value)

        self._cache_mtime = mtime
        self._cache = mapping
        return self._cache

    def get_override(self, entity_id: str) -> Dict[str, Any]:
        mapping = self._load()
        return dict(mapping.get(str(entity_id), {}))

    def apply(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(entity, dict):
            return {}

        out = dict(entity)
        entity_id = str(out.get("entity_id", "")).strip()
        if not entity_id:
            return out

        override = self.get_override(entity_id)
        base_name = str(out.get("name", "")).strip() or entity_id
        override_name = str(override.get("name", "")).strip()
        final_name = clean_entity_name(override_name or base_name, entity_id)
        out["name"] = final_name

        base_area = str(out.get("area", "")).strip()
        override_area = str(override.get("area", "")).strip()
        out["area"] = clean_entity_name(override_area or base_area)

        aliases: List[str] = []
        for source in (out.get("aliases"), override.get("aliases")):
            if not isinstance(source, list):
                continue
            for raw in source:
                text = clean_entity_name(str(raw), entity_id)
                if not text or text == final_name:
                    continue
                aliases.append(text)
        out["aliases"] = sorted(set(aliases))
        return out


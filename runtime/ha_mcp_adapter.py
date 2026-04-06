from __future__ import annotations

import asyncio
import json
import os
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List
from urllib.parse import urlsplit, urlunsplit

import httpx

from .debug_log import compact, get_logger


DEFAULT_ENTITIES: List[Dict[str, Any]] = [
    {
        "entity_id": "light.living_room_main",
        "name": "客厅主灯",
        "area": "客厅",
        "state": "off",
    },
    {
        "entity_id": "light.bedroom_lamp",
        "name": "卧室床头灯",
        "area": "卧室",
        "state": "off",
    },
    {
        "entity_id": "climate.living_room_ac",
        "name": "客厅空调",
        "area": "客厅",
        "state": "off",
    },
    {
        "entity_id": "lock.front_door",
        "name": "前门门锁",
        "area": "玄关",
        "state": "locked",
    },
    {
        "entity_id": "scene.home_mode",
        "name": "回家模式",
        "area": "全屋",
        "state": "off",
    },
]


TOOL_NAME_ALIAS = {
    "ha_create_backup": "ha_backup_create",
}

TOOL_PROXY_HINT = {
    "ha_search_entities": "ha_call_read_tool",
    "ha_get_entity": "ha_call_read_tool",
    "ha_call_service": "ha_call_write_tool",
    "ha_backup_create": "ha_call_write_tool",
    "ha_create_backup": "ha_call_write_tool",
}

DEFAULT_SYNC_DOMAINS = (
    "light",
    "switch",
    "climate",
    "lock",
    "scene",
    "cover",
    "fan",
    "media_player",
    "vacuum",
    "humidifier",
    "dehumidifier",
    "water_heater",
    "alarm_control_panel",
    "remote",
    "valve",
    "siren",
    "input_boolean",
    "button",
)


def _parse_csv(value: str) -> List[str]:
    items = [item.strip().lower() for item in str(value or "").split(",")]
    return [item for item in items if item]


def _normalize_mcp_url(raw_url: str) -> str:
    url = str(raw_url or "").strip()
    if not url:
        return ""

    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url

    path = parsed.path.strip()
    if path in {"", "/"}:
        path = "/mcp"
    elif path.endswith("/") and path != "/":
        path = path[:-1]
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _is_probable_missing_tool_error(error_code: str, message: str) -> bool:
    code = str(error_code or "").strip().upper()
    text = str(message or "").strip().lower()
    if "tool" not in text:
        return False
    if code in {"NOT_FOUND", "UPSTREAM_ERROR"} and "not found" in text:
        return True
    if code == "BAD_REQUEST" and "ha_call_" in text:
        return True
    if "proxy" in text and "ha_call_" in text:
        return True
    return False


def _default_status_code(error_code: str) -> int:
    if error_code in {"ENTITY_NOT_FOUND", "NOT_FOUND"}:
        return 404
    if error_code == "UNAUTHORIZED":
        return 401
    if error_code == "FORBIDDEN":
        return 403
    if error_code == "BAD_REQUEST":
        return 400
    if error_code == "CONFLICT":
        return 409
    if error_code == "INTERNAL_ERROR":
        return 500
    if error_code == "UPSTREAM_TIMEOUT":
        return 504
    return 502


RUNTIME_ERROR_CODES = {
    "BAD_REQUEST",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "NOT_FOUND",
    "CONFLICT",
    "UPSTREAM_TIMEOUT",
    "UPSTREAM_ERROR",
    "ENTITY_NOT_FOUND",
    "POLICY_CONFIRM_REQUIRED",
    "CONFIRM_TOKEN_EXPIRED",
    "INTERNAL_ERROR",
}


def _coerce_status_code(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        code = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text or not text.isdigit():
            return None
        code = int(text)
    else:
        return None
    return code if 100 <= code <= 599 else None


def _extract_remote_error_code(payload: Dict[str, Any]) -> str:
    candidates: List[Any] = [
        payload.get("error_code"),
        payload.get("code"),
    ]

    error_obj = payload.get("error")
    if isinstance(error_obj, dict):
        candidates.extend([error_obj.get("error_code"), error_obj.get("code")])

    data_obj = payload.get("data")
    if isinstance(data_obj, dict):
        candidates.extend([data_obj.get("error_code"), data_obj.get("code")])
        data_error = data_obj.get("error")
        if isinstance(data_error, dict):
            candidates.extend([data_error.get("error_code"), data_error.get("code")])

    for item in candidates:
        if item is None:
            continue
        value = str(item).strip()
        if value:
            return value.upper()
    return ""


def _extract_remote_error_message(payload: Dict[str, Any]) -> str:
    candidates: List[Any] = [
        payload.get("message"),
        payload.get("error_message"),
        payload.get("detail"),
    ]

    error_obj = payload.get("error")
    if isinstance(error_obj, dict):
        candidates.extend([error_obj.get("message"), error_obj.get("detail")])
    elif error_obj is not None:
        candidates.append(error_obj)

    data_obj = payload.get("data")
    if isinstance(data_obj, dict):
        candidates.extend([data_obj.get("message"), data_obj.get("error_message"), data_obj.get("detail")])
        data_error = data_obj.get("error")
        if isinstance(data_error, dict):
            candidates.extend([data_error.get("message"), data_error.get("detail")])
        elif data_error is not None:
            candidates.append(data_error)

    for item in candidates:
        if item is None:
            continue
        if isinstance(item, dict):
            continue
        text = str(item).strip()
        if text:
            return text
    return ""


def _extract_remote_status_code(payload: Dict[str, Any]) -> int | None:
    candidates: List[Any] = [
        payload.get("status_code"),
        payload.get("status"),
        payload.get("http_status"),
        payload.get("http_status_code"),
        payload.get("statusCode"),
    ]

    error_obj = payload.get("error")
    if isinstance(error_obj, dict):
        candidates.extend(
            [
                error_obj.get("status_code"),
                error_obj.get("status"),
                error_obj.get("http_status"),
                error_obj.get("http_status_code"),
                error_obj.get("statusCode"),
            ]
        )

    data_obj = payload.get("data")
    if isinstance(data_obj, dict):
        candidates.extend(
            [
                data_obj.get("status_code"),
                data_obj.get("status"),
                data_obj.get("http_status"),
                data_obj.get("http_status_code"),
                data_obj.get("statusCode"),
            ]
        )
        data_error = data_obj.get("error")
        if isinstance(data_error, dict):
            candidates.extend(
                [
                    data_error.get("status_code"),
                    data_error.get("status"),
                    data_error.get("http_status"),
                    data_error.get("http_status_code"),
                    data_error.get("statusCode"),
                ]
            )

    for item in candidates:
        parsed = _coerce_status_code(item)
        if parsed is not None:
            return parsed
    return None


def _map_remote_error_code(raw_error_code: str, message: str, status_code: int | None) -> str:
    code = str(raw_error_code or "").strip().upper()
    if code in RUNTIME_ERROR_CODES:
        return code

    if code == "ENTITY_NOT_FOUND":
        return "ENTITY_NOT_FOUND"
    if code in {"RESOURCE_NOT_FOUND", "SERVICE_NOT_FOUND", "CONFIG_NOT_FOUND"}:
        return "NOT_FOUND"
    if code in {"RESOURCE_ALREADY_EXISTS", "RESOURCE_LOCKED"}:
        return "CONFLICT"
    if code in {"ENTITY_INVALID_ID", "ENTITY_DOMAIN_MISMATCH"}:
        return "BAD_REQUEST"
    if code in {"SERVICE_INVALID_DOMAIN", "SERVICE_INVALID_ACTION"}:
        return "BAD_REQUEST"
    if code in {"CONNECTION_TIMEOUT", "TIMEOUT_OPERATION", "TIMEOUT_WEBSOCKET", "TIMEOUT_API_REQUEST"}:
        return "UPSTREAM_TIMEOUT"
    if code.startswith("TIMEOUT_"):
        return "UPSTREAM_TIMEOUT"
    if code.startswith("AUTH_") or code == "WEBSOCKET_NOT_AUTHENTICATED":
        return "FORBIDDEN"
    if code.startswith("VALIDATION_"):
        return "BAD_REQUEST"
    if code.startswith("CONFIG_"):
        return "BAD_REQUEST"
    if code.startswith("INTERNAL_"):
        return "UPSTREAM_ERROR"
    if code.startswith("CONNECTION_"):
        return "UPSTREAM_ERROR"
    if code.startswith("SERVICE_"):
        return "UPSTREAM_ERROR"
    if code.startswith("ENTITY_"):
        return "UPSTREAM_ERROR"
    if code.startswith("RESOURCE_"):
        return "UPSTREAM_ERROR"
    if code.startswith("WEBSOCKET_"):
        return "UPSTREAM_ERROR"

    text = (message or "").lower()
    if "timeout" in text:
        return "UPSTREAM_TIMEOUT"
    if "forbidden" in text or "permission" in text or "unauthorized" in text or "not authenticated" in text:
        return "FORBIDDEN"
    if "bad request" in text or "invalid" in text or "missing parameter" in text:
        return "BAD_REQUEST"
    if "not found" in text or "does not exist" in text:
        if "entity" in text:
            return "ENTITY_NOT_FOUND"
        return "NOT_FOUND"

    if status_code is not None:
        if status_code in {400, 422}:
            return "BAD_REQUEST"
        if status_code in {401, 403}:
            return "FORBIDDEN"
        if status_code == 404:
            return "NOT_FOUND"
        if status_code == 409:
            return "CONFLICT"
        if status_code in {408, 504}:
            return "UPSTREAM_TIMEOUT"
        if status_code >= 500:
            return "UPSTREAM_ERROR"

    return "UPSTREAM_ERROR"


RemoteToolRunner = Callable[[str, Dict[str, Any]], Dict[str, Any]]


class HaMcpAdapter:
    def __init__(
        self,
        entities: List[Dict[str, Any]] | None = None,
        *,
        mcp_url: str | None = None,
        mcp_token: str | None = None,
        timeout_sec: float = 8.0,
        timeout_retries: int = 1,
        remote_tool_runner: RemoteToolRunner | None = None,
    ) -> None:
        self._mcp_url = _normalize_mcp_url(mcp_url or os.getenv("SMARTHOME_HA_MCP_URL") or "")
        self._mcp_token = (mcp_token or os.getenv("SMARTHOME_HA_MCP_TOKEN") or "").strip()
        self._timeout_sec = float(timeout_sec)
        env_retries = os.getenv("SMARTHOME_HA_MCP_TIMEOUT_RETRIES")
        if env_retries is not None:
            try:
                timeout_retries = int(env_retries)
            except ValueError:
                pass
        self._timeout_retries = max(0, int(timeout_retries))
        sync_domains_raw = os.getenv("SMARTHOME_HA_MCP_SYNC_DOMAINS", "")
        parsed_sync_domains = _parse_csv(sync_domains_raw)
        self._sync_domains = tuple(parsed_sync_domains or list(DEFAULT_SYNC_DOMAINS))
        sync_limit_raw = os.getenv("SMARTHOME_HA_MCP_SYNC_LIMIT_PER_DOMAIN", "200")
        try:
            sync_limit = int(sync_limit_raw)
        except ValueError:
            sync_limit = 200
        self._sync_limit_per_domain = max(20, min(sync_limit, 1000))
        self._remote_tool_runner = remote_tool_runner
        self.mode = "ha_mcp" if (self._mcp_url or remote_tool_runner is not None) else "stub"
        self._logger = get_logger("ha_mcp")

        if self.mode == "stub":
            self._entities = [dict(item) for item in (entities or DEFAULT_ENTITIES)]
        else:
            self._entities = [dict(item) for item in (entities or [])]

        self.service_call_count = 0
        self.backup_call_count = 0
        self._logger.info(
            "adapter init mode=%s mcp_url=%s timeout_sec=%s retries=%s",
            self.mode,
            self._mcp_url or "(unset)",
            self._timeout_sec,
            self._timeout_retries,
        )

    def get_all_entities(self, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
        if self.mode == "ha_mcp" and (force_refresh or not self._entities):
            self._entities = self._sync_entities_best_effort()
        return [dict(entity) for entity in self._entities]

    def search_entities(self, query: str, domain: str | None = None, limit: int = 3) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        if self.mode == "ha_mcp":
            params: Dict[str, Any] = {"query": query, "limit": limit}
            if domain:
                params["domain_filter"] = domain
            raw = self._remote_tool_call("ha_search_entities", params)
            if not raw.get("success"):
                return []
            entities = list(raw.get("entities", []))
            entities.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
            return entities[:limit]

        limit = max(1, min(limit, 1000))
        scored: List[tuple[float, Dict[str, Any]]] = []
        for entity in self._entities:
            entity_id = entity["entity_id"]
            entity_domain = entity_id.split(".")[0]
            if domain and entity_domain != domain:
                continue
            haystack = f"{entity.get('name','')}{entity.get('area','')}{entity_id}"
            score = SequenceMatcher(None, query, haystack).ratio()
            if query and query in haystack:
                score += 0.2
            scored.append((min(score, 1.0), entity))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [dict(entity, score=round(score, 3)) for score, entity in scored[:limit] if score >= 0.35]

    def _find_entity(self, entity_id: str) -> Dict[str, Any] | None:
        for entity in self._entities:
            if entity["entity_id"] == entity_id:
                return entity
        return None

    def call_service(
        self,
        *,
        domain: str,
        service: str,
        entity_id: str,
        params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        params = params or {}
        self.service_call_count += 1

        if self.mode == "ha_mcp":
            call = self._remote_tool_call(
                "ha_call_service",
                {
                    "domain": domain,
                    "service": service,
                    "entity_id": entity_id or None,
                    "data": params,
                },
            )
            if not call.get("success"):
                error_code = str(call.get("error_code", "UPSTREAM_ERROR"))
                return {
                    "success": False,
                    "error_code": error_code,
                    "status_code": int(call.get("status_code", _default_status_code(error_code))),
                    "entity_id": entity_id,
                }
            return {
                "success": True,
                "status_code": int(call.get("status_code", 200)),
                "entity_id": entity_id,
                "state": call.get("state"),
                "params": params,
                "partial": bool(call.get("partial", False)),
                "warning": call.get("warning"),
            }

        entity = self._find_entity(entity_id)
        if entity is None:
            return {
                "success": False,
                "error_code": "ENTITY_NOT_FOUND",
                "status_code": 404,
                "entity_id": entity_id,
            }

        if domain == "light":
            if service == "turn_on":
                entity["state"] = "on"
                if "brightness_pct" in params:
                    entity["brightness_pct"] = params["brightness_pct"]
            elif service == "turn_off":
                entity["state"] = "off"
        elif domain == "climate" and service == "set_temperature":
            entity["state"] = "on"
            if "temperature" in params:
                entity["temperature"] = params["temperature"]
        elif domain == "lock" and service == "unlock":
            entity["state"] = "unlocked"
        elif domain == "scene" and service == "turn_on":
            entity["state"] = "on"

        return {
            "success": True,
            "status_code": 200,
            "entity_id": entity_id,
            "state": entity.get("state"),
            "params": params,
        }

    def tool_call(self, tool_name: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        params = params or {}

        if self.mode == "ha_mcp":
            result = self._remote_tool_call(tool_name, params)
            if tool_name in {"ha_create_backup", "ha_backup_create"} and result.get("success"):
                self.backup_call_count += 1
            return result

        if tool_name == "ha_get_entity":
            entity_id = str(params.get("entity_id", ""))
            if not entity_id:
                return {"success": False, "status_code": 400, "error_code": "BAD_REQUEST"}
            entity = self._find_entity(entity_id)
            if entity is None:
                return {
                    "success": False,
                    "status_code": 404,
                    "error_code": "ENTITY_NOT_FOUND",
                    "entity_id": entity_id,
                }
            return {"success": True, "status_code": 200, "entity": dict(entity)}

        if tool_name == "ha_search_entities":
            query = str(params.get("query", ""))
            domain = params.get("domain")
            try:
                limit = int(params.get("limit", 3))
            except (TypeError, ValueError):
                limit = 3
            entities = self.search_entities(query=query, domain=domain, limit=limit)
            return {"success": True, "status_code": 200, "entities": entities}

        if tool_name in {"ha_create_backup", "ha_backup_create"}:
            self.backup_call_count += 1
            return {"success": True, "status_code": 200, "backup_id": "bk_001"}
        return {"success": False, "status_code": 400, "error_code": "BAD_REQUEST"}

    def _sync_entities_best_effort(self) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        for domain in self._sync_domains:
            for item in self.search_entities(query="", domain=domain, limit=self._sync_limit_per_domain):
                entity_id = str(item.get("entity_id", ""))
                if not entity_id:
                    continue
                collected.append(
                    {
                        "entity_id": entity_id,
                        "name": str(item.get("name", "")),
                        "area": str(item.get("area", "")),
                        "state": item.get("state", "unknown"),
                    }
                )

        dedup: Dict[str, Dict[str, Any]] = {}
        for item in collected:
            dedup[item["entity_id"]] = item
        return list(dedup.values())

    def _remote_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._logger.debug("remote_tool_call name=%s params=%s", tool_name, compact(params))
        primary = self._call_and_normalize(tool_name, params)
        if primary.get("success"):
            return primary

        proxy_tool = TOOL_PROXY_HINT.get(tool_name)
        if not proxy_tool:
            self._logger.warning("remote_tool_call failed name=%s result=%s", tool_name, compact(primary))
            return primary

        error_code = str(primary.get("error_code", ""))
        error_msg = str(primary.get("error", ""))
        if not _is_probable_missing_tool_error(error_code, error_msg):
            self._logger.warning("remote_tool_call failed name=%s result=%s", tool_name, compact(primary))
            return primary

        target_tool = TOOL_NAME_ALIAS.get(tool_name, tool_name)
        proxy_params = {"name": target_tool, "arguments": dict(params)}
        proxy_result = self._call_and_normalize(proxy_tool, proxy_params, normalize_as=tool_name)
        if proxy_result.get("success"):
            return proxy_result
        self._logger.warning(
            "remote_tool_call failed name=%s primary=%s proxy_result=%s",
            tool_name,
            compact(primary),
            compact(proxy_result),
        )
        return primary

    def _call_and_normalize(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        normalize_as: str | None = None,
    ) -> Dict[str, Any]:
        target_name = normalize_as or tool_name
        attempts = 1 if self._remote_tool_runner is not None else (1 + self._timeout_retries)
        last_result: Dict[str, Any] = {
            "success": False,
            "error_code": "UPSTREAM_ERROR",
            "status_code": 502,
        }
        for _ in range(max(1, attempts)):
            raw_payload = self._invoke_remote_tool(tool_name, params)
            normalized = self._normalize_remote_result(target_name, raw_payload)
            last_result = normalized
            if normalized.get("success"):
                return normalized
            if str(normalized.get("error_code", "")).upper() != "UPSTREAM_TIMEOUT":
                return normalized
        return last_result

    def _invoke_remote_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._remote_tool_runner is not None:
            try:
                return self._remote_tool_runner(tool_name, dict(params))
            except TimeoutError:
                self._logger.warning("invoke_remote_tool timeout name=%s", tool_name)
                return {"success": False, "error_code": "UPSTREAM_TIMEOUT", "status_code": 504}
            except Exception as exc:
                self._logger.warning("invoke_remote_tool exception name=%s error=%s", tool_name, str(exc))
                return {
                    "success": False,
                    "error_code": "UPSTREAM_ERROR",
                    "status_code": 502,
                    "error": str(exc),
                }

        if not self._mcp_url:
            self._logger.warning("invoke_remote_tool missing mcp_url name=%s", tool_name)
            return {
                "success": False,
                "error_code": "UPSTREAM_ERROR",
                "status_code": 502,
                "error": "SMARTHOME_HA_MCP_URL is not configured",
            }

        try:
            return asyncio.run(self._call_tool_via_mcp(tool_name, params))
        except httpx.TimeoutException:
            self._logger.warning("invoke_remote_tool timeout name=%s", tool_name)
            return {"success": False, "error_code": "UPSTREAM_TIMEOUT", "status_code": 504}
        except TimeoutError:
            self._logger.warning("invoke_remote_tool timeout name=%s", tool_name)
            return {"success": False, "error_code": "UPSTREAM_TIMEOUT", "status_code": 504}
        except ImportError as exc:
            self._logger.warning("invoke_remote_tool import_error name=%s error=%s", tool_name, str(exc))
            return {
                "success": False,
                "error_code": "UPSTREAM_ERROR",
                "status_code": 502,
                "error": f"mcp client unavailable: {exc}",
            }
        except Exception as exc:
            self._logger.warning("invoke_remote_tool exception name=%s error=%s", tool_name, str(exc))
            return {
                "success": False,
                "error_code": "UPSTREAM_ERROR",
                "status_code": 502,
                "error": str(exc),
            }

    async def _call_tool_via_mcp(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers: Dict[str, str] = {}
        if self._mcp_token:
            headers["Authorization"] = f"Bearer {self._mcp_token}"

        target_tool = TOOL_NAME_ALIAS.get(tool_name, tool_name)
        async with streamablehttp_client(
            self._mcp_url,
            headers=headers or None,
            timeout=self._timeout_sec,
            sse_read_timeout=max(self._timeout_sec * 2, 30.0),
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(target_tool, params)
                return self._parse_mcp_result(result)

    def _parse_mcp_result(self, result: Any) -> Dict[str, Any]:
        is_error = bool(getattr(result, "isError", False))

        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            payload = dict(structured)
            if is_error:
                payload.setdefault("success", False)
            return payload
        if structured is not None:
            return {"success": not is_error, "data": structured}

        content = getattr(result, "content", None) or []
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
            else:
                text = str(getattr(item, "text", "")).strip()
            if text:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = {"raw_response": text}
                if isinstance(parsed, dict):
                    if is_error:
                        parsed.setdefault("success", False)
                    return parsed
                return {"data": parsed, "success": not is_error}

        return {"success": not is_error}

    def _normalize_remote_result(self, tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"success": False, "error_code": "UPSTREAM_ERROR", "status_code": 502}

        data = payload.get("data")
        if isinstance(data, dict):
            merged = dict(data)
            if "success" not in merged and "success" in payload:
                merged["success"] = payload["success"]
        else:
            merged = dict(payload)

        if not bool(merged.get("success", True)):
            return self._normalize_remote_error(merged)

        if tool_name == "ha_search_entities":
            results = merged.get("results", [])
            entities: List[Dict[str, Any]] = []
            if isinstance(results, list):
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    entity_id = str(item.get("entity_id", ""))
                    if not entity_id:
                        continue
                    entities.append(
                        {
                            "entity_id": entity_id,
                            "name": str(item.get("friendly_name") or item.get("name") or entity_id),
                            "area": str(item.get("area") or item.get("area_name") or ""),
                            "state": item.get("state"),
                            "score": float(item.get("score", 0.0)),
                        }
                    )
            return {"success": True, "status_code": 200, "entities": entities}

        if tool_name == "ha_get_entity":
            entry = merged.get("entity_entry")
            if not isinstance(entry, dict):
                entries = merged.get("entity_entries")
                if isinstance(entries, list) and entries:
                    entry = entries[0] if isinstance(entries[0], dict) else None
            if not isinstance(entry, dict):
                return self._normalize_remote_error(
                    {
                        "success": False,
                        "error": "Entity entry not found",
                        "error_code": "ENTITY_NOT_FOUND",
                    }
                )
            entity_id = str(entry.get("entity_id", merged.get("entity_id", "")))
            return {
                "success": True,
                "status_code": 200,
                "entity": {
                    "entity_id": entity_id,
                    "name": entry.get("name") or entry.get("original_name") or entity_id,
                    "area": entry.get("area_id") or "",
                    "state": entry.get("state"),
                },
            }

        if tool_name in {"ha_create_backup", "ha_backup_create"}:
            return {
                "success": True,
                "status_code": 200,
                "backup_id": merged.get("backup_id") or merged.get("backup_job_id"),
            }

        if tool_name == "ha_call_service":
            return {
                "success": True,
                "status_code": 200,
                "state": merged.get("verified_state"),
                "message": merged.get("message"),
                "entity_id": merged.get("entity_id"),
                "partial": bool(merged.get("partial", False)),
                "warning": merged.get("warning"),
            }

        return {"success": True, "status_code": 200, **merged}

    def _normalize_remote_error(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw_error_code = _extract_remote_error_code(payload)
        message = _extract_remote_error_message(payload)
        status_code = _extract_remote_status_code(payload)
        error_code = _map_remote_error_code(raw_error_code, message, status_code)
        if status_code is None:
            status_code = _default_status_code(error_code)

        return {
            "success": False,
            "error_code": error_code,
            "status_code": int(status_code),
            "error": message,
        }

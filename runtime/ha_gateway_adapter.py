from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List


GatewayRunner = Callable[[str, Dict[str, Any]], Dict[str, Any]]

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


def _error_to_runtime_code(message: str) -> str:
    text = (message or "").lower()
    if "not found" in text:
        return "ENTITY_NOT_FOUND"
    if "timeout" in text:
        return "UPSTREAM_TIMEOUT"
    if "unauthorized" in text or "forbidden" in text or "permission" in text:
        return "FORBIDDEN"
    if "bad request" in text or "invalid" in text or "missing" in text:
        return "BAD_REQUEST"
    return "UPSTREAM_ERROR"


def _status_from_code(code: str) -> int:
    if code in {"ENTITY_NOT_FOUND", "NOT_FOUND"}:
        return 404
    if code == "FORBIDDEN":
        return 403
    if code == "BAD_REQUEST":
        return 400
    if code == "UPSTREAM_TIMEOUT":
        return 504
    return 502


class HaGatewayAdapter:
    """Adapter that talks to ha_gateway over WebSocket protocol."""

    def __init__(
        self,
        entities: List[Dict[str, Any]] | None = None,
        *,
        gateway_url: str | None = None,
        timeout_sec: float = 8.0,
        gateway_runner: GatewayRunner | None = None,
        entity_cache_ttl_sec: float = 5.0,
        state_poll_timeout_sec: float = 1.5,
        state_poll_interval_sec: float = 0.2,
    ) -> None:
        self._gateway_url = (gateway_url or os.getenv("SMARTHOME_HA_GATEWAY_URL") or "").strip()
        self._timeout_sec = float(timeout_sec)
        self._gateway_runner = gateway_runner
        self._entity_cache_ttl_sec = max(1.0, float(entity_cache_ttl_sec))
        self._state_poll_timeout_sec = max(0.0, float(state_poll_timeout_sec))
        self._state_poll_interval_sec = max(0.05, float(state_poll_interval_sec))

        self.mode = "ha_gateway" if (self._gateway_url or gateway_runner is not None) else "stub"
        self.service_call_count = 0
        self.backup_call_count = 0

        self._entities: List[Dict[str, Any]] = (
            [dict(item) for item in (entities or DEFAULT_ENTITIES)] if self.mode == "stub" else []
        )
        self._entity_cache_updated_at = 0.0

    def get_all_entities(self) -> List[Dict[str, Any]]:
        if self.mode == "ha_gateway":
            self._refresh_entities(force=False)
        return [dict(item) for item in self._entities]

    def search_entities(self, query: str, domain: str | None = None, limit: int = 3) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 5))
        query = str(query or "").strip()

        entities = self.get_all_entities()
        if domain:
            entities = [item for item in entities if str(item.get("entity_id", "")).startswith(f"{domain}.")]

        if not query:
            return [dict(item, score=1.0) for item in entities[:limit]]

        scored: List[tuple[float, Dict[str, Any]]] = []
        query_lower = query.lower()

        for entity in entities:
            entity_id = str(entity.get("entity_id", ""))
            haystack = f"{entity.get('name', '')}{entity.get('area', '')}{entity_id}".lower()
            score = SequenceMatcher(None, query_lower, haystack).ratio()
            if query_lower in haystack:
                score += 0.3
            elif query_lower and all(char in haystack for char in query_lower):
                score += 0.2
            if score >= 0.35:
                scored.append((min(score, 1.0), entity))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [dict(item, score=round(score, 3)) for score, item in scored[:limit]]

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

        if self.mode == "stub":
            if not entity_id:
                return {
                    "success": False,
                    "error_code": "BAD_REQUEST",
                    "status_code": 400,
                    "error": "entity_id is required",
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
            elif domain == "switch":
                if service == "turn_on":
                    entity["state"] = "on"
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

        if not entity_id:
            return {
                "success": False,
                "error_code": "BAD_REQUEST",
                "status_code": 400,
                "error": "entity_id is required",
            }

        payload: Dict[str, Any] = {
            "domain": domain,
            "service": service,
            "service_data": dict(params),
            "target": {"entity_id": entity_id},
        }

        call = self._gateway_call("call_service", payload)
        if not call.get("success"):
            return {
                "success": False,
                "error_code": str(call.get("error_code", "UPSTREAM_ERROR")),
                "status_code": int(call.get("status_code", 502)),
                "entity_id": entity_id,
                "error": str(call.get("error", "gateway error")),
            }

        desired_state = self._infer_desired_state(domain=domain, service=service, params=params)
        state_obj = self._wait_for_expected_state(entity_id=entity_id, desired_state=desired_state)
        state_value: Any = state_obj.get("state") if isinstance(state_obj, dict) else None
        applied = None
        if desired_state is not None and state_value is not None:
            applied = self._state_matches(state_value, desired_state)

        return {
            "success": True,
            "status_code": 200,
            "entity_id": entity_id,
            "state": state_value,
            "desired_state": desired_state,
            "applied": applied,
            "params": params,
        }

    def _infer_desired_state(self, *, domain: str, service: str, params: Dict[str, Any]) -> Any | None:
        service_norm = str(service or "").strip().lower()
        domain_norm = str(domain or "").strip().lower()

        direct_map = {
            "turn_on": "on",
            "turn_off": "off",
            "lock": "locked",
            "unlock": "unlocked",
            "open_cover": "open",
            "close_cover": "closed",
        }
        if service_norm in direct_map:
            return direct_map[service_norm]

        if domain_norm in {"select", "input_select"} and service_norm == "select_option":
            option = params.get("option")
            if isinstance(option, str) and option.strip():
                return option.strip()

        return None

    def _state_matches(self, actual_state: Any, desired_state: Any) -> bool:
        if isinstance(actual_state, str) and isinstance(desired_state, str):
            return actual_state.strip().lower() == desired_state.strip().lower()
        return actual_state == desired_state

    def _get_entity_state_snapshot(self, entity_id: str) -> Dict[str, Any] | None:
        state_resp = self._gateway_call("get_state", {"entity_id": entity_id})
        if not state_resp.get("success"):
            return None

        state_obj = state_resp.get("data", {}).get("state")
        if not isinstance(state_obj, dict):
            return None

        self._upsert_entity_from_state(state_obj)
        return state_obj

    def _wait_for_expected_state(self, *, entity_id: str, desired_state: Any | None) -> Dict[str, Any] | None:
        latest_state = self._get_entity_state_snapshot(entity_id)
        if desired_state is None:
            return latest_state

        if latest_state is not None and self._state_matches(latest_state.get("state"), desired_state):
            return latest_state

        if self._state_poll_timeout_sec <= 0:
            return latest_state

        deadline = time.monotonic() + self._state_poll_timeout_sec
        while time.monotonic() < deadline:
            time.sleep(self._state_poll_interval_sec)
            snapshot = self._get_entity_state_snapshot(entity_id)
            if snapshot is not None:
                latest_state = snapshot
            if latest_state is not None and self._state_matches(latest_state.get("state"), desired_state):
                return latest_state

        return latest_state

    def tool_call(self, tool_name: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        params = params or {}

        if self.mode == "stub":
            if tool_name == "ha_get_entity":
                entity_id = str(params.get("entity_id", "")).strip()
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
                domain = params.get("domain_filter") or params.get("domain")
                limit = int(params.get("limit", 3)) if str(params.get("limit", "")).strip() else 3
                entities = self.search_entities(query=query, domain=domain, limit=limit)
                return {"success": True, "status_code": 200, "entities": entities}

            if tool_name in {"ha_create_backup", "ha_backup_create"}:
                self.backup_call_count += 1
                return {"success": True, "status_code": 200, "backup_id": "bk_001"}

            if tool_name == "ha_call_service":
                domain = str(params.get("domain", "")).strip()
                service = str(params.get("service", "")).strip()
                entity_id = str(params.get("entity_id", "")).strip()
                data = params.get("data") if isinstance(params.get("data"), dict) else {}
                return self.call_service(domain=domain, service=service, entity_id=entity_id, params=data)

            return {"success": False, "status_code": 400, "error_code": "BAD_REQUEST"}

        if tool_name == "ha_get_entity":
            entity_id = str(params.get("entity_id", "")).strip()
            if not entity_id:
                return {"success": False, "status_code": 400, "error_code": "BAD_REQUEST"}

            resp = self._gateway_call("get_state", {"entity_id": entity_id})
            if not resp.get("success"):
                return {
                    "success": False,
                    "status_code": int(resp.get("status_code", 404)),
                    "error_code": str(resp.get("error_code", "ENTITY_NOT_FOUND")),
                    "entity_id": entity_id,
                }

            state_obj = resp.get("data", {}).get("state")
            if not isinstance(state_obj, dict):
                return {
                    "success": False,
                    "status_code": 404,
                    "error_code": "ENTITY_NOT_FOUND",
                    "entity_id": entity_id,
                }

            self._upsert_entity_from_state(state_obj)
            attributes = state_obj.get("attributes", {}) if isinstance(state_obj.get("attributes"), dict) else {}
            area = attributes.get("area") or attributes.get("area_name") or ""
            name = attributes.get("friendly_name") or entity_id
            return {
                "success": True,
                "status_code": 200,
                "entity": {
                    "entity_id": entity_id,
                    "name": str(name),
                    "area": str(area),
                    "state": state_obj.get("state"),
                },
            }

        if tool_name == "ha_search_entities":
            query = str(params.get("query", ""))
            domain = params.get("domain_filter") or params.get("domain")
            limit = int(params.get("limit", 3)) if str(params.get("limit", "")).strip() else 3
            entities = self.search_entities(query=query, domain=domain, limit=limit)
            return {"success": True, "status_code": 200, "entities": entities}

        if tool_name in {"ha_create_backup", "ha_backup_create"}:
            self.backup_call_count += 1
            backup_name = str(params.get("name", "")).strip()
            service_data: Dict[str, Any] = {}
            if backup_name:
                service_data["name"] = backup_name

            resp = self._gateway_call(
                "call_service",
                {
                    "domain": "backup",
                    "service": "create",
                    "service_data": service_data,
                },
            )
            if not resp.get("success"):
                return {
                    "success": False,
                    "status_code": int(resp.get("status_code", 502)),
                    "error_code": str(resp.get("error_code", "UPSTREAM_ERROR")),
                    "error": str(resp.get("error", "gateway error")),
                }
            return {"success": True, "status_code": 200, "backup_id": None}

        if tool_name == "ha_call_service":
            domain = str(params.get("domain", "")).strip()
            service = str(params.get("service", "")).strip()
            entity_id = str(params.get("entity_id", "")).strip()
            data = params.get("data") if isinstance(params.get("data"), dict) else {}
            return self.call_service(domain=domain, service=service, entity_id=entity_id, params=data)

        return {"success": False, "status_code": 400, "error_code": "BAD_REQUEST"}

    def _refresh_entities(self, *, force: bool) -> None:
        if self.mode != "ha_gateway":
            return

        now = time.time()
        if not force and self._entities and (now - self._entity_cache_updated_at) < self._entity_cache_ttl_sec:
            return

        resp = self._gateway_call("discover", {})
        if not resp.get("success"):
            return

        data = resp.get("data")
        devices = data.get("devices", []) if isinstance(data, dict) else []

        normalized: Dict[str, Dict[str, Any]] = {}
        for item in devices:
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get("entity_id", "")).strip()
            if not entity_id:
                continue
            attributes = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
            normalized[entity_id] = {
                "entity_id": entity_id,
                "name": str(item.get("name") or attributes.get("friendly_name") or entity_id),
                "area": str(item.get("area") or attributes.get("area") or attributes.get("area_name") or ""),
                "state": item.get("state"),
            }

        self._entities = list(normalized.values())
        self._entity_cache_updated_at = now

    def _find_entity(self, entity_id: str) -> Dict[str, Any] | None:
        for entity in self._entities:
            if entity.get("entity_id") == entity_id:
                return entity
        return None

    def _upsert_entity_from_state(self, state_obj: Dict[str, Any]) -> None:
        entity_id = str(state_obj.get("entity_id", "")).strip()
        if not entity_id:
            return

        attributes = state_obj.get("attributes", {}) if isinstance(state_obj.get("attributes"), dict) else {}
        entry = {
            "entity_id": entity_id,
            "name": str(attributes.get("friendly_name") or entity_id),
            "area": str(attributes.get("area") or attributes.get("area_name") or ""),
            "state": state_obj.get("state"),
        }

        for index, item in enumerate(self._entities):
            if item.get("entity_id") == entity_id:
                self._entities[index] = entry
                break
        else:
            self._entities.append(entry)

        self._entity_cache_updated_at = time.time()

    def _gateway_call(self, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._gateway_runner is not None:
            try:
                raw = self._gateway_runner(message_type, dict(payload))
            except TimeoutError:
                return {
                    "success": False,
                    "error_code": "UPSTREAM_TIMEOUT",
                    "status_code": 504,
                    "error": "gateway timeout",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "error_code": "UPSTREAM_ERROR",
                    "status_code": 502,
                    "error": str(exc),
                }
            return self._normalize_gateway_response(raw)

        if not self._gateway_url:
            return {
                "success": False,
                "error_code": "UPSTREAM_ERROR",
                "status_code": 502,
                "error": "SMARTHOME_HA_GATEWAY_URL is not configured",
            }

        try:
            raw = asyncio.run(self._gateway_request(message_type, payload))
        except TimeoutError:
            return {
                "success": False,
                "error_code": "UPSTREAM_TIMEOUT",
                "status_code": 504,
                "error": "gateway timeout",
            }
        except ImportError as exc:
            return {
                "success": False,
                "error_code": "UPSTREAM_ERROR",
                "status_code": 502,
                "error": f"websocket client unavailable: {exc}",
            }
        except Exception as exc:
            return {
                "success": False,
                "error_code": "UPSTREAM_ERROR",
                "status_code": 502,
                "error": str(exc),
            }

        return self._normalize_gateway_response(raw)

    async def _gateway_request(self, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        import websockets

        request_id = f"req_{uuid.uuid4().hex}"
        request = {
            "type": message_type,
            "id": request_id,
            "payload": payload,
        }

        async with websockets.connect(
            self._gateway_url,
            open_timeout=self._timeout_sec,
            close_timeout=self._timeout_sec,
            ping_interval=None,
        ) as ws:
            await ws.send(json.dumps(request, ensure_ascii=False))

            deadline = asyncio.get_running_loop().time() + self._timeout_sec
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"gateway timeout for {message_type}")

                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")

                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    continue

                if str(msg.get("id", "")) != request_id:
                    continue

                return msg

    def _normalize_gateway_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "success": False,
                "error_code": "UPSTREAM_ERROR",
                "status_code": 502,
                "error": "invalid gateway response",
            }

        # Raw gateway protocol message format
        if "type" in payload and "payload" in payload:
            msg_type = str(payload.get("type", ""))
            body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}

            if msg_type == "response":
                if bool(body.get("success", False)):
                    return {
                        "success": True,
                        "status_code": 200,
                        "data": body.get("data"),
                    }

                message = str(body.get("error") or "gateway response failed")
                error_code = _error_to_runtime_code(message)
                return {
                    "success": False,
                    "error_code": error_code,
                    "status_code": _status_from_code(error_code),
                    "error": message,
                }

            if msg_type == "error":
                message = str(body.get("error") or "gateway error")
                error_code = _error_to_runtime_code(message)
                return {
                    "success": False,
                    "error_code": error_code,
                    "status_code": _status_from_code(error_code),
                    "error": message,
                }

        # Direct normalized format (used by tests/mocks)
        if "success" in payload:
            success = bool(payload.get("success", False))
            if success:
                return {
                    "success": True,
                    "status_code": int(payload.get("status_code", 200)),
                    "data": payload.get("data"),
                }

            message = str(payload.get("error") or payload.get("message") or "gateway request failed")
            error_code = str(payload.get("error_code") or _error_to_runtime_code(message))
            return {
                "success": False,
                "error_code": error_code,
                "status_code": int(payload.get("status_code", _status_from_code(error_code))),
                "error": message,
            }

        return {
            "success": False,
            "error_code": "UPSTREAM_ERROR",
            "status_code": 502,
            "error": "unrecognized gateway response format",
        }

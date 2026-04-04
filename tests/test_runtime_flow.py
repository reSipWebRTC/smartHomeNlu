import unittest
from typing import Any, Dict, List

from runtime import SmartHomeRuntime
from runtime.observability import REQUIRED_AUDIT_FIELDS


class EntityListAdapter:
    def __init__(self) -> None:
        self.mode = "stub"
        self.service_call_count = 0
        self.backup_call_count = 0
        self._entities: List[Dict[str, Any]] = [
            {"entity_id": "sun.sun", "name": "Sun", "area": "", "state": "above_horizon"},
            {"entity_id": "update.home_assistant_core_update", "name": "HA Core Update", "area": "", "state": "on"},
            {"entity_id": "light.kitchen_main", "name": "厨房主灯", "area": "厨房", "state": "off"},
            {"entity_id": "switch.coffee_machine", "name": "咖啡机", "area": "厨房", "state": "off"},
            {"entity_id": "climate.living_room_ac", "name": "客厅空调", "area": "客厅", "state": "off"},
        ]

    def get_all_entities(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._entities]

    def search_entities(self, query: str, domain: str | None = None, limit: int = 3) -> List[Dict[str, Any]]:
        query_norm = str(query or "").strip()
        rows = []
        for item in self._entities:
            entity_id = str(item.get("entity_id", ""))
            if domain and not entity_id.startswith(f"{domain}."):
                continue
            if query_norm and query_norm not in f"{item.get('name', '')}{entity_id}":
                continue
            rows.append(dict(item, score=1.0))
        return rows[: max(1, int(limit))]

    def call_service(self, **_: Any) -> Dict[str, Any]:
        self.service_call_count += 1
        return {"success": True, "status_code": 200}

    def tool_call(self, *_: Any, **__: Any) -> Dict[str, Any]:
        return {"success": True, "status_code": 200}


class SameNameSwitchAdapter:
    def __init__(self) -> None:
        self.mode = "ha_mcp"
        self.service_call_count = 0
        self.backup_call_count = 0
        self.calls: List[Dict[str, Any]] = []
        self._entities: List[Dict[str, Any]] = [
            {"entity_id": "switch.tyzxl_plug", "name": "TYZXl鹊起 延长线插座 None", "area": "", "state": "off"},
            {"entity_id": "switch.tyzxl_plug_2", "name": "TYZXl鹊起 延长线插座 None", "area": "", "state": "off"},
            {"entity_id": "switch.tyzxl_plug_3", "name": "TYZXl鹊起 延长线插座 None", "area": "", "state": "off"},
        ]

    def get_all_entities(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._entities]

    def search_entities(self, query: str, domain: str | None = None, limit: int = 3) -> List[Dict[str, Any]]:
        rows = []
        for item in self._entities:
            entity_id = str(item.get("entity_id", ""))
            if domain and not entity_id.startswith(f"{domain}."):
                continue
            rows.append(dict(item, score=0.92))
        return rows[: max(1, int(limit))]

    def call_service(
        self,
        *,
        domain: str,
        service: str,
        entity_id: str,
        params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        self.service_call_count += 1
        self.calls.append({"domain": domain, "service": service, "entity_id": entity_id, "params": dict(params or {})})
        return {"success": True, "status_code": 200, "entity_id": entity_id}

    def tool_call(self, *_: Any, **__: Any) -> Dict[str, Any]:
        return {"success": True, "status_code": 200}


class SparseSameNameSwitchAdapter(SameNameSwitchAdapter):
    def search_entities(self, query: str, domain: str | None = None, limit: int = 3) -> List[Dict[str, Any]]:
        query_norm = str(query or "").strip().lower()
        rows: List[Dict[str, Any]] = []
        if "tyzxl鹊起" in query_norm or "none" in query_norm:
            rows = [dict(item, score=0.95) for item in self._entities]
        else:
            rows = [dict(self._entities[0], score=0.91)]

        if domain:
            rows = [item for item in rows if str(item.get("entity_id", "")).startswith(f"{domain}.")]
        return rows[: max(1, int(limit))]


class RuntimeFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = SmartHomeRuntime()

    def test_health_endpoint(self) -> None:
        resp = self.runtime.get_api_v1_health()
        self.assertEqual(resp["code"], "OK")
        self.assertEqual(resp["data"]["status"], "up")

    def test_brightness_command_success(self) -> None:
        resp = self.runtime.post_api_v1_command(
            {
                "session_id": "sess_001",
                "user_id": "usr_001",
                "text": "把客厅灯调到50%",
                "channel": "voice",
            }
        )
        self.assertEqual(resp["code"], "OK")
        self.assertEqual(resp["data"]["status"], "ok")
        self.assertEqual(resp["data"]["intent"], "CONTROL")
        self.assertEqual(resp["data"]["sub_intent"], "adjust_brightness")

        events = self.runtime.event_bus.events("evt.execution.result.v1")
        self.assertGreaterEqual(len(events), 1)
        for field in ("status", "error_code", "latency_ms", "tool_name", "entity_id"):
            self.assertIn(field, events[-1])

    def test_query_command_success(self) -> None:
        resp = self.runtime.post_api_v1_command(
            {
                "session_id": "sess_query_001",
                "user_id": "usr_query_001",
                "text": "查询客厅空调状态",
            }
        )
        self.assertEqual(resp["code"], "OK")
        self.assertEqual(resp["data"]["intent"], "QUERY")
        self.assertEqual(resp["data"]["sub_intent"], "query_status")

        events = self.runtime.event_bus.events("evt.execution.result.v1")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[-1]["tool_name"], "ha_get_entity")
        self.assertEqual(events[-1]["status"], "success")

    def test_idempotency_window(self) -> None:
        req = {
            "session_id": "sess_002",
            "user_id": "usr_002",
            "text": "把客厅灯调到50%",
        }
        first = self.runtime.post_api_v1_command(req)
        second = self.runtime.post_api_v1_command(req)

        self.assertEqual(first["code"], "OK")
        self.assertEqual(second["code"], "OK")
        self.assertTrue(second["data"].get("idempotent_hit"))
        self.assertEqual(self.runtime.adapter.service_call_count, 1)

    def test_high_risk_confirm_flow(self) -> None:
        first = self.runtime.post_api_v1_command(
            {
                "session_id": "sess_003",
                "user_id": "usr_003",
                "text": "把前门解锁",
                "user_role": "normal_user",
            }
        )
        self.assertEqual(first["code"], "POLICY_CONFIRM_REQUIRED")
        token = first["data"].get("confirm_token")
        self.assertIsNotNone(token)

        second = self.runtime.post_api_v1_confirm(
            {
                "confirm_token": token,
                "accept": True,
            }
        )
        self.assertEqual(second["code"], "OK")
        self.assertEqual(second["data"]["status"], "ok")

    def test_rbac_blocks_backup_for_normal_user(self) -> None:
        resp = self.runtime.post_api_v1_command(
            {
                "session_id": "sess_004",
                "user_id": "usr_004",
                "text": "备份一下HA",
                "user_role": "normal_user",
            }
        )
        self.assertEqual(resp["code"], "FORBIDDEN")

    def test_low_confidence_clarify_and_streak(self) -> None:
        req = {
            "session_id": "sess_005",
            "user_id": "usr_005",
            "text": "帮我弄一下这个",
        }
        r1 = self.runtime.post_api_v1_command(req)
        r2 = self.runtime.post_api_v1_command(req)
        r3 = self.runtime.post_api_v1_command(req)

        self.assertEqual(r1["data"]["status"], "clarify")
        self.assertEqual(r2["data"]["status"], "clarify")
        self.assertIn("连续三次", r3["data"]["reply_text"])

    def test_main_low_confidence_collects_hard_example(self) -> None:
        resp = self.runtime.post_api_v1_command(
            {
                "session_id": "sess_007",
                "user_id": "usr_007",
                "text": "把客厅灯调亮",
            }
        )
        self.assertEqual(resp["code"], "OK")

        events = self.runtime.event_bus.events("evt.data.hard_example.v1")
        low_conf = [evt for evt in events if evt.get("sample_type") == "low_confidence"]
        self.assertGreaterEqual(len(low_conf), 1)
        self.assertEqual(low_conf[-1]["reason"], "main_low_confidence")

    def test_entity_not_found_collects_hard_example(self) -> None:
        self.runtime.entity_resolver.reindex([])
        resp = self.runtime.post_api_v1_command(
            {
                "session_id": "sess_008",
                "user_id": "usr_008",
                "text": "查询客厅空调状态",
            }
        )
        self.assertEqual(resp["code"], "ENTITY_NOT_FOUND")

        events = self.runtime.event_bus.events("evt.data.hard_example.v1")
        failures = [evt for evt in events if evt.get("sample_type") == "execution_failure"]
        self.assertGreaterEqual(len(failures), 1)
        self.assertEqual(failures[-1]["error_code"], "ENTITY_NOT_FOUND")

    def test_audit_log_required_fields(self) -> None:
        self.runtime.post_api_v1_command(
            {
                "session_id": "sess_006",
                "user_id": "usr_006",
                "text": "把客厅灯调到45%",
            }
        )
        latest = self.runtime.observability.audit_logs[-1]
        self.assertTrue(REQUIRED_AUDIT_FIELDS.issubset(set(latest.keys())))

    def test_entity_resolver_top_k_cap(self) -> None:
        candidates = self.runtime.entity_resolver.resolve(
            trace_id="trc_test",
            slots={"device_type": "灯"},
            top_k=10,
        )
        self.assertLessEqual(len(candidates), 5)

    def test_entities_endpoint_hides_default_ha_entities(self) -> None:
        runtime = SmartHomeRuntime(adapter=EntityListAdapter())

        hidden = runtime.get_api_v1_entities(query="", limit=2, hide_default=True)
        self.assertEqual(hidden["code"], "OK")
        self.assertEqual(hidden["data"]["total"], 3)
        self.assertEqual(hidden["data"]["count"], 2)
        self.assertTrue(hidden["data"]["has_more"])
        hidden_ids = [item["entity_id"] for item in hidden["data"]["items"]]
        self.assertNotIn("sun.sun", hidden_ids)
        self.assertNotIn("update.home_assistant_core_update", hidden_ids)

        shown = runtime.get_api_v1_entities(query="", limit=10, hide_default=False)
        self.assertEqual(shown["code"], "OK")
        shown_ids = [item["entity_id"] for item in shown["data"]["items"]]
        self.assertIn("sun.sun", shown_ids)
        self.assertIn("update.home_assistant_core_update", shown_ids)

    def test_same_name_devices_require_index_hint(self) -> None:
        adapter = SameNameSwitchAdapter()
        runtime = SmartHomeRuntime(adapter=adapter)

        ambiguous = runtime.post_api_v1_command(
            {
                "session_id": "sess_same_name_001",
                "user_id": "usr_same_name_001",
                "text": "打开TYZXl鹊起 延长线插座 None",
            }
        )
        self.assertEqual(ambiguous["code"], "OK")
        self.assertEqual(ambiguous["data"]["status"], "clarify")
        self.assertIn("第1路/第2路/第3路", ambiguous["data"]["reply_text"])
        self.assertEqual(adapter.service_call_count, 0)

        targeted = runtime.post_api_v1_command(
            {
                "session_id": "sess_same_name_002",
                "user_id": "usr_same_name_002",
                "text": "打开TYZXl鹊起 延长线插座 第2路",
            }
        )
        self.assertEqual(targeted["code"], "OK")
        self.assertEqual(targeted["data"]["status"], "ok")
        self.assertEqual(adapter.service_call_count, 1)
        self.assertEqual(adapter.calls[-1]["entity_id"], "switch.tyzxl_plug_2")

    def test_sparse_candidate_list_still_supports_route_hint(self) -> None:
        adapter = SparseSameNameSwitchAdapter()
        runtime = SmartHomeRuntime(adapter=adapter)

        ambiguous = runtime.post_api_v1_command(
            {
                "session_id": "sess_sparse_same_name_001",
                "user_id": "usr_sparse_same_name_001",
                "text": "打开TYZXl鹊起 延长线插座 None",
            }
        )
        self.assertEqual(ambiguous["code"], "OK")
        self.assertEqual(ambiguous["data"]["status"], "clarify")
        self.assertEqual(adapter.service_call_count, 0)

        targeted = runtime.post_api_v1_command(
            {
                "session_id": "sess_sparse_same_name_002",
                "user_id": "usr_sparse_same_name_002",
                "text": "打开TYZXl鹊起 延长线插座 None 第二路",
            }
        )
        self.assertEqual(targeted["code"], "OK")
        self.assertEqual(targeted["data"]["status"], "ok")
        self.assertEqual(adapter.service_call_count, 1)
        self.assertEqual(adapter.calls[-1]["entity_id"], "switch.tyzxl_plug_2")


if __name__ == "__main__":
    unittest.main()

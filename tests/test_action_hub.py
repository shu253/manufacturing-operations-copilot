from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from api.action_hub import ActionHub
from api.ai_store import AIAuditStore
from api.store import OperationalStore
from api.assistant_service import DifyClient
from business_engine import BusinessEngine, SQLiteRepository


ROOT = Path(__file__).resolve().parents[1]


class ActionHubTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "demo.sqlite3"
        shutil.copy2(ROOT / "data" / "huadong_jinggong_demo.sqlite3", self.database)
        self.audit = AIAuditStore(self.database)
        self.store = OperationalStore(self.database)
        self.hub = ActionHub(self.database, self.audit, self.store)
        with sqlite3.connect(self.database) as connection:
            connection.execute("DELETE FROM agent_identity_bindings")
            connection.execute("DELETE FROM outbound_notifications")
            connection.execute("DELETE FROM management_action_messages")
            connection.execute("DELETE FROM ai_operation_audit")
            connection.commit()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_weekly_and_monthly_periods_are_real(self) -> None:
        engine = BusinessEngine(SQLiteRepository(self.database))
        weekly = engine.generate_business_report("weekly", "2026-08-05")
        monthly = engine.generate_business_report("monthly", "2026-08-05")
        self.assertEqual(weekly.result["period_start"], "2026-08-03")
        self.assertEqual(weekly.result["period_end"], "2026-08-05")
        self.assertEqual(monthly.result["period_start"], "2026-08-01")
        self.assertIn("period_metrics", weekly.result)
        self.assertNotEqual(weekly.result["period_start"], monthly.result["period_start"])

    def test_identity_confirmation_delivery_and_receipt(self) -> None:
        owner = self.hub.upsert_binding({
            "employee_id": 1,
            "feishu_open_id": "ou_owner_test",
            "access_role": "owner",
        })
        recipient = self.hub.upsert_binding({
            "employee_id": 5,
            "feishu_open_id": "ou_procurement_test",
            "access_role": "department_head",
            "department_id": 5,
            "actor_open_id": "ou_owner_test",
        })
        self.assertTrue(owner["can_use_agent"])
        self.assertFalse(recipient["can_use_agent"])
        task = self.store.list_tasks(limit=1)[0]
        conversation_id = self.audit.ensure_conversation(
            None, "ou_owner_test", "management", "test", "test", "test"
        )
        proposal = self.hub.propose_message({
            "actor_open_id": "ou_owner_test",
            "task_code": task["task_code"],
            "recipient_employee_id": 5,
            "message_title": "采购交期确认",
            "message_body": "请确认关键物料最新交期并反馈。",
            "conversation_id": conversation_id,
        })
        self.assertTrue(proposal["confirmation_required"])
        confirmation = self.audit.consume_confirmation(proposal["confirmation_token"])

        def fake_send(notification_id):
            return {"notification_id": notification_id, "status": "sent"}

        with patch.object(self.hub, "send_notification", side_effect=fake_send):
            delivered = self.hub.execute_confirmed_message(confirmation)
        notification_id = delivered["notification"]["notification_id"]
        receipt = self.hub.receive_feedback(
            notification_id, "ou_procurement_test", "acknowledge"
        )
        self.assertEqual(receipt["status"], "acknowledged")
        feedback = self.hub.receive_feedback(
            notification_id, "ou_procurement_test", "feedback", "供应商正在确认"
        )
        self.assertEqual(feedback["feedback_text"], "供应商正在确认")
        self.assertTrue(self.hub.list_operations())

    def test_usage_summary_aggregates_tokens_and_cost(self) -> None:
        conversation_id = self.audit.ensure_conversation(
            None, "u", "management", "tongyi", "qwen", "v1"
        )
        self.audit.log_message(
            conversation_id=conversation_id,
            trace_id="trace-usage-test",
            message_role="assistant",
            content="ok",
            token_input=120,
            token_output=30,
            token_total=150,
            model_cost=0.0123,
            model_cost_currency="CNY",
        )
        summary = self.audit.usage_summary()
        self.assertGreaterEqual(summary["totals"]["input_tokens"], 120)
        self.assertGreaterEqual(summary["totals"]["output_tokens"], 30)
        self.assertGreaterEqual(float(summary["totals"]["total_cost"]), 0.0123)

    def test_management_report_action_is_confirmed_with_one_click(self) -> None:
        self.hub.upsert_binding({
            "employee_id": 1,
            "feishu_open_id": "ou_owner_test",
            "access_role": "owner",
        })
        self.hub.upsert_binding({
            "employee_id": 5,
            "feishu_open_id": "ou_procurement_test",
            "access_role": "department_head",
            "department_id": 5,
        })
        conversation_id = self.audit.ensure_conversation(
            None, "feishu:ou_owner_test", "management", "test", "test", "test"
        )
        proposals = self.hub.prepare_management_actions(
            trace_id="trace-management-action",
            conversation_id=conversation_id,
            actor_open_id="ou_owner_test",
            actions=[
                {
                    "priority": 2,
                    "action": "确认缺料补齐计划",
                    "owner": "采购部",
                },
                {
                    "priority": 4,
                    "action": "催收高风险应收",
                    "owner": "财务/销售",
                },
            ],
        )
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["recipient_employee_id"], 5)
        confirmation = self.audit.consume_confirmation(
            proposals[0]["confirmation_token"]
        )
        with patch("api.action_hub.threading.Thread") as thread_class:
            result = self.hub.execute_confirmed_management_action(confirmation)
        self.assertEqual(result["notification"]["status"], "pending")
        thread_class.return_value.start.assert_called_once()
        with self.assertRaises(Exception):
            self.audit.consume_confirmation(proposals[0]["confirmation_token"])

    def test_management_action_receipt_is_queued_for_owner_once(self) -> None:
        self.hub.upsert_binding({
            "employee_id": 1,
            "feishu_open_id": "ou_owner_test",
            "access_role": "owner",
        })
        self.hub.upsert_binding({
            "employee_id": 5,
            "feishu_open_id": "ou_procurement_test",
            "access_role": "department_head",
            "department_id": 5,
        })
        conversation_id = self.audit.ensure_conversation(
            None, "feishu:ou_owner_test", "management", "test", "test", "test"
        )
        proposal = self.hub.prepare_management_actions(
            trace_id="trace-owner-receipt",
            conversation_id=conversation_id,
            actor_open_id="ou_owner_test",
            actions=[{
                "priority": 2,
                "action": "确认缺料补齐计划",
                "owner": "采购部",
            }],
        )[0]
        confirmation = self.audit.consume_confirmation(
            proposal["confirmation_token"]
        )
        with patch("api.action_hub.threading.Thread"):
            delivery = self.hub.execute_confirmed_management_action(confirmation)
        source_notification_id = delivery["notification"]["notification_id"]

        with patch("api.action_hub.threading.Thread") as thread_class:
            receipt = self.hub.receive_feedback(
                source_notification_id,
                "ou_procurement_test",
                "acknowledge",
            )
        owner_notification = receipt["owner_notification"]
        self.assertEqual(owner_notification["recipient_open_id"], "ou_owner_test")
        self.assertEqual(owner_notification["requires_receipt"], 0)
        self.assertEqual(
            owner_notification["notification_kind"],
            "management_action_receipt_acknowledged",
        )
        thread_class.return_value.start.assert_called_once()
        card = self.hub._notification_card(owner_notification)
        self.assertFalse(
            any(item.get("tag") == "button" for item in card["body"]["elements"])
        )

        with patch("api.action_hub.threading.Thread") as duplicate_thread:
            duplicate = self.hub.receive_feedback(
                source_notification_id,
                "ou_procurement_test",
                "acknowledge",
            )
        self.assertEqual(
            duplicate["owner_notification"]["notification_id"],
            owner_notification["notification_id"],
        )
        duplicate_thread.assert_not_called()

        with patch("api.action_hub.threading.Thread") as feedback_thread:
            feedback = self.hub.receive_feedback(
                source_notification_id,
                "ou_procurement_test",
                "feedback",
                "需要协调",
            )
        self.assertEqual(
            feedback["owner_notification"]["notification_kind"],
            "management_action_receipt_feedback",
        )
        feedback_thread.return_value.start.assert_called_once()
        with sqlite3.connect(self.database) as connection:
            status = connection.execute(
                "SELECT status FROM management_action_messages "
                "WHERE management_action_id=?",
                (proposal["management_action_id"],),
            ).fetchone()[0]
        self.assertEqual(status, "feedback_received")

        with patch("api.action_hub.threading.Thread"):
            self.hub.receive_feedback(
                source_notification_id,
                "ou_procurement_test",
                "acknowledge",
            )
        with sqlite3.connect(self.database) as connection:
            status = connection.execute(
                "SELECT status FROM management_action_messages "
                "WHERE management_action_id=?",
                (proposal["management_action_id"],),
            ).fetchone()[0]
        self.assertEqual(status, "feedback_received")

    def test_dify_transient_error_is_retried(self) -> None:
        request = httpx.Request("POST", "https://api.dify.ai/v1/chat-messages")
        transient = httpx.Response(503, request=request)
        failed = httpx.HTTPStatusError("unavailable", request=request, response=transient)
        ok = MagicMock()
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"answer": "ok"}
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.side_effect = [failed, ok]
        with patch.dict(os.environ, {
            "DIFY_APP_API_KEY": "test-key",
            "DIFY_RETRY_COUNT": "2",
            "DIFY_RETRY_BACKOFF_SECONDS": "0",
        }), patch("api.assistant_service.httpx.Client", return_value=client):
            result = DifyClient().chat(
                question="test", as_of_date="2026-08-05",
                conversation_id=None, user_id="u", role="management",
                trace_id="trace-retry",
            )
        self.assertEqual(result["_gateway_attempts"], 2)
        self.assertEqual(client.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()

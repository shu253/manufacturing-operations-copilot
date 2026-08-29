from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from channels.feishu_core import (
    FeishuBotService,
    FeishuConfig,
    FeishuEventStore,
    FeishuMessage,
    configure_proxy_environment,
    parse_allowed_users,
    parse_sdk_message,
)


class FakeAssistant:
    def __init__(self) -> None:
        self.calls = []

    def query(self, message, role):
        self.calls.append((message, role))
        return {"answer": f"已分析：{message.question}"}


class FakeReplies:
    def __init__(self) -> None:
        self.items = []

    def reply_text(self, message_id, text):
        self.items.append((message_id, text))

    def reply_answer(self, message_id, question, result):
        self.items.append((message_id, result["answer"]))


class FeishuChannelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temp_directory.name) / "feishu-channel.sqlite3"
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def config(self, allowed_users=None) -> FeishuConfig:
        return FeishuConfig(
            app_id="cli_test",
            app_secret="secret",
            assistant_api="http://127.0.0.1:8000/api/v1/assistant/query",
            assistant_health_api="http://127.0.0.1:8000/api/v1/health",
            database_path=self.database_path,
            access_mode="allowlist",
            default_role="management",
            allowed_users=allowed_users or {},
            allow_p2p=True,
            allow_group_at=True,
            send_processing_message=True,
            worker_count=1,
            query_timeout_seconds=30,
            max_reply_chars=12000,
            trust_env_proxy=False,
            reply_format="card",
            card_template="blue",
            max_card_bytes=28000,
        )

    def test_allowed_user_parser(self) -> None:
        users = parse_allowed_users(
            "ou_manager:management, ou_buyer:procurement,ou_default",
            "finance",
        )
        self.assertEqual(users["ou_manager"], "management")
        self.assertEqual(users["ou_buyer"], "procurement")
        self.assertEqual(users["ou_default"], "finance")
        with self.assertRaises(ValueError):
            parse_allowed_users("ou_bad:administrator", "management")

    def test_direct_mode_bypasses_environment_proxy_for_feishu(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://127.0.0.1:9999",
                "https_proxy": "http://127.0.0.1:9999",
                "NO_PROXY": "example.com",
            },
            clear=False,
        ):
            configure_proxy_environment(self.config())
            self.assertNotIn("HTTPS_PROXY", os.environ)
            self.assertNotIn("https_proxy", os.environ)
            self.assertIn("open.feishu.cn", os.environ["NO_PROXY"])
            self.assertIn("127.0.0.1", os.environ["no_proxy"])

    def test_sdk_message_parsing_removes_group_mention(self) -> None:
        data = SimpleNamespace(
            header=SimpleNamespace(event_id="evt-001"),
            event=SimpleNamespace(
                sender=SimpleNamespace(
                    sender_type="user",
                    sender_id=SimpleNamespace(open_id="ou_001"),
                ),
                message=SimpleNamespace(
                    message_id="om_001",
                    chat_id="oc_001",
                    chat_type="group",
                    message_type="text",
                    content=json.dumps(
                        {"text": "@_user_1 销售-20260718-01为什么高风险？"},
                        ensure_ascii=False,
                    ),
                    mentions=[
                        SimpleNamespace(key="@_user_1", name="经营决策助手")
                    ],
                ),
            ),
        )
        message = parse_sdk_message(data)
        self.assertEqual(message.event_id, "evt-001")
        self.assertEqual(message.open_id, "ou_001")
        self.assertEqual(message.question, "销售-20260718-01为什么高风险？")
        self.assertEqual(
            message.conversation_id,
            "feishu:group:oc_001:ou_001",
        )

    def test_event_store_deduplicates_event_id(self) -> None:
        store = FeishuEventStore(self.database_path)
        message = FeishuMessage(
            event_id="evt-duplicate",
            message_id="om_001",
            chat_id="oc_001",
            chat_type="p2p",
            open_id="ou_001",
            sender_type="user",
            message_type="text",
            question="测试问题",
        )
        self.assertTrue(store.claim(message))
        self.assertFalse(store.claim(message))
        store.complete(message.event_id)

    def test_authorized_message_calls_assistant_and_replies(self) -> None:
        assistant = FakeAssistant()
        replies = FakeReplies()
        store = FeishuEventStore(self.database_path)
        service = FeishuBotService(
            self.config({"ou_001": "management"}),
            store,
            assistant,
            replies,
        )
        message = FeishuMessage(
            event_id="evt-authorized",
            message_id="om_001",
            chat_id="oc_001",
            chat_type="p2p",
            open_id="ou_001",
            sender_type="user",
            message_type="text",
            question="销售-20260718-01为什么高风险？",
        )
        self.assertTrue(store.claim(message))
        service.process(message)
        service.close()

        self.assertEqual(len(assistant.calls), 1)
        self.assertEqual(assistant.calls[0][1], "management")
        self.assertEqual(replies.items[0][1], "正在分析业务数据，请稍候……")
        self.assertIn("已分析：销售-20260718-01为什么高风险？", replies.items[1][1])

    def test_unknown_user_receives_open_id_without_calling_assistant(self) -> None:
        assistant = FakeAssistant()
        replies = FakeReplies()
        store = FeishuEventStore(self.database_path)
        service = FeishuBotService(
            self.config(),
            store,
            assistant,
            replies,
        )
        message = FeishuMessage(
            event_id="evt-unknown",
            message_id="om_002",
            chat_id="oc_002",
            chat_type="p2p",
            open_id="ou_unknown",
            sender_type="user",
            message_type="text",
            question="查询订单",
        )
        self.assertTrue(store.claim(message))
        service.process(message)
        service.close()

        self.assertEqual(assistant.calls, [])
        self.assertIn("ou_unknown", replies.items[0][1])
        self.assertIn("使用权限", replies.items[0][1])

    def test_answer_card_uses_json_v2_and_preserves_markdown(self) -> None:
        from channels.feishu_core import FeishuApiClient

        client = FeishuApiClient(self.config({"ou_001": "management"}))
        result = {
            "answer": "一、结论\n\n**综合风险85分**\n\n- 缺料40分",
            "intent": "order_risk",
            "trace_id": "trace-card-001",
        }
        card = client._answer_card(
            "销售-20260718-01为什么是高风险订单？",
            result,
        )
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["title"]["content"], "订单风险分析")
        self.assertEqual(
            card["body"]["elements"][0]["tag"],
            "markdown",
        )
        self.assertIn(
            "**综合风险85分**",
            card["body"]["elements"][0]["content"],
        )
        self.assertLess(
            len(json.dumps(card, ensure_ascii=False).encode("utf-8")),
            self.config().max_card_bytes,
        )

    def test_management_action_button_uses_confirmation_token(self) -> None:
        from channels.feishu_core import FeishuApiClient

        client = FeishuApiClient(self.config({"ou_001": "management"}))
        card = client._answer_card(
            "生成本周经营周报",
            {
                "answer": "经营周报内容",
                "intent": "business_report",
                "management_actions": [
                    {
                        "management_action_id": "action-001",
                        "priority": 2,
                        "action": "确认缺料补齐计划",
                        "responsible_department": "采购部",
                        "recipient_name": "采购负责人",
                        "button_text": "确认发送给采购部负责人",
                        "confirmation_token": "one-time-token",
                    }
                ],
            },
        )
        buttons = [
            item
            for item in card["body"]["elements"]
            if item.get("tag") == "button"
        ]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(
            buttons[0]["value"]["action"], "confirm_management_action"
        )
        self.assertEqual(
            buttons[0]["value"]["confirmation_token"], "one-time-token"
        )
        self.assertNotIn("recipient_open_id", buttons[0]["value"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from business_engine import EntityNotFound, InvalidCalculationInput

from .ai_store import AIAuditStore
from .store import OperationalStore


MANAGEMENT_ROLES = {"owner", "plant_manager"}
ALL_BINDING_ROLES = MANAGEMENT_ROLES | {"department_head"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class ActionHub:
    """Small action bridge: identity, approval, delivery, receipt and audit."""

    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
    MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(
        self,
        database_path: str | Path,
        audit_store: AIAuditStore,
        operational_store: OperationalStore,
    ) -> None:
        self.database_path = str(database_path)
        self.audit_store = audit_store
        self.operational_store = operational_store
        self.app_id = os.getenv("FEISHU_APP_ID", "").strip()
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
        self.retry_count = max(0, int(os.getenv("FEISHU_SEND_RETRY_COUNT", "3")))
        self.retry_backoff = max(0.0, float(os.getenv("FEISHU_SEND_RETRY_BACKOFF_SECONDS", "1")))
        self.trust_env = os.getenv("FEISHU_TRUST_ENV_PROXY", "false").lower() in {"1", "true", "yes", "on"}
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_identity_bindings (
                    binding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    feishu_open_id TEXT NOT NULL UNIQUE,
                    access_role TEXT NOT NULL,
                    department_id INTEGER,
                    plant_id INTEGER,
                    can_use_agent INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_bindings_employee
                    ON agent_identity_bindings(employee_id, is_active);
                CREATE TABLE IF NOT EXISTS outbound_notifications (
                    notification_id TEXT PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    management_action_id TEXT,
                    recipient_employee_id INTEGER NOT NULL,
                    recipient_open_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    external_message_id TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    acknowledged_at TEXT,
                    feedback_text TEXT,
                    feedback_at TEXT,
                    notification_kind TEXT NOT NULL DEFAULT 'action_request',
                    requires_receipt INTEGER NOT NULL DEFAULT 1,
                    source_notification_id TEXT,
                    deduplication_key TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_outbound_notifications_status
                    ON outbound_notifications(status, created_at);
                CREATE TABLE IF NOT EXISTS management_action_messages (
                    management_action_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    actor_open_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    recipient_employee_id INTEGER NOT NULL,
                    recipient_open_id TEXT NOT NULL,
                    recipient_name TEXT NOT NULL,
                    department_id INTEGER,
                    department_name TEXT,
                    priority INTEGER,
                    action_text TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notification_id TEXT,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_management_actions_trace
                    ON management_action_messages(trace_id, created_at);
                CREATE TABLE IF NOT EXISTS ai_operation_audit (
                    operation_audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    actor_open_id TEXT,
                    actor_role TEXT,
                    action_type TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    status TEXT NOT NULL,
                    request_json TEXT,
                    result_json TEXT,
                    error_text TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operation_audit_trace
                    ON ai_operation_audit(trace_id, operation_audit_id);
                """
            )
            outbound_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(outbound_notifications)"
                ).fetchall()
            }
            if "management_action_id" not in outbound_columns:
                connection.execute(
                    "ALTER TABLE outbound_notifications "
                    "ADD COLUMN management_action_id TEXT"
                )
            if "notification_kind" not in outbound_columns:
                connection.execute(
                    "ALTER TABLE outbound_notifications "
                    "ADD COLUMN notification_kind TEXT NOT NULL "
                    "DEFAULT 'action_request'"
                )
            if "requires_receipt" not in outbound_columns:
                connection.execute(
                    "ALTER TABLE outbound_notifications "
                    "ADD COLUMN requires_receipt INTEGER NOT NULL DEFAULT 1"
                )
            if "source_notification_id" not in outbound_columns:
                connection.execute(
                    "ALTER TABLE outbound_notifications "
                    "ADD COLUMN source_notification_id TEXT"
                )
            if "deduplication_key" not in outbound_columns:
                connection.execute(
                    "ALTER TABLE outbound_notifications "
                    "ADD COLUMN deduplication_key TEXT"
                )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_outbound_notifications_deduplication "
                "ON outbound_notifications(deduplication_key) "
                "WHERE deduplication_key IS NOT NULL"
            )
            connection.commit()

    def log_operation(
        self,
        action_type: str,
        status: str,
        *,
        trace_id: Optional[str] = None,
        actor_open_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        request: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        error_text: Optional[str] = None,
    ) -> int:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO ai_operation_audit(
                    trace_id, actor_open_id, actor_role, action_type,
                    target_type, target_id, status, request_json,
                    result_json, error_text, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trace_id or str(uuid.uuid4()), actor_open_id, actor_role,
                    action_type, target_type, target_id, status,
                    _json(request or {}), _json(result or {}), error_text,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def upsert_binding(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        role = str(payload["access_role"])
        if role not in ALL_BINDING_ROLES:
            raise InvalidCalculationInput("access_role仅支持owner、plant_manager或department_head")
        employee_id = int(payload["employee_id"])
        with closing(self._connect()) as connection:
            employee = connection.execute(
                "SELECT employee_id, employee_code, employee_name, department_id, plant_id FROM employees WHERE employee_id=? AND is_active=1",
                (employee_id,),
            ).fetchone()
            if not employee:
                raise EntityNotFound(f"员工不存在或未启用: {employee_id}")
            now = datetime.now(timezone.utc).isoformat()
            can_use = role in MANAGEMENT_ROLES
            connection.execute(
                """
                INSERT INTO agent_identity_bindings(
                    employee_id, feishu_open_id, access_role, department_id,
                    plant_id, can_use_agent, is_active, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,1,?,?)
                ON CONFLICT(feishu_open_id) DO UPDATE SET
                    employee_id=excluded.employee_id,
                    access_role=excluded.access_role,
                    department_id=excluded.department_id,
                    plant_id=excluded.plant_id,
                    can_use_agent=excluded.can_use_agent,
                    is_active=1,
                    updated_at=excluded.updated_at
                """,
                (employee_id, payload["feishu_open_id"], role,
                 payload.get("department_id") or employee["department_id"],
                 payload.get("plant_id") or employee["plant_id"], int(can_use), now, now),
            )
            connection.commit()
        binding = self.resolve_identity(str(payload["feishu_open_id"]), include_inactive=True)
        self.log_operation("identity_binding_upsert", "completed", actor_open_id=payload.get("actor_open_id"), target_type="employee", target_id=str(employee_id), result=binding)
        return binding

    def resolve_identity(self, open_id: str, include_inactive: bool = False) -> Dict[str, Any]:
        active_clause = "" if include_inactive else "AND b.is_active=1"
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT b.*, e.employee_code, e.employee_name, d.department_code,
                       d.department_name, p.plant_code, p.plant_name
                FROM agent_identity_bindings b
                JOIN employees e ON e.employee_id=b.employee_id
                LEFT JOIN departments d ON d.department_id=b.department_id
                LEFT JOIN plants p ON p.plant_id=b.plant_id
                WHERE b.feishu_open_id=? {active_clause}
                """,
                (open_id,),
            ).fetchone()
        if not row:
            return {"authorized": False, "feishu_open_id": open_id}
        result = dict(row)
        result["authorized"] = bool(result["is_active"])
        result["can_use_agent"] = bool(result["can_use_agent"])
        result["assistant_role"] = "management" if result["access_role"] in MANAGEMENT_ROLES else None
        return result

    def list_bindings(self) -> list[Dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT b.*, e.employee_code, e.employee_name,
                       d.department_code, d.department_name
                FROM agent_identity_bindings b
                JOIN employees e ON e.employee_id=b.employee_id
                LEFT JOIN departments d ON d.department_id=b.department_id
                ORDER BY b.access_role, d.department_code, e.employee_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def propose_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        actor = self.resolve_identity(str(payload["actor_open_id"]))
        if not actor.get("can_use_agent"):
            raise InvalidCalculationInput("只有已绑定的老板或厂长可以发起消息")
        recipient_id = int(payload["recipient_employee_id"])
        with closing(self._connect()) as connection:
            recipient = connection.execute(
                """
                SELECT b.feishu_open_id, b.access_role, e.employee_name,
                       d.department_name
                FROM agent_identity_bindings b
                JOIN employees e ON e.employee_id=b.employee_id
                LEFT JOIN departments d ON d.department_id=b.department_id
                WHERE b.employee_id=? AND b.is_active=1
                ORDER BY b.binding_id LIMIT 1
                """,
                (recipient_id,),
            ).fetchone()
        if not recipient:
            raise InvalidCalculationInput("接收人尚未绑定有效的飞书账号")
        action_payload = {
            "task_code": payload["task_code"],
            "recipient_employee_id": recipient_id,
            "recipient_open_id": recipient["feishu_open_id"],
            "message_title": payload["message_title"],
            "message_body": payload["message_body"],
            "actor_open_id": payload["actor_open_id"],
            "actor_role": actor["access_role"],
        }
        preview = {
            "发送人": f"{actor['employee_name']}（{actor['access_role']}）",
            "接收人": f"{recipient['employee_name']}（{recipient['department_name'] or '未分配部门'}）",
            "关联任务": payload["task_code"],
            "消息标题": payload["message_title"],
            "消息内容": payload["message_body"],
            "发送渠道": "站内消息＋飞书",
        }
        confirmation = self.audit_store.create_confirmation(
            str(payload.get("conversation_id") or "action-hub"),
            "send_department_message", action_payload, preview,
        )
        self.log_operation("message_proposed", "pending_confirmation", actor_open_id=payload["actor_open_id"], actor_role=actor["access_role"], target_type="employee", target_id=str(recipient_id), request=preview)
        return confirmation

    def prepare_management_actions(
        self,
        *,
        trace_id: str,
        conversation_id: str,
        actor_open_id: str,
        actions: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        """Create short-lived, server-trusted action buttons for a manager."""
        actor = self.resolve_identity(actor_open_id)
        if not actor.get("can_use_agent"):
            return []
        prepared: list[Dict[str, Any]] = []
        for item in actions[:5]:
            action_text = str(item.get("action") or "").strip()
            department_name = str(item.get("owner") or "").strip()
            if not action_text or not department_name:
                continue
            with closing(self._connect()) as connection:
                recipient = connection.execute(
                    """
                    SELECT b.feishu_open_id, b.employee_id, b.department_id,
                           e.employee_name, d.department_name
                    FROM agent_identity_bindings b
                    JOIN employees e ON e.employee_id=b.employee_id
                    LEFT JOIN departments d ON d.department_id=b.department_id
                    WHERE b.access_role='department_head'
                      AND b.is_active=1
                      AND d.department_name=?
                    ORDER BY b.binding_id
                    LIMIT 1
                    """,
                    (department_name,),
                ).fetchone()
            # Combined owners such as “计划/采购/生产” are intentionally not
            # auto-routed. A button is created only for an exact department match.
            if not recipient:
                continue
            management_action_id = str(uuid.uuid4())
            priority = item.get("priority")
            title = f"经营管理动作通知：{department_name}"
            body = (
                f"管理动作：{action_text}\n\n"
                "请确认处理安排，并通过卡片回执或文字反馈处理进展。"
            )
            now = datetime.now(timezone.utc).isoformat()
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT INTO management_action_messages(
                        management_action_id, trace_id, conversation_id,
                        actor_open_id, actor_role, recipient_employee_id,
                        recipient_open_id, recipient_name, department_id,
                        department_name, priority, action_text, title, body,
                        status, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'proposed',?)
                    """,
                    (
                        management_action_id, trace_id, conversation_id,
                        actor_open_id, actor["access_role"],
                        recipient["employee_id"], recipient["feishu_open_id"],
                        recipient["employee_name"], recipient["department_id"],
                        recipient["department_name"], priority, action_text,
                        title, body, now,
                    ),
                )
                connection.commit()
            preview = {
                "发送人": f"{actor['employee_name']}（{actor['access_role']}）",
                "接收人": (
                    f"{recipient['employee_name']}"
                    f"（{recipient['department_name']}）"
                ),
                "管理动作": action_text,
                "发送渠道": "站内管理通知＋飞书",
            }
            confirmation = self.audit_store.create_confirmation(
                conversation_id,
                "send_management_action",
                {
                    "management_action_id": management_action_id,
                    "actor_open_id": actor_open_id,
                },
                preview,
            )
            self.log_operation(
                "management_action_proposed",
                "pending_confirmation",
                trace_id=trace_id,
                actor_open_id=actor_open_id,
                actor_role=actor["access_role"],
                target_type="management_action",
                target_id=management_action_id,
                request=preview,
            )
            prepared.append(
                {
                    "management_action_id": management_action_id,
                    "priority": priority,
                    "action": action_text,
                    "responsible_department": department_name,
                    "recipient_employee_id": recipient["employee_id"],
                    "recipient_name": recipient["employee_name"],
                    "button_text": f"确认发送给{department_name}负责人",
                    "confirmation_token": confirmation["confirmation_token"],
                    "expires_at": confirmation["expires_at"],
                }
            )
        return prepared

    def execute_confirmed_management_action(
        self, confirmation: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = confirmation["payload"]
        action_id = str(payload["management_action_id"])
        with closing(self._connect()) as connection:
            action = connection.execute(
                "SELECT * FROM management_action_messages "
                "WHERE management_action_id=?",
                (action_id,),
            ).fetchone()
        if not action:
            raise EntityNotFound(f"管理动作不存在: {action_id}")
        item = dict(action)
        actor = self.resolve_identity(item["actor_open_id"])
        if not actor.get("can_use_agent"):
            raise InvalidCalculationInput("发送人身份已失效，管理动作未发送")
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE management_action_messages "
                "SET status='confirmed', confirmed_at=? "
                "WHERE management_action_id=? AND status='proposed'",
                (datetime.now(timezone.utc).isoformat(), action_id),
            )
            connection.commit()
        if cursor.rowcount == 0:
            raise InvalidCalculationInput("该管理动作已经确认或发送")
        notification_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO outbound_notifications(
                    notification_id, message_id, management_action_id,
                    recipient_employee_id, recipient_open_id, channel,
                    title, body, status, created_at
                ) VALUES(?,0,?,?,?,?,?,?,'pending',?)
                """,
                (
                    notification_id, action_id, item["recipient_employee_id"],
                    item["recipient_open_id"], "feishu", item["title"],
                    item["body"], now,
                ),
            )
            connection.execute(
                "UPDATE management_action_messages SET notification_id=? "
                "WHERE management_action_id=?",
                (notification_id, action_id),
            )
            connection.commit()
        with closing(self._connect()) as connection:
            delivery = dict(
                connection.execute(
                    "SELECT * FROM outbound_notifications "
                    "WHERE notification_id=?",
                    (notification_id,),
                ).fetchone()
            )
        self.log_operation(
            "management_action_confirmed",
            "queued",
            trace_id=item["trace_id"],
            actor_open_id=item["actor_open_id"],
            actor_role=item["actor_role"],
            target_type="management_action",
            target_id=action_id,
            result=delivery,
        )
        threading.Thread(
            target=self._deliver_management_action,
            args=(notification_id, item),
            name=f"management-action-{action_id[:8]}",
            daemon=True,
        ).start()
        return {"management_action": item, "notification": delivery}

    def _deliver_management_action(
        self, notification_id: str, action: Dict[str, Any]
    ) -> None:
        try:
            delivery = self.send_notification(notification_id)
            self.log_operation(
                "management_action_delivery",
                delivery["status"],
                trace_id=action["trace_id"],
                actor_open_id=action["actor_open_id"],
                actor_role=action["actor_role"],
                target_type="management_action",
                target_id=action["management_action_id"],
                result=delivery,
                error_text=delivery.get("last_error"),
            )
        except Exception as exc:
            self.log_operation(
                "management_action_delivery",
                "failed",
                trace_id=action["trace_id"],
                actor_open_id=action["actor_open_id"],
                actor_role=action["actor_role"],
                target_type="management_action",
                target_id=action["management_action_id"],
                error_text=f"{type(exc).__name__}: {exc}",
            )

    def execute_confirmed_message(self, confirmation: Dict[str, Any]) -> Dict[str, Any]:
        payload = confirmation["payload"]
        actor = self.resolve_identity(payload["actor_open_id"])
        if not actor.get("can_use_agent"):
            raise InvalidCalculationInput("发送人身份已失效，消息未发送")
        message = self.operational_store.create_message({
            "task_code": payload["task_code"],
            "recipient_employee_id": payload["recipient_employee_id"],
            "channel": "站内",
            "message_title": payload["message_title"],
            "message_body": payload["message_body"],
        })
        notification_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO outbound_notifications(
                    notification_id, message_id, recipient_employee_id,
                    recipient_open_id, channel, title, body, status,
                    created_at
                ) VALUES(?,?,?,?,?,?,?,'pending',?)
                """,
                (notification_id, message["message_id"], payload["recipient_employee_id"],
                 payload["recipient_open_id"], "feishu", payload["message_title"],
                 payload["message_body"], now),
            )
            connection.commit()
        delivery = self.send_notification(notification_id)
        self.log_operation("message_confirmed_and_sent", delivery["status"], actor_open_id=payload["actor_open_id"], actor_role=actor["access_role"], target_type="notification", target_id=notification_id, result=delivery, error_text=delivery.get("last_error"))
        return {"internal_message": message, "notification": delivery}

    def _tenant_token(self) -> str:
        if not self.app_id or not self.app_secret:
            raise RuntimeError("FEISHU_APP_ID或FEISHU_APP_SECRET尚未配置")
        with httpx.Client(trust_env=self.trust_env, timeout=15) as client:
            response = client.post(self.TOKEN_URL, json={"app_id": self.app_id, "app_secret": self.app_secret})
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"飞书令牌获取失败: {body.get('code')} {body.get('msg')}")
        return str(body["tenant_access_token"])

    @staticmethod
    def _notification_card(row: Dict[str, Any]) -> Dict[str, Any]:
        notification_id = row["notification_id"]
        requires_receipt = bool(row.get("requires_receipt", 1))
        kind = str(row.get("notification_kind") or "action_request")
        elements: list[Dict[str, Any]] = [
            {"tag": "markdown", "content": row["body"]},
            {
                "tag": "markdown",
                "content": (
                    f"<font color='grey'>通知编号：{notification_id}</font>"
                ),
            },
        ]
        if requires_receipt:
            elements.extend(
                [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "已收到"},
                        "type": "primary",
                        "value": {
                            "action": "acknowledge",
                            "notification_id": notification_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "需要协调"},
                        "type": "default",
                        "value": {
                            "action": "feedback",
                            "notification_id": notification_id,
                            "feedback": "需要协调",
                        },
                    },
                ]
            )
        template = "orange"
        if kind == "management_action_receipt_acknowledged":
            template = "green"
        elif kind == "management_action_receipt_feedback":
            template = "yellow"
        return {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": row["title"]},
                "template": template,
            },
            "body": {"elements": elements},
        }

    @staticmethod
    def _receipt_deduplication_key(
        source_notification_id: str,
        action: str,
        feedback: Optional[str],
    ) -> str:
        normalized = (feedback or "").strip()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"management-receipt:{source_notification_id}:{action}:{digest}"

    def _queue_owner_receipt_notification(
        self,
        connection: sqlite3.Connection,
        *,
        source: sqlite3.Row,
        action: str,
        feedback: Optional[str],
        occurred_at: str,
    ) -> Optional[Dict[str, Any]]:
        action_id = source["management_action_id"]
        if not action_id:
            return None
        management_action = connection.execute(
            """
            SELECT m.*, b.employee_id AS actor_employee_id
            FROM management_action_messages m
            LEFT JOIN agent_identity_bindings b
              ON b.feishu_open_id=m.actor_open_id AND b.is_active=1
            WHERE m.management_action_id=?
            ORDER BY b.binding_id
            LIMIT 1
            """,
            (action_id,),
        ).fetchone()
        if not management_action or management_action["actor_employee_id"] is None:
            return None

        feedback_text = (feedback or "").strip()
        if action == "acknowledge":
            status_text = "已收到"
            kind = "management_action_receipt_acknowledged"
        else:
            status_text = feedback_text
            kind = "management_action_receipt_feedback"
        local_time = datetime.fromisoformat(occurred_at).astimezone(
            timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")
        title = f"管理动作回执：{management_action['department_name']}"
        body = (
            f"负责人：{management_action['recipient_name']}"
            f"（{management_action['department_name']}）\n\n"
            f"管理动作：{management_action['action_text']}\n\n"
            f"回执状态：{status_text}\n\n"
            f"回执时间：{local_time}"
        )
        deduplication_key = self._receipt_deduplication_key(
            source["notification_id"], action, feedback_text
        )
        notification_id = str(uuid.uuid4())
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO outbound_notifications(
                notification_id, message_id, recipient_employee_id,
                recipient_open_id, channel, title, body, status, created_at,
                notification_kind, requires_receipt, source_notification_id,
                deduplication_key
            ) VALUES(?,0,?,?,?,?,?,'pending',?,?,0,?,?)
            """,
            (
                notification_id,
                management_action["actor_employee_id"],
                management_action["actor_open_id"],
                "feishu",
                title,
                body,
                occurred_at,
                kind,
                source["notification_id"],
                deduplication_key,
            ),
        )
        if cursor.rowcount == 0:
            existing = connection.execute(
                "SELECT * FROM outbound_notifications "
                "WHERE deduplication_key=?",
                (deduplication_key,),
            ).fetchone()
            if not existing:
                return None
            result = dict(existing)
            result["_created"] = False
            return result
        created = connection.execute(
            "SELECT * FROM outbound_notifications WHERE notification_id=?",
            (notification_id,),
        ).fetchone()
        if not created:
            return None
        result = dict(created)
        result["_created"] = True
        return result

    def _deliver_owner_receipt(
        self,
        notification_id: str,
        source_notification_id: str,
    ) -> None:
        try:
            delivery = self.send_notification(notification_id)
            self.log_operation(
                "management_action_receipt_delivery",
                delivery["status"],
                target_type="notification",
                target_id=notification_id,
                request={"source_notification_id": source_notification_id},
                result=delivery,
                error_text=delivery.get("last_error"),
            )
        except Exception as exc:
            self.log_operation(
                "management_action_receipt_delivery",
                "failed",
                target_type="notification",
                target_id=notification_id,
                request={"source_notification_id": source_notification_id},
                error_text=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _transient(exc: Exception) -> bool:
        if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {429, 500, 502, 503, 504}
        return False

    def send_notification(self, notification_id: str) -> Dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM outbound_notifications WHERE notification_id=?", (notification_id,)).fetchone()
        if not row:
            raise EntityNotFound(f"通知不存在: {notification_id}")
        item = dict(row)
        if item["status"] in {"sent", "acknowledged"}:
            return item
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE outbound_notifications SET status='sending' "
                "WHERE notification_id=? AND status IN ('pending','failed')",
                (notification_id,),
            )
            connection.commit()
        if cursor.rowcount == 0:
            with closing(self._connect()) as connection:
                current = connection.execute(
                    "SELECT * FROM outbound_notifications WHERE notification_id=?",
                    (notification_id,),
                ).fetchone()
            return dict(current)
        last_error = None
        attempts = int(item["attempt_count"])
        for retry_index in range(self.retry_count + 1):
            attempts += 1
            try:
                token = self._tenant_token()
                with httpx.Client(trust_env=self.trust_env, timeout=20) as client:
                    response = client.post(
                        self.MESSAGE_URL,
                        params={"receive_id_type": "open_id"},
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                        json={"receive_id": item["recipient_open_id"], "msg_type": "interactive", "content": _json(self._notification_card(item)), "uuid": uuid.uuid4().hex},
                    )
                response.raise_for_status()
                body = response.json()
                if body.get("code") != 0:
                    raise RuntimeError(f"飞书消息发送失败: {body.get('code')} {body.get('msg')}")
                external_id = str((body.get("data") or {}).get("message_id") or "")
                with closing(self._connect()) as connection:
                    connection.execute("UPDATE outbound_notifications SET status='sent', attempt_count=?, external_message_id=?, sent_at=?, last_error=NULL WHERE notification_id=?", (attempts, external_id, datetime.now(timezone.utc).isoformat(), notification_id))
                    connection.commit()
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self.log_operation("feishu_send_attempt", "retrying" if retry_index < self.retry_count and self._transient(exc) else "failed", target_type="notification", target_id=notification_id, request={"attempt": attempts}, error_text=last_error)
                if retry_index >= self.retry_count or not self._transient(exc):
                    with closing(self._connect()) as connection:
                        connection.execute("UPDATE outbound_notifications SET status='failed', attempt_count=?, last_error=? WHERE notification_id=?", (attempts, last_error, notification_id))
                        connection.commit()
                    break
                time.sleep(self.retry_backoff * (2 ** retry_index))
        with closing(self._connect()) as connection:
            result = dict(connection.execute("SELECT * FROM outbound_notifications WHERE notification_id=?", (notification_id,)).fetchone())
            if result.get("management_action_id"):
                connection.execute(
                    "UPDATE management_action_messages SET status=? "
                    "WHERE management_action_id=?",
                    (result["status"], result["management_action_id"]),
                )
                connection.commit()
        return result

    def receive_feedback(self, notification_id: str, actor_open_id: str, action: str, feedback: Optional[str] = None) -> Dict[str, Any]:
        owner_notification: Optional[Dict[str, Any]] = None
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM outbound_notifications WHERE notification_id=?", (notification_id,)).fetchone()
            if not row:
                raise EntityNotFound(f"通知不存在: {notification_id}")
            if row["recipient_open_id"] != actor_open_id:
                raise InvalidCalculationInput("只有该通知的接收人可以回执")
            now = datetime.now(timezone.utc).isoformat()
            if action == "acknowledge":
                connection.execute("UPDATE outbound_notifications SET status='acknowledged', acknowledged_at=COALESCE(acknowledged_at, ?) WHERE notification_id=?", (now, notification_id))
                if row["management_action_id"]:
                    connection.execute(
                        "UPDATE management_action_messages "
                        "SET status=CASE WHEN status='feedback_received' "
                        "THEN status ELSE 'acknowledged' END "
                        "WHERE management_action_id=?",
                        (row["management_action_id"],),
                    )
                else:
                    connection.execute(
                        "UPDATE messages SET status='已收到' WHERE message_id=?",
                        (row["message_id"],),
                    )
            elif action == "feedback":
                text = (feedback or "").strip()
                if not text:
                    raise InvalidCalculationInput("反馈内容不能为空")
                connection.execute("UPDATE outbound_notifications SET feedback_text=?, feedback_at=? WHERE notification_id=?", (text, now, notification_id))
                if row["management_action_id"]:
                    connection.execute(
                        "UPDATE management_action_messages "
                        "SET status='feedback_received' "
                        "WHERE management_action_id=?",
                        (row["management_action_id"],),
                    )
                else:
                    connection.execute(
                        "UPDATE messages SET status='已反馈' WHERE message_id=?",
                        (row["message_id"],),
                    )
            else:
                raise InvalidCalculationInput("不支持的回执动作")
            owner_notification = self._queue_owner_receipt_notification(
                connection,
                source=row,
                action=action,
                feedback=feedback,
                occurred_at=now,
            )
            connection.commit()
            result = dict(connection.execute("SELECT * FROM outbound_notifications WHERE notification_id=?", (notification_id,)).fetchone())
        should_deliver_owner_notification = bool(
            owner_notification and owner_notification.pop("_created", False)
        )
        result["owner_notification"] = owner_notification
        self.log_operation(f"notification_{action}", "completed", actor_open_id=actor_open_id, actor_role="department_head", target_type="notification", target_id=notification_id, result={"feedback": feedback, "owner_notification_id": (owner_notification or {}).get("notification_id")})
        if (
            should_deliver_owner_notification
            and owner_notification
            and owner_notification.get("status") == "pending"
        ):
            threading.Thread(
                target=self._deliver_owner_receipt,
                args=(owner_notification["notification_id"], notification_id),
                name=f"management-receipt-{notification_id[:8]}",
                daemon=True,
            ).start()
        return result

    def list_notifications(self, status: Optional[str] = None, limit: int = 100) -> list[Dict[str, Any]]:
        where, params = "", []
        if status:
            where, params = "WHERE status=?", [status]
        params.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(f"SELECT * FROM outbound_notifications {where} ORDER BY created_at DESC LIMIT ?", params).fetchall()
        return [dict(row) for row in rows]

    def list_operations(self, limit: int = 200) -> list[Dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM ai_operation_audit ORDER BY operation_audit_id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

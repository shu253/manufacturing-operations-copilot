from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from business_engine import EntityNotFound, InvalidCalculationInput


class OperationalStore:
    _RISK_TYPE_NAMES = {
        "MATERIAL_SHORTAGE": "关键物料缺料",
        "PURCHASE_LATE": "采购迟交",
        "PRODUCTION_DELAY": "生产进度落后",
        "QUALITY_REWORK": "质量返工",
        "DUE_SOON": "临近交期",
        "RECEIVABLE_OVERDUE": "应收账款逾期",
    }

    """阶段四任务和消息闭环使用的显式写入仓储。"""

    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list_products(self, active_only: bool = True) -> List[Dict[str, Any]]:
        where = "WHERE is_active=1" if active_only else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT product_code, product_name, product_family, unit
                FROM products
                {where}
                ORDER BY product_code
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_tasks(
        self, status: Optional[str] = None, priority: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if status:
            clauses.append("t.status=?")
            params.append(status)
        if priority:
            clauses.append("t.priority=?")
            params.append(priority)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT t.*, e.employee_code, e.employee_name,
                   r.risk_code, r.risk_type, r.rule_code,
                   r.entity_type, r.entity_code, r.risk_score,
                   r.severity AS risk_severity, r.status AS risk_status,
                   r.detected_at, r.summary AS risk_summary, r.potential_amount,
                   (
                       SELECT COUNT(*)
                       FROM messages m
                       WHERE m.task_id=t.task_id
                   ) AS message_count
            FROM tasks t
            LEFT JOIN employees e ON e.employee_id=t.owner_employee_id
            LEFT JOIN risk_events r ON r.risk_event_id=t.risk_event_id
            {where}
            ORDER BY CASE t.priority WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END,
                     t.due_date, t.task_id
            LIMIT ?
        """
        params.append(limit)
        with closing(self._connect()) as connection:
            return [
                self._decorate_task(dict(row))
                for row in connection.execute(sql, params).fetchall()
            ]

    def create_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with closing(self._connect()) as connection:
            employee = connection.execute(
                "SELECT 1 FROM employees WHERE employee_id=?",
                (payload["owner_employee_id"],),
            ).fetchone()
            if not employee:
                raise EntityNotFound(
                    f"员工不存在: {payload['owner_employee_id']}"
                )
            if payload.get("risk_event_id") is not None:
                risk = connection.execute(
                    "SELECT 1 FROM risk_events WHERE risk_event_id=?",
                    (payload["risk_event_id"],),
                ).fetchone()
                if not risk:
                    raise EntityNotFound(
                        f"风险事件不存在: {payload['risk_event_id']}"
                    )
            next_id = connection.execute(
                "SELECT COALESCE(MAX(task_id),0)+1 FROM tasks"
            ).fetchone()[0]
            task_code = f"API-TASK-{next_id:06d}"
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, risk_event_id, task_code, task_title,
                    owner_employee_id, due_date, status, priority
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    next_id,
                    payload.get("risk_event_id"),
                    task_code,
                    payload["task_title"],
                    payload["owner_employee_id"],
                    str(payload["due_date"]),
                    "待处理",
                    payload["priority"],
                ),
            )
            connection.commit()
        return self.get_task(task_code)

    def get_task(self, task_code: str) -> Dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT t.*, e.employee_code, e.employee_name,
                       r.risk_code, r.risk_type, r.rule_code,
                       r.entity_type, r.entity_code, r.risk_score,
                       r.severity AS risk_severity, r.status AS risk_status,
                       r.detected_at, r.summary AS risk_summary, r.potential_amount,
                       (
                           SELECT COUNT(*)
                           FROM messages m
                           WHERE m.task_id=t.task_id
                       ) AS message_count
                FROM tasks t
                LEFT JOIN employees e ON e.employee_id=t.owner_employee_id
                LEFT JOIN risk_events r ON r.risk_event_id=t.risk_event_id
                WHERE t.task_code=?
                """,
                (task_code,),
            ).fetchone()
            if not row:
                raise EntityNotFound(f"任务不存在: {task_code}")
            evidence = [
                dict(item)
                for item in connection.execute(
                    """
                    SELECT evidence_type, source_table, source_record_code,
                           evidence_value
                    FROM risk_evidence
                    WHERE risk_event_id=?
                    ORDER BY risk_evidence_id
                    """,
                    (row["risk_event_id"],),
                ).fetchall()
            ]
            messages = [
                dict(item)
                for item in connection.execute(
                    """
                    SELECT m.message_id, m.channel, m.message_title,
                           m.message_body, m.sent_at, m.status AS read_status,
                           e.employee_code, e.employee_name
                    FROM messages m
                    LEFT JOIN employees e
                      ON e.employee_id=m.recipient_employee_id
                    WHERE m.task_id=?
                    ORDER BY m.message_id DESC
                    """,
                    (row["task_id"],),
                ).fetchall()
            ]
        result = self._decorate_task(dict(row))
        result["evidence"] = evidence
        result["messages"] = messages
        return result

    def _decorate_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        risk_type = task.get("risk_type")
        rule_code = task.get("rule_code")
        classification = (
            rule_code
            if rule_code in self._RISK_TYPE_NAMES
            else risk_type
        )
        entity_code = task.get("entity_code") or ""
        task["risk_type_name"] = self._RISK_TYPE_NAMES.get(
            classification, risk_type or "其他风险"
        )
        title_templates = {
            "MATERIAL_SHORTAGE": f"补齐{entity_code}关键物料缺口",
            "PURCHASE_LATE": f"跟进{entity_code}采购迟交",
            "PRODUCTION_DELAY": f"追回{entity_code}生产进度",
            "QUALITY_REWORK": f"处理{entity_code}质量返工",
            "DUE_SOON": f"保障{entity_code}按期交付",
            "RECEIVABLE_OVERDUE": f"催收{entity_code}逾期应收款",
        }
        task["display_title"] = title_templates.get(
            classification, task.get("task_title") or "风险处理任务"
        )
        return task

    def update_task(self, task_code: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"owner_employee_id", "due_date", "status", "priority"}
        values = {key: value for key, value in changes.items() if key in allowed and value is not None}
        if not values:
            raise InvalidCalculationInput("至少提供一个需要更新的字段")
        with closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT 1 FROM tasks WHERE task_code=?", (task_code,)
            ).fetchone()
            if not existing:
                raise EntityNotFound(f"任务不存在: {task_code}")
            if "owner_employee_id" in values and not connection.execute(
                "SELECT 1 FROM employees WHERE employee_id=?",
                (values["owner_employee_id"],),
            ).fetchone():
                raise EntityNotFound(f"员工不存在: {values['owner_employee_id']}")
            assignments = ", ".join(f"{key}=?" for key in values)
            params = [str(value) for value in values.values()] + [task_code]
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_code=?", params
            )
            connection.commit()
        return self.get_task(task_code)

    def list_messages(
        self, task_code: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        params: List[Any] = []
        where = ""
        if task_code:
            where = "WHERE t.task_code=?"
            params.append(task_code)
        params.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT m.*, t.task_code, e.employee_code, e.employee_name
                FROM messages m
                JOIN tasks t ON t.task_id=m.task_id
                LEFT JOIN employees e ON e.employee_id=m.recipient_employee_id
                {where}
                ORDER BY m.message_id DESC LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def create_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with closing(self._connect()) as connection:
            task = connection.execute(
                "SELECT task_id FROM tasks WHERE task_code=?",
                (payload["task_code"],),
            ).fetchone()
            if not task:
                raise EntityNotFound(f"任务不存在: {payload['task_code']}")
            if not connection.execute(
                "SELECT 1 FROM employees WHERE employee_id=?",
                (payload["recipient_employee_id"],),
            ).fetchone():
                raise EntityNotFound(
                    f"员工不存在: {payload['recipient_employee_id']}"
                )
            next_id = connection.execute(
                "SELECT COALESCE(MAX(message_id),0)+1 FROM messages"
            ).fetchone()[0]
            sent_at = datetime.now().astimezone().isoformat(timespec="seconds")
            connection.execute(
                """
                INSERT INTO messages(
                    message_id, task_id, recipient_employee_id, channel,
                    message_title, message_body, sent_at, status
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    next_id,
                    task["task_id"],
                    payload["recipient_employee_id"],
                    payload["channel"],
                    payload["message_title"],
                    payload["message_body"],
                    sent_at,
                    "已创建",
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT m.*, t.task_code, e.employee_code, e.employee_name
                FROM messages m JOIN tasks t ON t.task_id=m.task_id
                LEFT JOIN employees e ON e.employee_id=m.recipient_employee_id
                WHERE m.message_id=?
                """,
                (next_id,),
            ).fetchone()
            return dict(row)

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from business_engine import InvalidCalculationInput


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class AIAuditStore:
    """智能体会话、工具调用和人工确认的显式审计仓储。"""

    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ai_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    workflow_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    message_role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    intent TEXT,
                    model_provider TEXT,
                    model_name TEXT,
                    workflow_version TEXT,
                    status TEXT NOT NULL,
                    grounding_status TEXT,
                    token_input INTEGER,
                    token_output INTEGER,
                    token_total INTEGER,
                    model_cost NUMERIC,
                    model_cost_currency TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES ai_conversations(conversation_id)
                );
                CREATE TABLE IF NOT EXISTS ai_tool_calls (
                    ai_tool_call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    message_id TEXT,
                    tool_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT,
                    status TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    calculation_id TEXT,
                    sources_json TEXT,
                    error_text TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_tool_calls_trace
                    ON ai_tool_calls(trace_id, ai_tool_call_id);
                CREATE TABLE IF NOT EXISTS ai_confirmations (
                    token_hash TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT
                );
                """
            )
            conversation_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(ai_conversations)"
                ).fetchall()
            }
            if "dify_conversation_id" not in conversation_columns:
                connection.execute(
                    "ALTER TABLE ai_conversations "
                    "ADD COLUMN dify_conversation_id TEXT"
                )
            message_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(ai_messages)").fetchall()
            }
            if "token_total" not in message_columns:
                connection.execute("ALTER TABLE ai_messages ADD COLUMN token_total INTEGER")
            if "model_cost_currency" not in message_columns:
                connection.execute("ALTER TABLE ai_messages ADD COLUMN model_cost_currency TEXT")
            connection.commit()

    def ensure_conversation(
        self,
        conversation_id: Optional[str],
        user_id: str,
        role: str,
        model_provider: str,
        model_name: str,
        workflow_version: str,
    ) -> str:
        resolved = conversation_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ai_conversations(
                    conversation_id, user_id, role, model_provider, model_name,
                    workflow_version, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    role=excluded.role,
                    model_provider=excluded.model_provider,
                    model_name=excluded.model_name,
                    workflow_version=excluded.workflow_version,
                    updated_at=excluded.updated_at
                """,
                (
                    resolved,
                    user_id,
                    role,
                    model_provider,
                    model_name,
                    workflow_version,
                    now,
                    now,
                ),
            )
            connection.commit()
        return resolved

    def get_dify_conversation_id(self, conversation_id: str) -> Optional[str]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT dify_conversation_id
                FROM ai_conversations
                WHERE conversation_id=?
                """,
                (conversation_id,),
            ).fetchone()
        if not row:
            return None
        return row["dify_conversation_id"] or None

    def set_dify_conversation_id(
        self, conversation_id: str, dify_conversation_id: str
    ) -> None:
        if not dify_conversation_id:
            return
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE ai_conversations
                SET dify_conversation_id=?, updated_at=?
                WHERE conversation_id=?
                """,
                (
                    dify_conversation_id,
                    datetime.now(timezone.utc).isoformat(),
                    conversation_id,
                ),
            )
            connection.commit()

    def log_message(
        self,
        *,
        conversation_id: str,
        trace_id: str,
        message_role: str,
        content: str,
        intent: Optional[str] = None,
        model_provider: Optional[str] = None,
        model_name: Optional[str] = None,
        workflow_version: Optional[str] = None,
        status: str = "completed",
        grounding_status: Optional[str] = None,
        token_input: Optional[int] = None,
        token_output: Optional[int] = None,
        token_total: Optional[int] = None,
        model_cost: Optional[float] = None,
        model_cost_currency: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
    ) -> str:
        resolved = message_id or str(uuid.uuid4())
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ai_messages(
                    message_id, conversation_id, trace_id, message_role, content,
                    intent, model_provider, model_name, workflow_version, status,
                    grounding_status, token_input, token_output, token_total,
                    model_cost, model_cost_currency, payload_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    resolved,
                    conversation_id,
                    trace_id,
                    message_role,
                    content,
                    intent,
                    model_provider,
                    model_name,
                    workflow_version,
                    status,
                    grounding_status,
                    token_input,
                    token_output,
                    token_total,
                    model_cost,
                    model_cost_currency,
                    _json(payload or {}),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
        return resolved

    def log_tool_call(
        self,
        *,
        trace_id: str,
        tool_name: str,
        parameters: Dict[str, Any],
        output: Optional[Dict[str, Any]],
        status: str,
        duration_ms: int,
        calculation_id: Optional[str] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
        error_text: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> int:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO ai_tool_calls(
                    trace_id, message_id, tool_name, input_json, output_json,
                    status, duration_ms, calculation_id, sources_json,
                    error_text, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trace_id,
                    message_id,
                    tool_name,
                    _json(parameters),
                    _json(output) if output is not None else None,
                    status,
                    duration_ms,
                    calculation_id,
                    _json(sources or []),
                    error_text,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_tool_calls(self, trace_id: str) -> List[Dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM ai_tool_calls
                WHERE trace_id=? ORDER BY ai_tool_call_id
                """,
                (trace_id,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["input"] = json.loads(item.pop("input_json") or "{}")
            item["output"] = json.loads(item.pop("output_json") or "null")
            item["sources"] = json.loads(item.pop("sources_json") or "[]")
            items.append(item)
        return items

    def latest_context(self, conversation_id: str) -> Dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM ai_messages
                WHERE conversation_id=? AND message_role='assistant'
                ORDER BY created_at DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row and row["payload_json"] else {}

    def create_confirmation(
        self,
        conversation_id: str,
        action_type: str,
        payload: Dict[str, Any],
        preview: Dict[str, Any],
        ttl_minutes: int = 10,
    ) -> Dict[str, Any]:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=ttl_minutes)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ai_confirmations(
                    token_hash, conversation_id, action_type, payload_json,
                    preview_json, status, expires_at, created_at
                ) VALUES(?,?,?,?,?,'pending',?,?)
                """,
                (
                    token_hash,
                    conversation_id,
                    action_type,
                    _json(payload),
                    _json(preview),
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.commit()
        return {
            "confirmation_required": True,
            "action_type": action_type,
            "action_preview": preview,
            "confirmation_token": token,
            "expires_at": expires.isoformat(),
        }

    def consume_confirmation(self, token: str) -> Dict[str, Any]:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM ai_confirmations WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if not row:
                connection.rollback()
                raise InvalidCalculationInput("确认令牌无效")
            if row["status"] != "pending":
                connection.rollback()
                raise InvalidCalculationInput("确认令牌已经使用或取消")
            if datetime.fromisoformat(row["expires_at"]) < now:
                connection.execute(
                    "UPDATE ai_confirmations SET status='expired' WHERE token_hash=?",
                    (token_hash,),
                )
                connection.commit()
                raise InvalidCalculationInput("确认令牌已过期，请重新发起操作")
            connection.execute(
                """
                UPDATE ai_confirmations
                SET status='confirmed', confirmed_at=?
                WHERE token_hash=? AND status='pending'
                """,
                (now.isoformat(), token_hash),
            )
            connection.commit()
        return {
            "conversation_id": row["conversation_id"],
            "action_type": row["action_type"],
            "payload": json.loads(row["payload_json"]),
            "preview": json.loads(row["preview_json"]),
        }

    def usage_summary(self) -> Dict[str, Any]:
        with closing(self._connect()) as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) AS message_count,
                       COALESCE(SUM(token_input),0) AS input_tokens,
                       COALESCE(SUM(token_output),0) AS output_tokens,
                       COALESCE(SUM(COALESCE(token_total,COALESCE(token_input,0)+COALESCE(token_output,0))),0) AS total_tokens,
                       ROUND(COALESCE(SUM(model_cost),0),6) AS total_cost,
                       MAX(model_cost_currency) AS currency
                FROM ai_messages WHERE message_role='assistant'
                """
            ).fetchone()
            by_model = connection.execute(
                """
                SELECT model_provider, model_name, COUNT(*) AS message_count,
                       COALESCE(SUM(token_input),0) AS input_tokens,
                       COALESCE(SUM(token_output),0) AS output_tokens,
                       ROUND(COALESCE(SUM(model_cost),0),6) AS total_cost,
                       MAX(model_cost_currency) AS currency
                FROM ai_messages WHERE message_role='assistant'
                GROUP BY model_provider, model_name
                ORDER BY total_cost DESC, message_count DESC
                """
            ).fetchall()
        return {"totals": dict(totals), "by_model": [dict(row) for row in by_model]}

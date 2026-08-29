from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx


LOGGER = logging.getLogger("feishu-bot")
SUPPORTED_ROLES = {"management", "procurement", "finance", "production"}


def load_env_file(path: Path) -> None:
    """Load a simple .env file without overriding process-level variables."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def configure_proxy_environment(config: "FeishuConfig") -> None:
    """Keep both httpx and the Feishu SDK away from broken OS proxy settings."""
    if config.trust_env_proxy:
        return
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(name, None)
    bypass_hosts = {"open.feishu.cn", "127.0.0.1", "localhost"}
    for name in ("NO_PROXY", "no_proxy"):
        existing = {
            item.strip()
            for item in os.environ.get(name, "").split(",")
            if item.strip()
        }
        os.environ[name] = ",".join(sorted(existing | bypass_hosts))


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_allowed_users(value: str, default_role: str) -> Dict[str, str]:
    """Parse ``open_id:role`` entries separated by commas."""
    users: Dict[str, str] = {}
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        open_id, separator, role = item.partition(":")
        resolved_role = role.strip() if separator else default_role
        open_id = open_id.strip()
        if not open_id:
            continue
        if resolved_role not in SUPPORTED_ROLES:
            raise ValueError(
                f"Unsupported Feishu role {resolved_role!r} for {open_id!r}; "
                f"choose one of {sorted(SUPPORTED_ROLES)}"
            )
        users[open_id] = resolved_role
    return users


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    assistant_api: str
    assistant_health_api: str
    database_path: Path
    access_mode: str
    default_role: str
    allowed_users: Dict[str, str]
    allow_p2p: bool
    allow_group_at: bool
    send_processing_message: bool
    worker_count: int
    query_timeout_seconds: float
    max_reply_chars: int
    trust_env_proxy: bool
    reply_format: str
    card_template: str
    max_card_bytes: int
    identity_api: str = "http://127.0.0.1:8000/api/v1/identities/feishu"
    feedback_api: str = "http://127.0.0.1:8000/api/v1/notifications/feishu/callback"
    confirm_api: str = "http://127.0.0.1:8000/api/v1/assistant/confirm"
    action_api_token: str = ""

    @classmethod
    def from_env(cls, project_root: Path) -> "FeishuConfig":
        default_role = os.getenv("FEISHU_DEFAULT_ROLE", "management").strip()
        if default_role not in SUPPORTED_ROLES:
            raise ValueError(
                f"FEISHU_DEFAULT_ROLE must be one of {sorted(SUPPORTED_ROLES)}"
            )
        access_mode = os.getenv("FEISHU_ACCESS_MODE", "allowlist").strip().lower()
        if access_mode not in {"allowlist", "open"}:
            raise ValueError("FEISHU_ACCESS_MODE must be allowlist or open")
        assistant_api = os.getenv(
            "LOCAL_ASSISTANT_API",
            "http://127.0.0.1:8000/api/v1/assistant/query",
        ).strip()
        reply_format = os.getenv("FEISHU_REPLY_FORMAT", "card").strip().lower()
        if reply_format not in {"card", "text"}:
            raise ValueError("FEISHU_REPLY_FORMAT must be card or text")
        return cls(
            app_id=os.getenv("FEISHU_APP_ID", "").strip(),
            app_secret=os.getenv("FEISHU_APP_SECRET", "").strip(),
            assistant_api=assistant_api,
            assistant_health_api=os.getenv(
                "LOCAL_ASSISTANT_HEALTH_API",
                "http://127.0.0.1:8000/api/v1/health",
            ).strip(),
            database_path=Path(
                os.getenv(
                    "FEISHU_STATE_DATABASE",
                    str(project_root / "data" / "feishu_channel.sqlite3"),
                )
            ).resolve(),
            access_mode=access_mode,
            default_role=default_role,
            allowed_users=parse_allowed_users(
                os.getenv("FEISHU_ALLOWED_USERS", ""),
                default_role,
            ),
            allow_p2p=_as_bool(os.getenv("FEISHU_ALLOW_P2P"), True),
            allow_group_at=_as_bool(os.getenv("FEISHU_ALLOW_GROUP_AT"), True),
            send_processing_message=_as_bool(
                os.getenv("FEISHU_SEND_PROCESSING_MESSAGE"), True
            ),
            worker_count=max(1, int(os.getenv("FEISHU_WORKER_COUNT", "4"))),
            query_timeout_seconds=max(
                5.0, float(os.getenv("FEISHU_QUERY_TIMEOUT_SECONDS", "90"))
            ),
            max_reply_chars=max(
                1000, int(os.getenv("FEISHU_MAX_REPLY_CHARS", "12000"))
            ),
            trust_env_proxy=_as_bool(
                os.getenv("FEISHU_TRUST_ENV_PROXY"), False
            ),
            reply_format=reply_format,
            card_template=os.getenv(
                "FEISHU_CARD_TEMPLATE", "blue"
            ).strip() or "blue",
            max_card_bytes=max(
                8000, int(os.getenv("FEISHU_MAX_CARD_BYTES", "28000"))
            ),
            identity_api=os.getenv(
                "LOCAL_IDENTITY_API",
                "http://127.0.0.1:8000/api/v1/identities/feishu",
            ).rstrip("/"),
            feedback_api=os.getenv(
                "LOCAL_FEISHU_FEEDBACK_API",
                "http://127.0.0.1:8000/api/v1/notifications/feishu/callback",
            ).strip(),
            confirm_api=os.getenv(
                "LOCAL_ASSISTANT_CONFIRM_API",
                "http://127.0.0.1:8000/api/v1/assistant/confirm",
            ).strip(),
            action_api_token=os.getenv("AI_TOOL_TOKEN", "").strip(),
        )

    def validate(self) -> None:
        if not self.app_id:
            raise ValueError("FEISHU_APP_ID is required")
        if not self.app_secret:
            raise ValueError("FEISHU_APP_SECRET is required")
        if not self.assistant_api.startswith(("http://", "https://")):
            raise ValueError("LOCAL_ASSISTANT_API must be an HTTP(S) URL")
        if self.access_mode == "allowlist" and not self.allowed_users:
            LOGGER.warning(
                "FEISHU_ALLOWED_USERS is empty. Users will only receive an "
                "authorization message containing their open_id."
            )

    def role_for(self, open_id: str) -> Optional[str]:
        configured = self.allowed_users.get(open_id)
        if configured:
            return configured
        if self.access_mode == "open":
            return self.default_role
        return None


@dataclass(frozen=True)
class FeishuMessage:
    event_id: str
    message_id: str
    chat_id: str
    chat_type: str
    open_id: str
    sender_type: str
    message_type: str
    question: str

    @property
    def user_id(self) -> str:
        return f"feishu:{self.open_id}"

    @property
    def conversation_id(self) -> str:
        if self.chat_type == "p2p":
            return f"feishu:p2p:{self.open_id}"
        return f"feishu:group:{self.chat_id}:{self.open_id}"


def _attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _strip_mentions(text: str, mentions: Iterable[Any]) -> str:
    result = text
    for mention in mentions:
        key = str(_attr(mention, "key", "") or "")
        name = str(_attr(mention, "name", "") or "")
        if key:
            result = result.replace(key, " ")
        if name:
            result = result.replace(f"@{name}", " ")
    return " ".join(result.split())


def parse_sdk_message(data: Any) -> FeishuMessage:
    """Convert the SDK event object into the channel-neutral message model."""
    header = _attr(data, "header")
    event = _attr(data, "event")
    message = _attr(event, "message")
    sender = _attr(event, "sender")
    sender_id = _attr(sender, "sender_id")

    raw_content = str(_attr(message, "content", "") or "")
    message_type = str(_attr(message, "message_type", "") or "")
    question = ""
    if message_type == "text" and raw_content:
        try:
            parsed_content = json.loads(raw_content)
            question = str(parsed_content.get("text", "") or "")
        except (TypeError, ValueError):
            question = raw_content
    question = _strip_mentions(question, _attr(message, "mentions", []) or [])

    return FeishuMessage(
        event_id=str(_attr(header, "event_id", "") or ""),
        message_id=str(_attr(message, "message_id", "") or ""),
        chat_id=str(_attr(message, "chat_id", "") or ""),
        chat_type=str(_attr(message, "chat_type", "") or ""),
        open_id=str(_attr(sender_id, "open_id", "") or ""),
        sender_type=str(_attr(sender, "sender_type", "") or ""),
        message_type=message_type,
        question=question,
    )


class FeishuEventStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS feishu_events (
                    event_id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    open_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    question TEXT,
                    received_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_feishu_events_received
                    ON feishu_events(received_at);
                """
            )

    def claim(self, message: FeishuMessage) -> bool:
        if not message.event_id:
            raise ValueError("Feishu event does not contain header.event_id")
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO feishu_events(
                        event_id, message_id, open_id, chat_id, status,
                        question, received_at
                    ) VALUES (?, ?, ?, ?, 'received', ?, ?)
                    """,
                    (
                        message.event_id,
                        message.message_id,
                        message.open_id,
                        message.chat_id,
                        message.question,
                        int(time.time()),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def complete(self, event_id: str, error_message: str | None = None) -> None:
        status = "failed" if error_message else "completed"
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE feishu_events
                SET status=?, completed_at=?, error_message=?
                WHERE event_id=?
                """,
                (status, int(time.time()), error_message, event_id),
            )


class AssistantGateway:
    def __init__(self, config: FeishuConfig):
        self.config = config

    def query(self, message: FeishuMessage, role: str) -> Dict[str, Any]:
        payload = {
            "question": message.question,
            "user_id": message.user_id,
            "conversation_id": message.conversation_id,
            "role": role,
            "response_mode": "blocking",
        }
        with httpx.Client(trust_env=False) as client:
            response = client.post(
                self.config.assistant_api,
                json=payload,
                timeout=self.config.query_timeout_seconds,
            )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise RuntimeError(f"Assistant API returned an error: {body}")
        result = body.get("data") or {}
        if not str(result.get("answer", "")).strip():
            raise RuntimeError("Assistant API returned an empty answer")
        return result

    def resolve_identity(self, open_id: str) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client(trust_env=False) as client:
                response = client.get(
                    f"{self.config.identity_api}/{open_id}", timeout=10
                )
            response.raise_for_status()
            body = response.json()
            return body.get("data") if body.get("success") else None
        except httpx.HTTPError:
            LOGGER.warning("Identity API unavailable; using environment allowlist")
            return None

    def submit_feedback(
        self,
        notification_id: str,
        actor_open_id: str,
        action: str,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = {}
        if self.config.action_api_token:
            headers["Authorization"] = f"Bearer {self.config.action_api_token}"
        with httpx.Client(trust_env=False) as client:
            response = client.post(
                self.config.feedback_api,
                headers=headers,
                json={
                    "notification_id": notification_id,
                    "actor_open_id": actor_open_id,
                    "action": action,
                    "feedback": feedback,
                },
                timeout=10,
            )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise RuntimeError(f"Feedback API returned an error: {body}")
        return body.get("data") or {}

    def confirm_management_action(
        self, confirmation_token: str, actor_open_id: str
    ) -> Dict[str, Any]:
        with httpx.Client(trust_env=False) as client:
            response = client.post(
                self.config.confirm_api,
                json={
                    "confirmation_token": confirmation_token,
                    "actor_open_id": actor_open_id,
                },
                timeout=30,
            )
        if response.status_code == 400:
            error_text = json.dumps(
                response.json(), ensure_ascii=False, default=str
            )
            if any(
                marker in error_text
                for marker in ("已经使用", "已经确认", "已经处理")
            ):
                return {"delivery_status": "already_processed"}
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise RuntimeError(
                f"Management action confirmation failed: {body}"
            )
        return body.get("data") or {}

    def check_health(self) -> Dict[str, Any]:
        with httpx.Client(trust_env=False) as client:
            response = client.get(
                self.config.assistant_health_api,
                timeout=10,
            )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise RuntimeError(f"Assistant health check failed: {body}")
        return body


class FeishuApiClient:
    TOKEN_URL = (
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
    )
    API_BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, config: FeishuConfig):
        self.config = config
        self._token = ""
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def _tenant_access_token(self) -> str:
        with self._token_lock:
            if self._token and time.time() < self._token_expires_at:
                return self._token
            try:
                with httpx.Client(
                    trust_env=self.config.trust_env_proxy
                ) as client:
                    response = client.post(
                        self.TOKEN_URL,
                        json={
                            "app_id": self.config.app_id,
                            "app_secret": self.config.app_secret,
                        },
                        timeout=15,
                    )
            except httpx.ConnectError as exc:
                mode = (
                    "环境代理"
                    if self.config.trust_env_proxy
                    else "直连（已忽略环境代理）"
                )
                raise RuntimeError(
                    f"无法通过{mode}连接飞书开放平台。"
                    "请检查代理软件、防火墙或企业网络策略；"
                    "如网络必须使用代理，请设置 "
                    "FEISHU_TRUST_ENV_PROXY=true。"
                ) from exc
            response.raise_for_status()
            body = response.json()
            if body.get("code") != 0:
                raise RuntimeError(
                    f"Unable to obtain Feishu tenant token: "
                    f"{body.get('code')} {body.get('msg')}"
                )
            self._token = str(body["tenant_access_token"])
            expires_in = max(600, int(body.get("expire", 7200)))
            self._token_expires_at = time.time() + expires_in - 300
            return self._token

    def check_credentials(self) -> None:
        self._tenant_access_token()

    def _reply(self, message_id: str, msg_type: str, content: Dict[str, Any]) -> None:
        with httpx.Client(
            trust_env=self.config.trust_env_proxy
        ) as client:
            response = client.post(
                f"{self.API_BASE}/im/v1/messages/{message_id}/reply",
                headers={
                    "Authorization": f"Bearer {self._tenant_access_token()}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "msg_type": msg_type,
                    "content": json.dumps(content, ensure_ascii=False),
                    "uuid": uuid.uuid4().hex,
                },
                timeout=20,
            )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(
                f"Unable to reply to Feishu message: "
                f"{body.get('code')} {body.get('msg')}"
            )

    def reply_text(self, message_id: str, text: str) -> None:
        reply = text.strip() or "当前未生成可显示的回复。"
        if len(reply) > self.config.max_reply_chars:
            suffix = "\n\n内容较长，已截断。请缩小查询范围后继续提问。"
            reply = reply[: self.config.max_reply_chars - len(suffix)] + suffix
        self._reply(message_id, "text", {"text": reply})

    @staticmethod
    def _answer_title(result: Dict[str, Any]) -> str:
        intent = str(result.get("intent", "") or "")
        titles = {
            "order_risk": "订单风险分析",
            "order_overview": "订单经营概况",
            "material_shortage": "物料缺料分析",
            "purchase_delay": "采购交付分析",
            "production_progress": "生产进度分析",
            "supplier_profile": "供应商经营画像",
            "supplier_recommendation": "供应商推荐",
            "order_cost": "订单成本分析",
            "cost_analysis": "订单成本分析",
            "quote": "报价测算",
            "quote_calculation": "报价测算",
            "material_price_scenario": "经营情景模拟",
            "scenario_simulation": "经营情景模拟",
            "receivables": "应收账款分析",
            "business_report": "经营报告",
            "policy_qa": "企业制度问答",
        }
        return titles.get(intent, "经营决策分析")

    def _answer_card(
        self,
        question: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        answer = str(result.get("answer", "") or "").strip()
        trace_id = str(result.get("trace_id", "") or "").strip()
        footer = "由制造企业经营决策助手生成"
        if trace_id:
            footer += f"  ·  追踪编号 {trace_id}"
        elements: list[Dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": answer,
                "text_align": "left",
                "text_size": "normal_v2",
            }
        ]
        management_actions = result.get("management_actions") or []
        if management_actions:
            elements.append(
                {
                    "tag": "markdown",
                    "content": "**可执行管理动作**",
                    "text_align": "left",
                    "margin": "16px 0px 0px 0px",
                }
            )
            for item in management_actions[:5]:
                priority = item.get("priority")
                priority_text = (
                    f"优先级{priority} · " if priority is not None else ""
                )
                elements.extend(
                    [
                        {
                            "tag": "markdown",
                            "content": (
                                f"{priority_text}{item.get('action', '')}\n"
                                f"接收人：{item.get('recipient_name', '')}"
                                f"（{item.get('responsible_department', '')}）"
                            ),
                            "text_align": "left",
                        },
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": item.get(
                                    "button_text", "确认发送管理动作"
                                ),
                            },
                            "type": "primary",
                            "value": {
                                "action": "confirm_management_action",
                                "confirmation_token": item.get(
                                    "confirmation_token", ""
                                ),
                                "management_action_id": item.get(
                                    "management_action_id", ""
                                ),
                            },
                        },
                    ]
                )
        elements.append(
            {
                "tag": "markdown",
                "content": f"<font color='grey'>{footer}</font>",
                "text_align": "left",
                "text_size": "notation",
                "margin": "12px 0px 0px 0px",
            }
        )
        return {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "style": {
                    "text_size": {
                        "normal_v2": {
                            "default": "normal",
                            "pc": "normal",
                            "mobile": "normal",
                        }
                    }
                },
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": self._answer_title(result),
                },
                "subtitle": {
                    "tag": "plain_text",
                    "content": question[:120],
                },
                "template": self.config.card_template,
                "text_tag_list": [
                    {
                        "tag": "text_tag",
                        "text": {
                            "tag": "plain_text",
                            "content": "AI分析",
                        },
                        "color": "blue",
                    }
                ],
                "padding": "12px 12px 12px 12px",
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }

    def reply_answer(
        self,
        message_id: str,
        question: str,
        result: Dict[str, Any],
    ) -> None:
        answer = str(result.get("answer", "") or "")
        if self.config.reply_format == "text":
            self.reply_text(message_id, answer)
            return
        card = self._answer_card(question, result)
        card_bytes = len(
            json.dumps(card, ensure_ascii=False).encode("utf-8")
        )
        if card_bytes > self.config.max_card_bytes:
            LOGGER.warning(
                "Feishu card is %d bytes; falling back to text", card_bytes
            )
            self.reply_text(message_id, answer)
            return
        try:
            self._reply(message_id, "interactive", card)
        except Exception:
            LOGGER.exception(
                "Unable to send Feishu card; falling back to text"
            )
            self.reply_text(message_id, answer)


class FeishuBotService:
    def __init__(
        self,
        config: FeishuConfig,
        store: FeishuEventStore,
        assistant: AssistantGateway,
        replies: FeishuApiClient,
    ):
        self.config = config
        self.store = store
        self.assistant = assistant
        self.replies = replies
        self.executor = ThreadPoolExecutor(
            max_workers=config.worker_count,
            thread_name_prefix="feishu-query",
        )

    def accept(self, message: FeishuMessage) -> bool:
        """Claim and enqueue an event; designed to return within three seconds."""
        if not self.store.claim(message):
            LOGGER.info("Ignoring duplicate Feishu event %s", message.event_id)
            return False
        self.executor.submit(self.process, message)
        return True

    def process(self, message: FeishuMessage) -> None:
        error_message: str | None = None
        try:
            if message.sender_type and message.sender_type != "user":
                return
            if not message.message_id or not message.open_id:
                raise ValueError("Feishu message is missing message_id or sender open_id")
            if message.chat_type == "p2p" and not self.config.allow_p2p:
                return
            if message.chat_type != "p2p" and not self.config.allow_group_at:
                return
            if message.message_type != "text":
                self.replies.reply_text(
                    message.message_id,
                    "当前版本支持文字经营问答，请输入订单、采购、供应商、"
                    "成本、报价或经营分析问题。",
                )
                return

            feedback_match = re.match(
                r"^反馈\s+([0-9a-fA-F-]{20,})\s+(.+)$",
                message.question or "",
                re.DOTALL,
            )
            if feedback_match:
                self.assistant.submit_feedback(
                    feedback_match.group(1), message.open_id,
                    "feedback", feedback_match.group(2).strip(),
                )
                self.replies.reply_text(message.message_id, "反馈已回传给老板/厂长。")
                return

            identity = (
                self.assistant.resolve_identity(message.open_id)
                if hasattr(self.assistant, "resolve_identity")
                else None
            )
            if identity and identity.get("authorized"):
                role = identity.get("assistant_role") if identity.get("can_use_agent") else None
            else:
                role = self.config.role_for(message.open_id)
            if role is None:
                self.replies.reply_text(
                    message.message_id,
                    "您尚未获得经营决策助手的使用权限（经营问数权限）。部门负责人可接收事项并回执，"
                    "经营问数仅向老板和厂长开放。\n\n"
                    f"您的飞书 open_id：{message.open_id}\n\n"
                    "请将该ID提供给系统管理员，由管理员加入使用白名单。",
                )
                return
            if not message.question:
                self.replies.reply_text(
                    message.message_id,
                    "请输入需要查询的经营问题，例如："
                    "销售-20260718-01为什么是高风险订单？",
                )
                return

            if self.config.send_processing_message:
                self.replies.reply_text(
                    message.message_id,
                    "正在分析业务数据，请稍候……",
                )
            result = self.assistant.query(message, role)
            self.replies.reply_answer(
                message.message_id,
                message.question,
                result,
            )
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            LOGGER.exception(
                "Failed to process Feishu event %s", message.event_id
            )
            try:
                self.replies.reply_text(
                    message.message_id,
                    "本次经营分析未能完成，请稍后重试。"
                    f"\n追踪编号：{message.event_id}",
                )
            except Exception:
                LOGGER.exception(
                    "Failed to send Feishu error reply for event %s",
                    message.event_id,
                )
        finally:
            self.store.complete(message.event_id, error_message)

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class QuoteRequest(BaseModel):
    product_code: str
    quantity: float = Field(gt=0)
    target_margin: float = Field(default=0.25, ge=0.0, le=0.60)
    options: Dict[str, Any] = Field(default_factory=dict)
    as_of_date: Optional[date] = None


class ScenarioRequest(BaseModel):
    scenario_type: str
    parameters: Dict[str, Any]
    as_of_date: Optional[date] = None


class ReportRequest(BaseModel):
    report_type: str = "daily"
    as_of_date: Optional[date] = None
    format: str = "markdown"

    @field_validator("report_type")
    @classmethod
    def validate_report_type(cls, value: str) -> str:
        if value not in {"daily", "weekly", "monthly"}:
            raise ValueError("report_type仅支持daily、weekly或monthly")
        return value

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        if value not in {"markdown", "json"}:
            raise ValueError("format仅支持markdown或json")
        return value


class ReportExportRequest(BaseModel):
    report_type: str = "daily"
    as_of_date: Optional[date] = None
    format: str

    @field_validator("report_type")
    @classmethod
    def validate_report_type(cls, value: str) -> str:
        if value not in {"daily", "weekly", "monthly"}:
            raise ValueError("report_type仅支持daily、weekly或monthly")
        return value

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        if value not in {"markdown", "json", "docx", "pdf", "xlsx"}:
            raise ValueError("format仅支持markdown、json、docx、pdf或xlsx")
        return value


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    as_of_date: Optional[date] = None
    conversation_id: Optional[str] = Field(default=None, max_length=128)
    user_id: str = Field(default="web-demo-user", min_length=1, max_length=128)
    role: str = Field(default="management", min_length=1, max_length=32)
    response_mode: str = "blocking"

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, value: str) -> str:
        if value not in {"blocking", "streaming"}:
            raise ValueError("response_mode仅支持blocking或streaming")
        return value


class AIToolRequest(BaseModel):
    trace_id: str = Field(min_length=8, max_length=128)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    as_of_date: Optional[date] = None

    @field_validator("parameters", mode="before")
    @classmethod
    def parse_parameters(cls, value: Any) -> Dict[str, Any]:
        """Accept Dify's JSON-string form while keeping object input compatible."""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            if len(value) > 20_000:
                raise ValueError("parameters内容过长")
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("parameters必须是有效的JSON字符串") from exc
            if not isinstance(parsed, dict):
                raise ValueError("parameters解析后必须是JSON对象")
            return parsed
        raise ValueError("parameters必须是JSON对象或JSON字符串")


class AssistantConfirmationRequest(BaseModel):
    confirmation_token: str = Field(min_length=20, max_length=256)
    actor_open_id: Optional[str] = Field(default=None, max_length=128)


class IdentityBindingRequest(BaseModel):
    employee_id: int = Field(gt=0)
    feishu_open_id: str = Field(min_length=4, max_length=128)
    access_role: str
    department_id: Optional[int] = Field(default=None, gt=0)
    plant_id: Optional[int] = Field(default=None, gt=0)
    actor_open_id: Optional[str] = Field(default=None, max_length=128)


class MessageProposalRequest(BaseModel):
    actor_open_id: str = Field(min_length=4, max_length=128)
    task_code: str = Field(min_length=2, max_length=64)
    recipient_employee_id: int = Field(gt=0)
    message_title: str = Field(min_length=2, max_length=200)
    message_body: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = Field(default=None, max_length=128)


class FeishuFeedbackRequest(BaseModel):
    notification_id: str = Field(min_length=8, max_length=128)
    actor_open_id: str = Field(min_length=4, max_length=128)
    action: str
    feedback: Optional[str] = Field(default=None, max_length=2000)


class NotificationRetryRequest(BaseModel):
    notification_id: str = Field(min_length=8, max_length=128)
    actor_open_id: str = Field(min_length=4, max_length=128)


class TaskCreateRequest(BaseModel):
    risk_event_id: Optional[int] = None
    task_title: str = Field(min_length=2, max_length=200)
    owner_employee_id: int = Field(gt=0)
    due_date: date
    priority: str = "中"

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        if value not in {"低", "中", "高"}:
            raise ValueError("priority仅支持低、中、高")
        return value


class TaskUpdateRequest(BaseModel):
    owner_employee_id: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[date] = None
    status: Optional[str] = None
    priority: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"待处理", "处理中", "已完成", "已关闭"}:
            raise ValueError("status值无效")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"低", "中", "高"}:
            raise ValueError("priority值无效")
        return value


class MessageCreateRequest(BaseModel):
    task_code: str
    recipient_employee_id: int = Field(gt=0)
    channel: str = "站内"
    message_title: str = Field(min_length=2, max_length=200)
    message_body: str = Field(min_length=1, max_length=4000)

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value not in {"站内", "企业微信", "钉钉", "邮件"}:
            raise ValueError("channel值无效")
        return value

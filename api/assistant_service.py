from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from business_engine import EntityNotFound, InvalidCalculationInput
from business_engine.core import DEFAULT_AS_OF, Repository

from .ai_store import AIAuditStore
from .ai_tools import AIToolService
from .store import OperationalStore


ORDER_CODE_PATTERN = re.compile(
    r"销售-(?:\d{8}-\d{2}|\d{6})|(?<![A-Za-z0-9-])SO(?:\d{8}|-\d{6})(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
PURCHASE_ORDER_CODE_PATTERN = re.compile(
    r"采购-(?:\d{8}-\d{2}|\d{6})|(?<![A-Za-z0-9-])PO(?:\d{8}|-\d{6})(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
EXPLICIT_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?!\d)"
)
MATERIAL_CODE_PATTERN = re.compile(
    r"物料-\d{4}|(?<![A-Za-z0-9-])M-[A-Z]{2,4}-\d{3}(?![A-Za-z0-9-])", re.IGNORECASE
)
SUPPLIER_CODE_PATTERN = re.compile(
    r"供应商-\d{4}|(?<![A-Za-z0-9-])S\d{4}(?![A-Za-z0-9-])", re.IGNORECASE
)
PRODUCT_CODE_PATTERN = re.compile(
    r"产品-\d{3}|(?<![A-Za-z0-9-])P\d{3}(?![A-Za-z0-9-])", re.IGNORECASE
)
BUSINESS_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])(-?\d[\d,]*(?:\.\d+)?)\s*(元|万元|%|分|天|项|张|笔|套)"
)
ISO_DATE_PATTERN = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
HELP_MENU_MARKER = "<!--HELP_MENU-->"


class DifyClient:
    def __init__(self) -> None:
        self.api_base = os.getenv("DIFY_API_BASE", "https://api.dify.ai/v1").rstrip("/")
        self.api_key = os.getenv("DIFY_APP_API_KEY", "").strip()
        self.workflow_version = os.getenv("DIFY_WORKFLOW_VERSION", "stage6-v1")
        self.model_provider = os.getenv("AI_MODEL_PROVIDER", "tongyi")
        self.model_name = os.getenv("QWEN_MODEL_NAME", "qwen-plus")
        self.deepseek_model_name = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")
        self.timeout = float(os.getenv("DIFY_TIMEOUT_SECONDS", "60"))
        self.retry_count = max(0, int(os.getenv("DIFY_RETRY_COUNT", "2")))
        self.retry_backoff = max(
            0.0, float(os.getenv("DIFY_RETRY_BACKOFF_SECONDS", "1"))
        )
        self.trust_env_proxy = os.getenv(
            "DIFY_TRUST_ENV_PROXY", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        *,
        question: str,
        as_of_date: str,
        conversation_id: Optional[str],
        user_id: str,
        role: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "inputs": {
                "as_of_date": as_of_date,
                "role": role,
                "trace_id": trace_id,
                "workflow_version": self.workflow_version,
            },
            "query": question,
            "response_mode": "blocking",
            "user": user_id,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        attempts = 0
        with httpx.Client(timeout=self.timeout, trust_env=self.trust_env_proxy) as client:
            for retry_index in range(self.retry_count + 1):
                attempts += 1
                try:
                    response = client.post(
                        f"{self.api_base}/chat-messages",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=payload,
                    )
                    response.raise_for_status()
                    result = response.json()
                    result["_gateway_attempts"] = attempts
                    return result
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    transient = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {429, 500, 502, 503, 504}
                    if retry_index >= self.retry_count or not transient:
                        raise
                    time.sleep(self.retry_backoff * (2 ** retry_index))
        raise RuntimeError("Dify调用未返回结果")


class NumberGroundingValidator:
    @staticmethod
    def _collect_numbers(value: Any, key: str = "") -> List[float]:
        numbers: List[float] = []
        if isinstance(value, bool) or value is None:
            return numbers
        if isinstance(value, (int, float)):
            number = float(value)
            numbers.append(number)
            if any(token in key.lower() for token in ("rate", "margin", "percent")):
                numbers.append(number * 100)
            return numbers
        if isinstance(value, str):
            for raw_value, unit in BUSINESS_NUMBER_PATTERN.findall(value):
                number = float(raw_value.replace(",", ""))
                numbers.append(number)
                if unit == "万元":
                    numbers.append(number * 10000)
            return numbers
        if isinstance(value, dict):
            for child_key, child in value.items():
                numbers.extend(NumberGroundingValidator._collect_numbers(child, str(child_key)))
        elif isinstance(value, list):
            for child in value:
                numbers.extend(NumberGroundingValidator._collect_numbers(child, key))
        return numbers

    @staticmethod
    def _collect_dates(value: Any) -> List[date]:
        dates: List[date] = []
        if isinstance(value, str):
            for raw_date in ISO_DATE_PATTERN.findall(value):
                try:
                    dates.append(date.fromisoformat(raw_date))
                except ValueError:
                    continue
            return dates
        if isinstance(value, dict):
            for child in value.values():
                dates.extend(NumberGroundingValidator._collect_dates(child))
        elif isinstance(value, list):
            for child in value:
                dates.extend(NumberGroundingValidator._collect_dates(child))
        return dates

    def validate(
        self,
        answer: str,
        tool_outputs: Iterable[Dict[str, Any]],
        trusted_inputs: Iterable[Any] = (),
    ) -> Tuple[bool, List[str]]:
        available: List[float] = []
        for trusted_input in trusted_inputs:
            available.extend(self._collect_numbers(trusted_input))
        for output in tool_outputs:
            available.extend(self._collect_numbers(output))
            trusted_dates = sorted(set(self._collect_dates(output)))
            for index, first in enumerate(trusted_dates):
                for second in trusted_dates[index + 1 :]:
                    available.append(float(abs((second - first).days)))
        unmatched = []
        for raw_value, unit in BUSINESS_NUMBER_PATTERN.findall(answer):
            value = float(raw_value.replace(",", ""))
            if unit == "万元":
                candidates = (value, value * 10000)
            else:
                candidates = (value,)
            if not any(
                abs(candidate - source) <= max(0.011, abs(source) * 0.0001)
                for candidate in candidates
                for source in available
            ):
                unmatched.append(f"{raw_value}{unit}")
        return not unmatched, unmatched


class AssistantService:
    SUGGESTIONS = [
        "销售-20260718-01为什么是高风险订单，应该怎么处理？",
        "针对销售-20260718-01，铜材上涨8%会有什么影响？",
        "销售-20260718-01目前有哪些缺料？",
        "当前应收账款风险如何？",
        "生成今天的经营日报摘要。",
    ]

    def __init__(
        self,
        *,
        tools: AIToolService,
        audit_store: AIAuditStore,
        operational_store: OperationalStore,
        repository: Repository,
        action_hub: Any = None,
    ):
        self.tools = tools
        self.audit_store = audit_store
        self.operational_store = operational_store
        self.repository = repository
        self.action_hub = action_hub
        self.dify = DifyClient()
        self.grounding = NumberGroundingValidator()

    @property
    def mode(self) -> str:
        return "dify-cloud" if self.dify.configured else "controlled-local"

    def query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        question = str(payload["question"]).strip()
        resolved = (
            payload.get("as_of_date")
            or self._extract_as_of_date(question)
            or DEFAULT_AS_OF
        )
        if isinstance(resolved, str):
            resolved = date.fromisoformat(resolved)
        trace_id = str(uuid.uuid4())
        conversation_id = self.audit_store.ensure_conversation(
            payload.get("conversation_id"),
            payload.get("user_id", "web-demo-user"),
            payload.get("role", "management"),
            self.dify.model_provider if self.dify.configured else "deterministic",
            self.dify.model_name if self.dify.configured else "controlled-rules",
            self.dify.workflow_version,
        )
        self.audit_store.log_message(
            conversation_id=conversation_id,
            trace_id=trace_id,
            message_role="user",
            content=question,
            status="received",
        )
        context = self.audit_store.latest_context(conversation_id)
        effective_question, correction_note = self._correct_entity_code(question)
        if self._is_write_request(effective_question):
            result = self._propose_action(
                effective_question, resolved, conversation_id, context
            )
        elif self.dify.configured:
            result = self._query_dify(
                effective_question,
                resolved,
                conversation_id,
                trace_id,
                payload,
            )
        else:
            result = self._query_local(
                effective_question,
                resolved,
                conversation_id,
                trace_id,
                context,
            )
            result.setdefault("warnings", []).append(
                "当前未配置Dify App API Key，使用受控本地编排；填写服务端环境变量后自动切换到通义千问工作流。"
            )
        if correction_note:
            result["answer"] = f"{correction_note}\n\n{result['answer']}"
            result.setdefault("warnings", []).append(correction_note)

        management_actions = self._prepare_management_actions(
            payload=payload,
            trace_id=trace_id,
            conversation_id=conversation_id,
        )
        if management_actions:
            result["management_actions"] = management_actions

        result.update(
            {
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "model": {
                    "mode": self.mode,
                    "provider": self.dify.model_provider if self.dify.configured else "deterministic",
                    "name": self.dify.model_name if self.dify.configured else "controlled-rules",
                    "workflow_version": self.dify.workflow_version,
                },
                "suggested_questions": result.get("suggested_questions")
                or self.SUGGESTIONS,
            }
        )
        if self.action_hub and (result.get("dify_gateway_attempts") or 1) > 1:
            self.action_hub.log_operation(
                "dify_retry",
                "completed",
                trace_id=trace_id,
                actor_open_id=payload.get("user_id"),
                actor_role=payload.get("role"),
                target_type="workflow",
                target_id=self.dify.workflow_version,
                result={"attempts": result["dify_gateway_attempts"]},
            )
        audit_id = self.audit_store.log_message(
            conversation_id=conversation_id,
            trace_id=trace_id,
            message_role="assistant",
            content=result["answer"],
            intent=result.get("intent"),
            model_provider=result["model"]["provider"],
            model_name=result["model"]["name"],
            workflow_version=self.dify.workflow_version,
            grounding_status=result.get("grounding_status", "trusted-tool-template"),
            token_input=(result.get("model_usage") or {}).get("input_tokens"),
            token_output=(result.get("model_usage") or {}).get("output_tokens"),
            token_total=(result.get("model_usage") or {}).get("total_tokens"),
            model_cost=(result.get("model_usage") or {}).get("total_price"),
            model_cost_currency=(result.get("model_usage") or {}).get("currency"),
            payload={
                "intent": result.get("intent"),
                "entities": result.get("entities", {}),
                "tool_calls": result.get("tool_calls", []),
                "confirmation": result.get("confirmation"),
                "model_usage": result.get("model_usage", {}),
                "dify_gateway_attempts": result.get("dify_gateway_attempts"),
            },
        )
        result["message_id"] = audit_id
        result["audit_id"] = audit_id
        return result

    @staticmethod
    def _extract_as_of_date(question: str) -> Optional[date]:
        match = EXPLICIT_DATE_PATTERN.search(question)
        if not match:
            return None
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            raise InvalidCalculationInput("问题中的日期无效，请使用YYYY-MM-DD格式")

    @staticmethod
    def _is_write_request(question: str) -> bool:
        return (
            ("任务" in question and any(word in question for word in ("创建", "新建", "分派", "关闭")))
            or ("消息" in question and "发送" in question)
        )

    def _propose_action(
        self,
        question: str,
        resolved: date,
        conversation_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not ("任务" in question and any(word in question for word in ("创建", "新建"))):
            raise InvalidCalculationInput("当前仅支持通过AI提议创建风险任务，其他写操作请在风险任务页面完成")
        order_code = self._order_code(question) or context.get("entities", {}).get("order_code")
        if not order_code:
            raise InvalidCalculationInput("请先说明需要为哪个订单创建风险任务")
        risk = self.repository.one(
            """
            SELECT risk_event_id, risk_code, summary, risk_score
            FROM risk_events
            WHERE entity_code=?
            ORDER BY risk_score DESC, risk_event_id LIMIT 1
            """,
            (order_code,),
        )
        if not risk:
            raise InvalidCalculationInput(f"订单{order_code}没有可关联的风险事件")
        owner = self.repository.one(
            "SELECT employee_id, employee_name FROM employees WHERE employee_id=12"
        ) or self.repository.one(
            "SELECT employee_id, employee_name FROM employees ORDER BY employee_id LIMIT 1"
        )
        task_payload = {
            "risk_event_id": risk["risk_event_id"],
            "task_title": f"处理{order_code}交付风险",
            "owner_employee_id": owner["employee_id"],
            "due_date": (resolved + timedelta(days=1)).isoformat(),
            "priority": "高",
        }
        preview = {
            "任务标题": task_payload["task_title"],
            "关联订单": order_code,
            "风险说明": risk["summary"],
            "负责人": owner["employee_name"],
            "截止日期": task_payload["due_date"],
            "优先级": task_payload["priority"],
        }
        confirmation = self.audit_store.create_confirmation(
            conversation_id, "create_task", task_payload, preview
        )
        return {
            "answer": "任务尚未创建。请核对下方任务内容，确认后系统才会写入风险任务。",
            "intent": "create_task",
            "entities": {"order_code": order_code},
            "tool_calls": [],
            "metrics": [],
            "visualization": None,
            "sources": [
                {"source_table": "risk_events", "record_code": risk["risk_code"]}
            ],
            "warnings": [],
            "confirmation": confirmation,
        }

    def confirm(self, token: str, actor_open_id: Optional[str] = None) -> Dict[str, Any]:
        confirmation = self.audit_store.consume_confirmation(token)
        if confirmation["action_type"] == "create_task":
            task = self.operational_store.create_task(confirmation["payload"])
            if self.action_hub:
                self.action_hub.log_operation("task_created_after_confirmation", "completed", actor_open_id=actor_open_id, target_type="task", target_id=task["task_code"], result=task)
            return {
                "answer": f"风险任务{task['task_code']}已创建，并已分派给{task.get('employee_name') or '指定负责人'}。",
                "action_type": "create_task",
                "result": task,
                "conversation_id": confirmation["conversation_id"],
                "sources": [{"source_table": "tasks", "record_code": task["task_code"]}],
            }
        if confirmation["action_type"] == "send_department_message" and self.action_hub:
            expected_actor = confirmation["payload"].get("actor_open_id")
            if actor_open_id and actor_open_id != expected_actor:
                raise InvalidCalculationInput("确认人和消息发起人不一致")
            result = self.action_hub.execute_confirmed_message(confirmation)
            notification = result["notification"]
            delivery_status = notification["status"]
            if delivery_status in {"sent", "acknowledged"}:
                answer = "消息已写入站内消息并成功发送至飞书。"
            elif delivery_status == "failed":
                answer = (
                    "消息已写入站内消息；飞书首次投递失败，"
                    "系统已保留失败记录并将按补偿机制继续重试。"
                )
            else:
                answer = (
                    "消息已写入站内消息；飞书消息正在处理，"
                    "可稍后查看最终投递状态。"
                )
            return {
                "answer": answer,
                "action_type": "send_department_message",
                "delivery_status": delivery_status,
                "retry_pending": delivery_status == "failed",
                "result": result,
                "conversation_id": confirmation["conversation_id"],
                "sources": [{"source_table": "outbound_notifications", "record_code": notification["notification_id"]}],
            }
        if confirmation["action_type"] == "send_management_action" and self.action_hub:
            expected_actor = confirmation["payload"].get("actor_open_id")
            if not actor_open_id or actor_open_id != expected_actor:
                raise InvalidCalculationInput("确认人和管理动作发起人不一致")
            result = self.action_hub.execute_confirmed_management_action(
                confirmation
            )
            notification = result["notification"]
            delivery_status = notification["status"]
            if delivery_status in {"sent", "acknowledged"}:
                answer = "管理动作已成功发送至部门负责人飞书。"
            elif delivery_status == "failed":
                answer = (
                    "管理动作首次投递失败，系统已保留记录并将按补偿机制重试。"
                )
            else:
                answer = "管理动作正在投递，可稍后查看最终状态。"
            return {
                "answer": answer,
                "action_type": "send_management_action",
                "delivery_status": delivery_status,
                "retry_pending": delivery_status == "failed",
                "result": result,
                "conversation_id": confirmation["conversation_id"],
                "sources": [
                    {
                        "source_table": "management_action_messages",
                        "record_code": result["management_action"][
                            "management_action_id"
                        ],
                    },
                    {
                        "source_table": "outbound_notifications",
                        "record_code": notification["notification_id"],
                    },
                ],
            }
        raise InvalidCalculationInput("不支持的确认操作")

    def _prepare_management_actions(
        self,
        *,
        payload: Dict[str, Any],
        trace_id: str,
        conversation_id: str,
    ) -> List[Dict[str, Any]]:
        if not self.action_hub:
            return []
        user_id = str(payload.get("user_id") or "")
        if not user_id.startswith("feishu:"):
            return []
        actor_open_id = user_id.removeprefix("feishu:").strip()
        if not actor_open_id:
            return []
        report_actions: List[Dict[str, Any]] = []
        for call in reversed(self.audit_store.list_tool_calls(trace_id)):
            if call.get("tool_name") != "generate_business_report":
                continue
            output = call.get("output") or {}
            structured = (
                ((output.get("data") or {}).get("structured_data")) or {}
            )
            report_actions = structured.get("top_actions") or []
            break
        if not report_actions:
            return []
        try:
            return self.action_hub.prepare_management_actions(
                trace_id=trace_id,
                conversation_id=conversation_id,
                actor_open_id=actor_open_id,
                actions=report_actions,
            )
        except (EntityNotFound, InvalidCalculationInput):
            return []

    def _query_dify(
        self,
        question: str,
        resolved: date,
        conversation_id: str,
        trace_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        dify_conversation_id = self.audit_store.get_dify_conversation_id(
            conversation_id
        )
        dify_question = question
        if "关键物料" in question and not any(
            word in question for word in ("缺料", "短缺", "齐套")
        ):
            # “有哪些关键物料”在本项目的经营问答中指订单缺料/齐套情况。
            # 给Dify分类器补充明确语义，避免误分到订单概况。
            dify_question = f"{question}（请按订单缺料与物料齐套情况分析）"
        try:
            raw = self.dify.chat(
                question=dify_question,
                as_of_date=resolved.isoformat(),
                conversation_id=dify_conversation_id,
                user_id=payload.get("user_id", "web-demo-user"),
                role=payload.get("role", "management"),
                trace_id=trace_id,
            )
        except (httpx.HTTPError, ValueError) as exc:
            local = self._query_local(
                question,
                resolved,
                conversation_id,
                trace_id,
                self.audit_store.latest_context(conversation_id),
            )
            local.setdefault("warnings", []).append(
                f"Dify Cloud调用失败，已明确降级为受控本地编排：{exc}"
            )
            return local
        returned_dify_conversation_id = str(
            raw.get("conversation_id", "") or ""
        ).strip()
        if returned_dify_conversation_id:
            self.audit_store.set_dify_conversation_id(
                conversation_id,
                returned_dify_conversation_id,
            )
        parsed = self._parse_dify_answer(raw.get("answer", ""))
        calls = self.audit_store.list_tool_calls(trace_id)
        if (
            "关键物料" in question
            and not any(
                item.get("tool_name")
                in {"get_material_shortages", "get_order_fulfillment"}
                for item in calls
            )
        ):
            corrected = self._query_local(
                question,
                resolved,
                conversation_id,
                trace_id,
                self.audit_store.latest_context(conversation_id),
            )
            corrected.setdefault("warnings", []).append(
                "Dify意图分类未进入缺料分支，系统已自动纠偏为订单缺料分析。"
            )
            return corrected
        if (
            self._is_material_price_scenario(question)
            and not any(
                item.get("tool_name") == "run_procurement_scenario"
                for item in calls
            )
        ):
            corrected = self._query_local(
                question,
                resolved,
                conversation_id,
                trace_id,
                self.audit_store.latest_context(conversation_id),
            )
            corrected.setdefault("warnings", []).append(
                "Dify未调用价格情景模拟工具，系统已自动纠偏为确定性成本与毛利测算。"
            )
            return corrected
        outputs = [item["output"] for item in calls if item.get("output")]
        answer = parsed.get("answer") or raw.get("answer") or "Dify未返回可展示的答案。"
        is_static_help = answer.lstrip().startswith(HELP_MENU_MARKER)
        if is_static_help:
            answer = answer.lstrip()[len(HELP_MENU_MARKER):].lstrip()
        trusted_inputs = [question] + [
            item["input"] for item in calls if item.get("input")
        ]
        if is_static_help:
            valid, unmatched = True, []
        else:
            valid, unmatched = self.grounding.validate(
                answer,
                outputs,
                trusted_inputs=trusted_inputs,
            )
        if not valid:
            answer = (
                "大模型回答包含无法从业务工具结果核验的数字，系统已拦截。"
                f"未匹配内容：{'、'.join(unmatched)}。请重新提问或查看数据依据。"
            )
        sources = self._collect_sources(calls)
        metadata = raw.get("metadata") or {}
        usage = metadata.get("usage") or {}
        return {
            "answer": answer,
            "intent": parsed.get("intent", "dify_workflow"),
            "entities": parsed.get("entities", {}),
            "key_findings": parsed.get("key_findings", []),
            "metrics": parsed.get("metrics", []),
            "visualization": parsed.get("visualization"),
            "tool_calls": self._tool_summaries(calls),
            "sources": sources,
            "warnings": parsed.get("warnings", []),
            "confirmation": parsed.get("confirmation"),
            "grounding_status": (
                "trusted-static-help"
                if is_static_help
                else "passed" if valid else "blocked"
            ),
            "model_usage": {
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "total_price": usage.get("total_price"),
                "currency": usage.get("currency"),
            },
            "dify_gateway_attempts": raw.get("_gateway_attempts", 1),
        }

    @staticmethod
    def _parse_dify_answer(answer: str) -> Dict[str, Any]:
        text = answer.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {"answer": answer}
        except json.JSONDecodeError:
            return {"answer": answer}

    def _query_local(
        self,
        question: str,
        resolved: date,
        conversation_id: str,
        trace_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        order_code = self._order_code(question) or context.get("entities", {}).get("order_code")
        calls: List[Dict[str, Any]] = []

        def call(name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
            output = self.tools.call(name, parameters, resolved, trace_id)
            calls.append({"tool_name": name, "output": output})
            return output

        purchase_order_code = self._purchase_order_code(question)
        if purchase_order_code and any(
            word in question for word in ("采购", "迟交", "到货", "交付", "供应商")
        ):
            output = call(
                "get_purchase_delays",
                {"purchase_order_code": purchase_order_code},
            )
            detail = output["data"]
            items = detail.get("items", [])
            affected_orders = sorted(
                {item["sales_order_code"] for item in items}
            )
            answer_lines = [
                f"采购订单{purchase_order_code}共识别到"
                f"{detail['delay_record_count']}条迟交影响记录。"
            ]
            for item in items[:5]:
                answer_lines.append(
                    f"- {item['material_name']}（{item['material_code']}）"
                    f"预计{item['expected_delivery_date']}到货，"
                    f"影响销售订单{item['sales_order_code']}，"
                    f"晚于订单交期{item['late_vs_order_days']}天。"
                )
            if not items:
                answer_lines.append("当前没有识别到该采购订单造成的迟交影响。")
            result = self._local_result(
                "\n".join(answer_lines),
                "purchase_delay",
                affected_orders[0] if len(affected_orders) == 1 else None,
                calls,
                detail,
                "table",
            )
            result["entities"]["purchase_order_code"] = purchase_order_code
            return result

        if self._is_material_price_scenario(question):
            if not order_code:
                order_code = "销售-20260718-01"
            rate_match = re.search(r"(\d+(?:\.\d+)?)\s*%", question)
            rate = float(rate_match.group(1)) / 100 if rate_match else 0.08
            output = call(
                "run_procurement_scenario",
                {
                    "scenario_type": "material_price_change",
                    "parameters": {
                        "order_code": order_code,
                        "material_code": "物料-0001",
                        "change_rate": rate,
                    },
                },
            )
            detail = output["data"]["result"]
            margin_change_points = abs(detail["margin_change"] * 100)
            warning_text = (
                "测算后毛利率低于预警阈值，需要启动低毛利评审。"
                if detail.get("low_margin_warning")
                else "测算后毛利率尚未触发低毛利预警。"
            )
            answer = "\n".join(
                [
                    "一、情景测算结论",
                    (
                        f"如果电解铜板（物料-0001）价格上涨{rate*100:.2f}%，"
                        f"订单{order_code}的完整成本将增加"
                        f"{detail['cost_change']:,.2f}元，毛利率下降"
                        f"{margin_change_points:.2f}个百分点。"
                    ),
                    "",
                    "二、成本与毛利变化",
                    f"- 原完整成本：{detail['original_cost']:,.2f}元。",
                    f"- 测算后完整成本：{detail['new_cost']:,.2f}元。",
                    f"- 成本增加：{detail['cost_change']:,.2f}元。",
                    (
                        f"- 毛利率：由{detail['original_margin_rate']*100:.2f}%"
                        f"下降至{detail['new_margin_rate']*100:.2f}%。"
                    ),
                    f"- 预警判断：{warning_text}",
                    "",
                    "三、建议管理动作",
                    "1. 核实电解铜板（物料-0001）最新采购价格及在途采购单，确认涨价是否已经实际发生。",
                    "2. 评估替代供应商、锁价采购或批量议价方案，降低材料价格波动影响。",
                    "3. 如无法消化成本上涨，重新评估订单报价、毛利底线和客户商务策略。",
                    "",
                    "四、计算与数据依据",
                    (
                        f"本次按物料价格上涨{rate*100:.2f}%进行确定性情景测算；"
                        "成本和毛利数字来自业务计算引擎。"
                    ),
                ]
            )
            return self._local_result(
                answer, "material_price_scenario", order_code, calls, detail, "comparison"
            )
        if ("风险" in question or "延期" in question) and order_code:
            risk = call("get_order_risk", {"order_code": order_code})
            if "怎么处理" in question or "原因" in question or "为什么" in question:
                call("get_order_fulfillment", {"order_code": order_code})
                call("get_purchase_delays", {"order_code": order_code})
                call("get_production_progress", {"order_code": order_code})
            detail = risk["data"]
            component_text = "；".join(
                f"{item['reason']}（{item['score']}分）"
                for item in detail.get("risk_components", [])
            )
            answer = (
                f"订单{order_code}综合风险分为{detail['risk_score']}分，"
                f"风险等级为{detail['risk_level']}。风险构成为：{component_text}。"
            )
            if len(calls) > 1:
                answer += "建议优先确认关键物料补齐计划，其次跟进迟交采购单，并同步追赶生产进度。"
            return self._local_result(
                answer, "order_risk", order_code, calls, detail, "risk_score"
            )
        if any(word in question for word in ("缺料", "短缺", "齐套", "关键物料")):
            output = call(
                "get_material_shortages",
                {"order_code": order_code} if order_code else {},
            )
            detail = output["data"]
            scope = f"订单{order_code}" if order_code else "当前全部订单"
            critical_items = [
                item for item in detail.get("items", []) if item.get("is_critical")
            ]
            answer_lines = [
                f"截至{resolved.isoformat()}，{scope}共识别到"
                f"{detail['shortage_record_count']}项缺料，其中"
                f"{detail['critical_shortage_record_count']}项为关键物料短缺。"
            ]
            for item in (critical_items or detail.get("items", []))[:5]:
                recovery = item.get("expected_recovery_date") or "尚未确认"
                answer_lines.append(
                    f"- {item['material_name']}（{item['material_code']}）："
                    f"短缺{item['shortage_qty_display']}，预计补齐日期{recovery}。"
                )
            if detail.get("remaining_record_count", 0):
                answer_lines.append(
                    f"其余{detail['remaining_record_count']}项请在缺料分析页面查看。"
                )
            answer = "\n".join(answer_lines)
            return self._local_result(
                answer, "material_shortage", order_code, calls, detail, "table"
            )
        if "生产" in question or "进度" in question:
            if not order_code:
                raise InvalidCalculationInput("请提供需要分析的订单编号")
            output = call("get_production_progress", {"order_code": order_code})
            detail = output["data"]
            planned_finish = date.fromisoformat(detail["planned_finish_date"])
            basis_date = date.fromisoformat(detail["progress_basis_date"])
            overdue_days = max((basis_date - planned_finish).days, 0)
            schedule_text = (
                f"当前已超过计划完工日{overdue_days}天。"
                if overdue_days
                else "当前尚未超过计划完工日。"
            )
            answer = "\n".join(
                [
                    f"订单{order_code}生产进度分析",
                    (
                        f"- 生产订单：{detail['production_order_code']}，"
                        f"计划周期为{detail['planned_start_date']}至"
                        f"{detail['planned_finish_date']}。"
                    ),
                    (
                        f"- 进度基准日：{detail['progress_basis_date']}；"
                        f"实际进度数据更新至{detail['actual_progress_data_date']}。"
                    ),
                    (
                        f"- 理论进度：{detail['expected_progress_rate']:.2f}%；"
                        f"实际进度：{detail['actual_progress_rate']:.2f}%；"
                        f"偏差{detail['deviation_points']:.2f}个百分点。"
                    ),
                    f"- 当前状态：{detail['status']}；{schedule_text}",
                    (
                        "- 建议：立即核查未完工工序、关键物料和产能安排，"
                        "明确追赶计划并同步评估对销售订单交付的影响。"
                    ),
                ]
            )
            return self._local_result(
                answer, "production_progress", order_code, calls, detail, "table"
            )
        if "应收" in question or "回款" in question or "账龄" in question:
            output = call("get_receivables", {})
            detail = output["data"]
            answer = (
                f"当前未收金额为{detail['total_outstanding_amount']:,.2f}元，"
                f"逾期金额为{detail['total_overdue_amount']:,.2f}元，"
                f"高风险应收{detail['high_risk_count']}笔。"
            )
            return self._local_result(
                answer, "receivables", order_code, calls, detail, "metrics"
            )
        if "日报" in question or "周报" in question or "月报" in question or "经营报告" in question:
            report_type = "weekly" if "周报" in question else "monthly" if "月报" in question else "daily"
            output = call("generate_business_report", {"report_type": report_type})
            detail = output["data"]["structured_data"]
            answer = self._format_business_report(detail, resolved)
            return self._local_result(
                answer, "business_report", order_code, calls, detail, "metrics"
            )
        if any(word in question for word in ("制度", "规定", "办法", "审批", "口径")):
            output = call("search_enterprise_policy", {"query": question})
            items = output["data"]["items"]
            if not items:
                answer = "当前企业知识库中没有找到对应制度依据。"
            else:
                excerpts = [excerpt for item in items for excerpt in item["excerpts"]][:3]
                answer = "根据企业演示制度资料：\n" + "\n".join(f"- {item}" for item in excerpts)
            return self._local_result(
                answer, "policy_qa", order_code, calls, output["data"], "document"
            )
        if order_code and any(word in question for word in ("订单", "客户", "交期", "金额")):
            output = call("get_order_overview", {"order_code": order_code})
            detail = output["data"]
            answer = (
                f"订单{order_code}客户为{detail['customer_name']}，订单金额"
                f"{detail['order_amount']:,.2f}元，承诺交期为"
                f"{detail['promised_delivery_date']}，当前状态为{detail['status']}。"
            )
            return self._local_result(
                answer, "order_overview", order_code, calls, detail, "metrics"
            )
        raise InvalidCalculationInput(
            "当前问题缺少可识别的业务对象。请提供订单、物料、供应商或报告类型，或选择推荐问题。"
        )

    @staticmethod
    def _format_business_report(detail: Dict[str, Any], resolved: date) -> str:
        report_name = detail.get("report_type_display", "经营报告")
        risk_amount = detail.get("risk_order_amount_display")
        if not risk_amount:
            risk_amount = f"{detail.get('risk_order_amount', 0):,.2f}元"

        lines = [
            f"一、{report_name}概览",
            (
                f"{report_name}，报告基准日：{resolved.isoformat()}，"
                "覆盖订单交付、供应保障、成本管控及应收管理等核心经营环节。"
            ),
            "",
            "二、核心经营指标",
            (
                f"- 订单与风险：未来7天待交付订单"
                f"{detail.get('upcoming_7d_order_count', 0)}张，风险订单"
                f"{detail.get('risk_order_count', 0)}张，高风险订单"
                f"{detail.get('high_risk_order_count', 0)}张，风险影响金额{risk_amount}。"
            ),
            (
                f"- 供应与采购：缺料{detail.get('shortage_count', 0)}项，"
                f"采购迟交{detail.get('purchase_delay_count', 0)}项，"
                f"采购价格异常{detail.get('price_anomaly_count', 0)}项。"
            ),
            (
                f"- 成本与应收：低毛利订单"
                f"{detail.get('low_margin_order_count', 0)}张，"
                f"高风险应收{detail.get('high_risk_receivable_count', 0)}笔。"
            ),
        ]

        period = detail.get("period_metrics") or {}
        if period:
            lines.extend(
                [
                    "",
                    "本期发生",
                    (
                        f"统计期间：{detail.get('period_start')}至"
                        f"{detail.get('period_end')}（含首尾日期）。"
                    ),
                    (
                        f"- 新增销售订单{period['sales'].get('order_count', 0)}张，"
                        f"金额{period['sales'].get('order_amount', 0):,.2f}元；"
                        f"采购订单{period['procurement'].get('purchase_order_count', 0)}张，"
                        f"金额{period['procurement'].get('purchase_amount', 0):,.2f}元。"
                    ),
                    (
                        f"- 完工生产订单{period['production'].get('completed_order_count', 0)}张；"
                        f"发货{period['shipments'].get('shipment_count', 0)}笔，"
                        f"金额{period['shipments'].get('shipment_amount', 0):,.2f}元；"
                        f"回款{period['payments'].get('payment_count', 0)}笔，"
                        f"金额{period['payments'].get('payment_amount', 0):,.2f}元。"
                    ),
                ]
            )

        risk_orders = detail.get("high_risk_orders") or []
        if risk_orders:
            lines.extend(["", "三、重点风险订单"])
            for index, item in enumerate(risk_orders, 1):
                amount = item.get("potential_amount_display")
                if not amount:
                    amount = f"{item.get('potential_amount', 0):,.2f}元"
                lines.append(
                    f"{index}. {item.get('sales_order_code', '未知订单')}："
                    f"交付日期{item.get('promised_delivery_date', '未确认')}，"
                    f"风险分{item.get('risk_score', 0)}，"
                    f"等级{item.get('risk_level', '未判定')}，"
                    f"缺料{item.get('shortage_line_count', 0)}项，"
                    f"影响金额{amount}。"
                )
            scope_note = detail.get("high_risk_order_scope_display")
            if scope_note:
                lines.append(scope_note)

        actions = detail.get("top_actions") or []
        if actions:
            lines.extend(["", "四、建议管理动作"])
            for index, item in enumerate(actions, 1):
                lines.append(
                    f"{index}. {item.get('action', '待确认管理动作')}"
                    f"；责任部门：{item.get('owner', '待确认')}。"
                )

        lines.extend(
            [
                "",
                "五、数据说明",
                "以上业务数字均来自业务工具返回结果；可继续追问具体订单、缺料、采购迟交或应收明细。",
            ]
        )
        return "\n".join(lines)

    def _local_result(
        self,
        answer: str,
        intent: str,
        order_code: Optional[str],
        calls: List[Dict[str, Any]],
        result: Dict[str, Any],
        visualization: Optional[str],
    ) -> Dict[str, Any]:
        sources = []
        warnings = []
        for item in calls:
            sources.extend(item["output"]["meta"].get("sources", []))
            warnings.extend(item["output"]["meta"].get("warnings", []))
        return {
            "answer": answer,
            "intent": intent,
            "entities": {"order_code": order_code} if order_code else {},
            "key_findings": [],
            "metrics": self._metrics_from_result(result),
            "result": result,
            "visualization": visualization,
            "tool_calls": [
                {
                    "tool_name": item["tool_name"],
                    "status": "success",
                    "calculation_id": item["output"]["meta"].get("calculation_id"),
                }
                for item in calls
            ],
            "sources": self._deduplicate_sources(sources),
            "warnings": list(dict.fromkeys(warnings)),
            "confirmation": None,
            "grounding_status": "trusted-tool-template",
        }

    @staticmethod
    def _metrics_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        preferred = (
            "risk_score",
            "count",
            "cost_change",
            "original_margin_rate",
            "new_margin_rate",
            "total_outstanding_amount",
            "total_overdue_amount",
            "high_risk_count",
        )
        return [
            {"code": key, "value": result[key]}
            for key in preferred
            if key in result
        ]

    @staticmethod
    def _is_material_price_scenario(question: str) -> bool:
        normalized = question.upper()
        has_material = "铜" in question or "物料-0001" in question or "物料-0001" in normalized
        has_change = any(
            word in question for word in ("上涨", "涨价", "变化", "上升", "提高")
        )
        return has_material and has_change

    @staticmethod
    def _order_code(question: str) -> Optional[str]:
        match = ORDER_CODE_PATTERN.search(question)
        return match.group(0).upper() if match else None

    @staticmethod
    def _purchase_order_code(question: str) -> Optional[str]:
        match = PURCHASE_ORDER_CODE_PATTERN.search(question)
        return match.group(0).upper() if match else None

    def _correct_entity_code(self, question: str) -> Tuple[str, Optional[str]]:
        order_code = self._order_code(question)
        if not order_code or not any(
            word in question for word in ("采购", "迟交", "到货", "供应商")
        ):
            return question, None
        if self.repository.one(
            "SELECT 1 FROM sales_orders WHERE sales_order_code=?",
            (order_code,),
        ):
            return question, None
        candidate = (
            f"采购-{order_code[len('销售-'):]}"
            if order_code.startswith("销售-")
            else f"PO{order_code[2:]}"
        )
        if not self.repository.one(
            "SELECT 1 FROM purchase_orders WHERE purchase_order_code=?",
            (candidate,),
        ):
            return question, None
        note = (
            f"未找到销售订单{order_code}；根据问题中的采购语义，"
            f"已自动识别为采购订单{candidate}。"
        )
        return question.replace(order_code, candidate), note

    @staticmethod
    def _deduplicate_sources(
        sources: Iterable[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        result, seen = [], set()
        for source in sources:
            key = (
                source.get("source_table") or source.get("type"),
                source.get("record_code") or source.get("code"),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(source)
        return result

    def _collect_sources(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self._deduplicate_sources(
            source for call in calls for source in call.get("sources", [])
        )

    @staticmethod
    def _tool_summaries(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "tool_name": item["tool_name"],
                "status": item["status"],
                "duration_ms": item["duration_ms"],
                "calculation_id": item.get("calculation_id"),
                "error": item.get("error_text"),
            }
            for item in calls
        ]

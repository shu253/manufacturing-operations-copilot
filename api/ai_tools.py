from __future__ import annotations

import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from business_engine import (
    BusinessEngine,
    EntityNotFound,
    InvalidCalculationInput,
)
from business_engine.core import DEFAULT_AS_OF, Repository

from .ai_store import AIAuditStore


TOOL_NAMES = {
    "get_dashboard_summary",
    "get_order_overview",
    "get_order_risk",
    "get_order_fulfillment",
    "get_material_shortages",
    "get_purchase_delays",
    "get_production_progress",
    "get_supplier_profile",
    "recommend_suppliers",
    "get_order_cost",
    "calculate_quote",
    "run_procurement_scenario",
    "get_receivables",
    "generate_business_report",
    "search_enterprise_policy",
}

SOURCE_NAMES = {
    "production_material_requirements": "生产物料需求",
    "purchase_orders": "采购订单",
    "production_orders": "生产订单",
    "sales_orders": "销售订单",
    "materials": "物料主数据",
    "supplier_monthly_metrics": "供应商月度指标",
    "receivable_invoices": "应收发票",
}
SOURCE_NAMES.update(
    {
        "bom_lines": "产品物料清单",
        "products": "产品标准成本参数",
        "material_price_history": "物料采购价格历史",
    }
)


class AIToolService:
    def __init__(
        self,
        engine: BusinessEngine,
        repository: Repository,
        audit_store: AIAuditStore,
        knowledge_path: Path,
    ):
        self.engine = engine
        self.repository = repository
        self.audit_store = audit_store
        self.knowledge_path = knowledge_path

    @staticmethod
    def _resolved_date(value: Optional[date | str]) -> date:
        if value is None:
            return DEFAULT_AS_OF
        return value if isinstance(value, date) else date.fromisoformat(value)

    @staticmethod
    def _required(parameters: Dict[str, Any], key: str) -> Any:
        value = parameters.get(key)
        if value in (None, ""):
            raise InvalidCalculationInput(f"缺少必要参数: {key}")
        return value

    def _data_as_of_date(self) -> Optional[str]:
        row = self.repository.one(
            "SELECT MAX(snapshot_date) AS data_as_of_date "
            "FROM inventory_balances"
        )
        return row["data_as_of_date"] if row else None

    def _envelope(self, tool_name: str, envelope: Any) -> Dict[str, Any]:
        raw = envelope.to_dict()
        latest_data_date = self._data_as_of_date()
        warnings = list(raw["warnings"])
        if (
            latest_data_date
            and date.fromisoformat(latest_data_date)
            < date.fromisoformat(raw["as_of_date"])
        ):
            warnings.append(
                f"当前分析基于截至{latest_data_date}的业务数据，"
                f"可能不包含{latest_data_date}之后发生的业务变化。"
            )
        sources = [
            {
                **source,
                "source_name": SOURCE_NAMES.get(
                    source["source_table"], "业务数据记录"
                ),
            }
            for source in raw["evidence"]
        ]
        return {
            "success": True,
            "tool_name": tool_name,
            "data": raw["result"],
            "meta": {
                "as_of_date": raw["as_of_date"],
                "data_as_of_date": latest_data_date,
                "formula_version": raw["formula_version"],
                "calculation_id": raw["calculation_id"],
                "sources": sources,
                "warnings": list(dict.fromkeys(warnings)),
            },
        }

    def call(
        self,
        tool_name: str,
        parameters: Optional[Dict[str, Any]],
        as_of_date: Optional[date | str],
        trace_id: str,
    ) -> Dict[str, Any]:
        if tool_name not in TOOL_NAMES:
            raise InvalidCalculationInput(f"不允许调用的AI工具: {tool_name}")
        params = dict(parameters or {})
        forbidden = {"sql", "query_sql", "database_path", "table_name", "url"}
        if forbidden.intersection(params):
            raise InvalidCalculationInput("AI工具参数包含被禁止的数据库或网络控制字段")
        started = time.perf_counter()
        output = None
        try:
            output = self._dispatch(
                tool_name, params, self._resolved_date(as_of_date)
            )
            duration = int((time.perf_counter() - started) * 1000)
            self.audit_store.log_tool_call(
                trace_id=trace_id,
                tool_name=tool_name,
                parameters=params,
                output=output,
                status="success",
                duration_ms=duration,
                calculation_id=output["meta"].get("calculation_id"),
                sources=output["meta"].get("sources", []),
            )
            return output
        except Exception as exc:
            duration = int((time.perf_counter() - started) * 1000)
            self.audit_store.log_tool_call(
                trace_id=trace_id,
                tool_name=tool_name,
                parameters=params,
                output=output,
                status="failed",
                duration_ms=duration,
                error_text=str(exc),
            )
            raise

    @staticmethod
    def _trim_number(value: Any, decimal_places: int = 4) -> str:
        number = Decimal(str(value))
        text = f"{number:,.{decimal_places}f}"
        return text.rstrip("0").rstrip(".")

    @classmethod
    def _quantity_display(cls, value: Any, unit: Optional[str]) -> str:
        number = Decimal(str(value))
        unit_text = (unit or "").strip()
        discrete_units = {"件", "个", "台", "套", "只", "支", "根", "张", "盒"}
        display = cls._trim_number(number)
        if not unit_text:
            return f"{display}（计量单位未返回）"
        if unit_text in discrete_units:
            if number == number.to_integral_value():
                return f"{int(number):,}{unit_text}"
            return f"{display}{unit_text}（标准成本耗用量）"
        return f"{display} {unit_text}"

    @staticmethod
    def _money_display(value: Any) -> str:
        return f"{Decimal(str(value)):,.2f}元"

    @staticmethod
    def _rate_display(value: Any) -> str:
        return f"{Decimal(str(value)) * Decimal('100'):.2f}%"

    @classmethod
    def _unit_price_display(cls, value: Any, unit: Optional[str]) -> str:
        display = cls._money_display(value)
        return f"{display}/{unit}" if unit else f"{display}（计价单位未返回）"

    @classmethod
    def _format_order_cost_response(
        cls, response: Dict[str, Any]
    ) -> Dict[str, Any]:
        data = response["data"]
        unit = data.get("unit")
        components = data.get("components", {})
        data["order_quantity_display"] = cls._quantity_display(
            data["quantity"], unit
        )
        data["full_cost_display"] = cls._money_display(components["total"])
        data["sales_revenue_display"] = cls._money_display(data["sales_revenue"])
        data["gross_profit_display"] = cls._money_display(data["gross_profit"])
        data["gross_margin_rate_display"] = cls._rate_display(
            data["gross_margin_rate"]
        )
        data["low_margin_warning_display"] = (
            "是" if data["low_margin_warning"] else "否"
        )

        labels = {
            "material": "材料成本",
            "labor": "人工成本",
            "outsource": "外协成本",
            "overhead": "制造费用",
            "logistics": "包装物流",
            "total": "完整成本合计",
        }
        data["components_display"] = [
            {
                "code": code,
                "label": labels[code],
                "amount": components[code],
                "amount_display": cls._money_display(components[code]),
            }
            for code in labels
            if code in components
        ]

        formatted_materials = []
        for material in data.get("material_details", []):
            item = dict(material)
            item["quantity_display"] = cls._quantity_display(
                material["quantity"], material.get("unit")
            )
            item["unit_price_display"] = cls._unit_price_display(
                material["unit_price"], material.get("unit")
            )
            item["amount_display"] = cls._money_display(material["amount"])
            if material.get("material_cost_share") is not None:
                item["material_cost_share_display"] = cls._rate_display(
                    material["material_cost_share"]
                )
            formatted_materials.append(item)

        # AI经营问答只返回主要成本物料，避免完整BOM占满上下文并造成回答截断。
        # 完整物料明细仍由成本穿透页面和原业务接口提供。
        formatted_materials.sort(
            key=lambda item: Decimal(str(item.get("amount", 0))),
            reverse=True,
        )
        display_limit = 5
        data["material_record_count"] = len(formatted_materials)
        data["displayed_material_count"] = min(
            len(formatted_materials), display_limit
        )
        data["remaining_material_count"] = max(
            len(formatted_materials) - display_limit, 0
        )
        data["is_material_details_truncated"] = (
            len(formatted_materials) > display_limit
        )
        data["material_detail_scope_display"] = (
            f"仅展示材料金额最高的{data['displayed_material_count']}项；"
            f"其余{data['remaining_material_count']}项请在成本穿透页面查看。"
            if data["remaining_material_count"]
            else "已展示全部物料成本明细。"
        )
        data["material_details"] = formatted_materials[:display_limit]
        return response

    @classmethod
    def _format_scenario_response(
        cls, response: Dict[str, Any]
    ) -> Dict[str, Any]:
        data = response["data"]
        result = data.get("result", {})
        if not isinstance(result, dict):
            return response

        money_fields = (
            "original_cost",
            "new_cost",
            "cost_change",
        )
        for field in money_fields:
            if field in result:
                result[f"{field}_display"] = cls._money_display(result[field])

        rate_fields = (
            "change_rate",
            "original_margin_rate",
            "new_margin_rate",
            "low_margin_threshold",
        )
        for field in rate_fields:
            if field in result:
                result[f"{field}_display"] = cls._rate_display(result[field])
        if "margin_change" in result:
            result["margin_change_display"] = (
                f"{float(result['margin_change']) * 100:.2f}个百分点"
            )

        if "low_margin_warning" in result:
            result["low_margin_warning_display"] = (
                "是" if result["low_margin_warning"] else "否"
            )
        return response

    @classmethod
    def _format_receivables_response(
        cls, response: Dict[str, Any]
    ) -> Dict[str, Any]:
        data = response["data"]
        for field in (
            "total_outstanding_amount",
            "total_overdue_amount",
            "partial_payment_outstanding_amount",
            "shipped_not_invoiced_amount",
        ):
            data[f"{field}_display"] = cls._money_display(data[field])

        for bucket in data.get("aging_summary", []):
            bucket["outstanding_amount_display"] = cls._money_display(
                bucket["outstanding_amount"]
            )

        receivables = []
        for row in data.get("receivables", []):
            item = dict(row)
            for field in (
                "invoice_amount",
                "paid_amount",
                "outstanding_amount",
            ):
                item[f"{field}_display"] = cls._money_display(item[field])
            item["payment_status_display"] = (
                "部分回款" if Decimal(str(item["paid_amount"])) > 0 else "未回款"
            )
            receivables.append(item)

        receivable_limit = 10
        data["receivable_record_count"] = len(receivables)
        data["displayed_receivable_count"] = min(
            len(receivables), receivable_limit
        )
        data["remaining_receivable_count"] = max(
            len(receivables) - receivable_limit, 0
        )
        data["is_receivable_details_truncated"] = (
            len(receivables) > receivable_limit
        )
        data["receivable_detail_scope_display"] = (
            f"仅展示风险最高的{data['displayed_receivable_count']}笔应收；"
            f"其余{data['remaining_receivable_count']}笔请在应收与回款页面查看。"
            if data["remaining_receivable_count"]
            else "已展示全部未结清应收明细。"
        )
        data["receivables"] = receivables[:receivable_limit]

        uninvoiced = []
        for row in data.get("shipped_not_invoiced", []):
            item = dict(row)
            item["shipment_amount_display"] = cls._money_display(
                item["shipment_amount"]
            )
            uninvoiced.append(item)
        uninvoiced_limit = 10
        data["displayed_shipped_not_invoiced_count"] = min(
            len(uninvoiced), uninvoiced_limit
        )
        data["remaining_shipped_not_invoiced_count"] = max(
            len(uninvoiced) - uninvoiced_limit, 0
        )
        data["is_shipped_not_invoiced_truncated"] = (
            len(uninvoiced) > uninvoiced_limit
        )
        data["shipped_not_invoiced_scope_display"] = (
            f"仅展示金额最高的{data['displayed_shipped_not_invoiced_count']}笔；"
            f"其余{data['remaining_shipped_not_invoiced_count']}笔"
            "请在应收与回款页面查看。"
            if data["remaining_shipped_not_invoiced_count"]
            else "已展示全部已发货未开票明细。"
        )
        data["shipped_not_invoiced"] = uninvoiced[:uninvoiced_limit]
        return response

    @classmethod
    def _format_business_report_response(
        cls, response: Dict[str, Any]
    ) -> Dict[str, Any]:
        data = response["data"]
        report_type = data["report_type"]
        report_names = {
            "daily": "经营日报",
            "weekly": "经营周报",
            "monthly": "经营月报",
        }
        data["report_type_display"] = report_names[report_type]
        structured = data["structured_data"]
        structured["report_type_display"] = report_names[report_type]
        structured["risk_order_amount_display"] = cls._money_display(
            structured["risk_order_amount"]
        )

        high_risk_orders = []
        for row in structured.get("high_risk_orders", []):
            if row.get("risk_level") != "高":
                continue
            high_risk_orders.append(
                {
                    "sales_order_code": row["sales_order_code"],
                    "promised_delivery_date": row["promised_delivery_date"],
                    "risk_score": row["risk_score"],
                    "risk_level": row["risk_level"],
                    "shortage_line_count": row["shortage_line_count"],
                    "potential_amount": row["potential_amount"],
                    "potential_amount_display": cls._money_display(
                        row["potential_amount"]
                    ),
                }
            )

        display_limit = 5
        structured["high_risk_order_detail_count"] = len(high_risk_orders)
        structured["displayed_high_risk_order_count"] = min(
            len(high_risk_orders), display_limit
        )
        structured["remaining_high_risk_order_count"] = max(
            len(high_risk_orders) - display_limit, 0
        )
        structured["is_high_risk_order_details_truncated"] = (
            len(high_risk_orders) > display_limit
        )
        structured["high_risk_order_scope_display"] = (
            f"仅展示风险分最高的{structured['displayed_high_risk_order_count']}张；"
            f"其余{structured['remaining_high_risk_order_count']}张"
            "请在订单风险中心查看。"
            if structured["remaining_high_risk_order_count"]
            else "已展示全部高风险订单明细。"
        )
        structured["high_risk_orders"] = high_risk_orders[:display_limit]
        return response

    @classmethod
    def _format_quote_response(
        cls, response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare a compact, customer-readable quote payload for Dify."""
        data = response["data"]
        unit = data.get("unit")

        quantity_display = cls._quantity_display(data["quantity"], unit)
        data["quote_quantity_display"] = quantity_display
        data["quantity_display"] = quantity_display
        for key in (
            "base_cost",
            "urgency_cost",
            "estimated_cost",
            "break_even_price",
            "target_price",
            "target_gross_profit",
        ):
            data[f"{key}_display"] = cls._money_display(data[key])
        data["target_unit_price_display"] = cls._unit_price_display(
            data["target_unit_price"], unit
        )
        data["urgency_surcharge_rate_display"] = cls._rate_display(
            data["urgency_surcharge_rate"]
        )
        data["target_margin_rate_display"] = cls._rate_display(
            data["target_margin_rate"]
        )

        for item in data.get("cost_breakdown", []):
            item["amount_display"] = cls._money_display(item["amount"])
            item["share_display"] = cls._rate_display(
                item["share_of_base_cost"]
            )
        for item in data.get("quote_composition", []):
            item["amount_display"] = cls._money_display(item["amount"])
            item["share_display"] = cls._rate_display(
                item["share_of_target_price"]
            )

        historical = data.get("historical_reference")
        if historical:
            for key in (
                "unit_price_low",
                "unit_price_median",
                "unit_price_high",
                "total_price_low",
                "total_price_high",
            ):
                historical[f"{key}_display"] = cls._money_display(
                    historical[key]
                )
            for key in ("margin_min", "margin_median", "margin_max"):
                historical[f"{key}_display"] = cls._rate_display(
                    historical[key]
                )
            range_method_names = {
                "p25_p75": "单价P25—P75",
                "P25-P75": "单价P25—P75",
                "min_max": "单价最小值—最大值",
                "min-max": "单价最小值—最大值",
            }
            historical["range_method_display"] = range_method_names.get(
                historical.get("range_method"),
                str(historical.get("range_method") or "历史单价区间"),
            )
            historical["unit_price_range_display"] = (
                f"{cls._unit_price_display(historical['unit_price_low'], unit)}—"
                f"{cls._unit_price_display(historical['unit_price_high'], unit)}"
            )
            historical["total_price_range_display"] = (
                f"{cls._money_display(historical['total_price_low'])}—"
                f"{cls._money_display(historical['total_price_high'])}"
            )

        formatted_materials = []
        for material in data.get("material_details", []):
            item = dict(material)
            item["quantity_display"] = cls._quantity_display(
                material["quantity"], material.get("unit")
            )
            item["unit_price_display"] = cls._unit_price_display(
                material["unit_price"], material.get("unit")
            )
            item["amount_display"] = cls._money_display(material["amount"])
            if material.get("material_cost_share") is not None:
                item["material_cost_share_display"] = cls._rate_display(
                    material["material_cost_share"]
                )
            formatted_materials.append(item)

        formatted_materials.sort(
            key=lambda item: Decimal(str(item.get("amount", 0))),
            reverse=True,
        )
        display_limit = 5
        data["material_record_count"] = len(formatted_materials)
        data["displayed_material_count"] = min(
            len(formatted_materials), display_limit
        )
        data["remaining_material_count"] = max(
            len(formatted_materials) - display_limit, 0
        )
        data["is_material_details_truncated"] = (
            len(formatted_materials) > display_limit
        )
        data["material_detail_scope_display"] = (
            f"仅展示材料金额最高的{data['displayed_material_count']}项；"
            f"其余{data['remaining_material_count']}项请在报价页面查看。"
            if data["remaining_material_count"]
            else "已展示全部材料成本依据。"
        )
        data["material_details"] = formatted_materials[:display_limit]
        return response

    def _dispatch(
        self, tool_name: str, parameters: Dict[str, Any], resolved: date
    ) -> Dict[str, Any]:
        if tool_name == "get_dashboard_summary":
            return self._envelope(tool_name, self.engine.generate_daily_brief(resolved))
        if tool_name == "get_order_risk":
            return self._envelope(
                tool_name,
                self.engine.calculate_order_risk(
                    self._required(parameters, "order_code"), resolved
                ),
            )
        if tool_name == "get_order_fulfillment":
            response = self._envelope(
                tool_name,
                self.engine.analyze_order_fulfillment(
                    self._required(parameters, "order_code"), resolved
                ),
            )
            data = response["data"]
            data["line_kitting_rate_display"] = self._rate_display(
                data["line_kitting_rate"]
            )
            data["quantity_kitting_rate_display"] = self._rate_display(
                data["quantity_kitting_rate"]
            )
            return response
        if tool_name == "get_material_shortages":
            filters = {
                key: parameters[key]
                for key in ("order_code", "material_code")
                if parameters.get(key)
            }
            response = self._envelope(
                tool_name, self.engine.analyze_material_shortages(filters, resolved)
            )
            items = response["data"]["items"]
            display_limit = 10
            response["data"]["items"] = items[:display_limit]
            response["data"]["displayed_record_count"] = min(
                len(items), display_limit
            )
            response["data"]["remaining_record_count"] = max(
                len(items) - display_limit, 0
            )
            response["data"]["is_truncated"] = len(items) > display_limit
            return response
        if tool_name == "get_purchase_delays":
            order_code = parameters.get("order_code")
            purchase_order_code = parameters.get("purchase_order_code")
            # Dify 参数提取器过去只有 order_code 字段，用户直接询问采购单时
            # 会把 PO 编号放进 order_code。若该编号只存在于采购订单表，
            # 自动按采购订单解释，兼容现有线上工作流。
            if order_code and not purchase_order_code:
                is_sales_order = self.repository.one(
                    "SELECT 1 FROM sales_orders WHERE sales_order_code=?",
                    (order_code,),
                )
                is_purchase_order = self.repository.one(
                    "SELECT 1 FROM purchase_orders WHERE purchase_order_code=?",
                    (order_code,),
                )
                if is_purchase_order and not is_sales_order:
                    purchase_order_code = order_code
                    order_code = None
            filters = {
                key: value
                for key, value in (
                    ("order_code", order_code),
                    ("purchase_order_code", purchase_order_code),
                    ("material_code", parameters.get("material_code")),
                    ("supplier_code", parameters.get("supplier_code")),
                )
                if value
            }
            response = self._envelope(
                tool_name, self.engine.evaluate_purchase_delays(filters, resolved)
            )
            items = response["data"]["items"]
            display_limit = 10
            response["data"]["items"] = items[:display_limit]
            response["data"]["displayed_record_count"] = min(
                len(items), display_limit
            )
            response["data"]["remaining_record_count"] = max(
                len(items) - display_limit, 0
            )
            response["data"]["is_truncated"] = len(items) > display_limit
            return response
        if tool_name == "get_production_progress":
            return self._envelope(
                tool_name,
                self.engine.evaluate_production_progress(
                    self._required(parameters, "order_code"), resolved
                ),
            )
        if tool_name == "get_order_cost":
            response = self._envelope(
                tool_name,
                self.engine.calculate_order_cost(
                    self._required(parameters, "order_code"), resolved
                ),
            )
            return self._format_order_cost_response(response)
        if tool_name == "calculate_quote":
            margin = float(parameters.get("target_margin", 0.25))
            if not 0 <= margin <= 0.60:
                raise InvalidCalculationInput("target_margin必须在0到0.60之间")
            response = self._envelope(
                tool_name,
                self.engine.calculate_quote(
                    self._required(parameters, "product_code"),
                    float(self._required(parameters, "quantity")),
                    margin,
                    parameters.get("options") or {},
                    resolved,
                ),
            )
            return self._format_quote_response(response)
        if tool_name == "run_procurement_scenario":
            response = self._envelope(
                tool_name,
                self.engine.run_procurement_scenario(
                    self._required(parameters, "scenario_type"),
                    parameters.get("parameters") or {},
                    resolved,
                ),
            )
            return self._format_scenario_response(response)
        if tool_name == "get_receivables":
            filters = {
                key: parameters[key]
                for key in ("customer_code", "order_code")
                if parameters.get(key)
            }
            response = self._envelope(
                tool_name, self.engine.analyze_receivables(filters, resolved)
            )
            return self._format_receivables_response(response)
        if tool_name == "recommend_suppliers":
            return self._envelope(
                tool_name,
                self.engine.recommend_suppliers(
                    self._required(parameters, "material_code"),
                    float(self._required(parameters, "quantity")),
                    self._required(parameters, "need_by_date"),
                    resolved,
                ),
            )
        if tool_name == "get_supplier_profile":
            supplier_code = self._required(parameters, "supplier_code")
            profile = self.repository.one(
                "SELECT * FROM suppliers WHERE supplier_code=?", (supplier_code,)
            )
            if not profile:
                raise EntityNotFound(f"供应商不存在: {supplier_code}")
            metrics = self.engine.calculate_supplier_metrics(
                supplier_code, int(parameters.get("period", 12)), resolved
            )
            output = self._envelope(tool_name, metrics)
            output["data"] = {"profile": profile, "metrics": output["data"]}
            output["meta"]["sources"].insert(
                0, {"source_table": "suppliers", "record_code": supplier_code}
            )
            return output
        if tool_name == "get_order_overview":
            order_code = self._required(parameters, "order_code")
            latest_data_date = self._data_as_of_date()
            order = self.repository.one(
                """
                SELECT so.sales_order_code, so.order_date,
                       so.promised_delivery_date, so.order_amount, so.status,
                       c.customer_code, c.customer_name, p.plant_name
                FROM sales_orders so
                JOIN customers c ON c.customer_id=so.customer_id
                JOIN plants p ON p.plant_id=so.plant_id
                WHERE so.sales_order_code=?
                """,
                (order_code,),
            )
            if not order:
                raise EntityNotFound(f"销售订单不存在: {order_code}")
            warnings = []
            if (
                latest_data_date
                and date.fromisoformat(latest_data_date) < resolved
            ):
                warnings.append(
                    f"当前订单概况基于截至{latest_data_date}的业务数据，"
                    f"可能不包含{latest_data_date}之后发生的业务变化。"
                )
            return {
                "success": True,
                "tool_name": tool_name,
                "data": order,
                "meta": {
                    "as_of_date": resolved.isoformat(),
                    "data_as_of_date": latest_data_date,
                    "formula_version": "3.0.0",
                    "calculation_id": None,
                    "sources": [
                        {
                            "source_table": "sales_orders",
                            "source_name": "销售订单",
                            "record_code": order_code,
                        }
                    ],
                    "warnings": warnings,
                },
            }
        if tool_name == "generate_business_report":
            report_type = parameters.get("report_type", "daily")
            if report_type not in {"daily", "weekly", "monthly"}:
                raise InvalidCalculationInput("report_type仅支持daily、weekly或monthly")
            output = self._envelope(
                tool_name,
                self.engine.generate_business_report(report_type, resolved),
            )
            output["data"] = {
                "report_type": report_type,
                "structured_data": output["data"],
            }
            return self._format_business_report_response(output)
        if tool_name == "search_enterprise_policy":
            return self._search_policy(
                str(self._required(parameters, "query")), resolved
            )
        raise InvalidCalculationInput(f"未实现的AI工具: {tool_name}")

    def _search_policy(self, query: str, resolved: date) -> Dict[str, Any]:
        normalized = re.sub(r"[\s，。？！；：、,.?!;:（）()]+", "", query)
        vocabulary = {
            "采购管理", "采购申请", "供应商选择", "采购异常", "人工审批",
            "供应商", "供应商管理", "准入", "替代供应商", "综合评价",
            "综合评分", "评价维度", "评分权重", "价格", "交付", "质量",
            "响应", "稳定性", "完整成本", "成本", "报价", "目标报价",
            "毛利率", "材料", "人工", "外协", "制造费用", "包装物流",
            "订单风险", "风险评分", "风险规则", "关键物料短缺",
            "采购预计迟交", "生产进度落后", "质量返工", "距交期不足",
            "总分封顶", "低风险", "中风险", "高风险", "交期",
            "经营日报", "经营周报", "经营月报", "经营报告", "管理动作",
        }
        keywords = {term for term in vocabulary if term in normalized}
        concept_aliases = {
            ("综合评分", "供应商评分", "供应商评价"): {
                "供应商", "综合评价", "评价维度", "评分权重",
                "价格", "交付", "质量", "响应", "稳定性",
            },
            ("订单风险", "风险评分", "风险规则"): {
                "订单风险", "风险评分", "关键物料短缺",
                "采购预计迟交", "生产进度落后", "质量返工",
                "距交期不足", "总分封顶", "低风险", "中风险", "高风险",
            },
            ("完整成本", "成本构成", "报价成本"): {
                "完整成本", "材料", "人工", "外协", "制造费用", "包装物流",
            },
            ("报价", "目标报价", "毛利率"): {
                "完整成本", "目标报价", "目标毛利率", "毛利政策",
            },
            ("采购制度", "采购管理", "采购规定"): {
                "采购管理", "采购申请", "供应商选择", "采购异常", "人工审批",
            },
            ("供应商管理", "供应商制度", "供应商办法"): {
                "供应商管理", "准入要求", "评价维度", "风险处理",
            },
            ("经营日报", "经营周报", "经营月报", "经营报告"): {
                "经营报告", "经营日报", "经营周报", "经营月报",
                "核心指标", "管理动作",
            },
        }
        for triggers, related_terms in concept_aliases.items():
            if any(trigger in normalized for trigger in triggers):
                keywords.update(related_terms)

        matches = []
        for path in sorted(self.knowledge_path.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = lines[0].lstrip("# ").strip() if lines else path.stem
            score = sum(
                text.count(keyword) * max(len(keyword), 2)
                for keyword in keywords
            )
            score += sum(
                max(len(keyword), 2) * 3
                for keyword in keywords
                if keyword in title or keyword in path.stem
            )
            if score:
                scored_lines = []
                for index, line in enumerate(lines):
                    if line.startswith("#") or line == "本资料仅用于智能体功能演示。":
                        continue
                    line_score = sum(
                        line.count(keyword) * max(len(keyword), 2)
                        for keyword in keywords
                    )
                    if line_score:
                        scored_lines.append((line_score, index, line))
                scored_lines.sort(key=lambda item: (-item[0], item[1]))
                matches.append(
                    {
                        "document": path.name,
                        "document_title": title,
                        "score": score,
                        "excerpts": [item[2] for item in scored_lines[:8]],
                    }
                )
        matches.sort(key=lambda item: item["score"], reverse=True)
        if matches:
            relevance_threshold = max(6, matches[0]["score"] * 0.25)
            matches = [
                item for item in matches
                if item["score"] >= relevance_threshold
            ]
        return {
            "success": True,
            "tool_name": "search_enterprise_policy",
            "data": {"query": query, "count": len(matches), "items": matches[:5]},
            "meta": {
                "as_of_date": resolved.isoformat(),
                "formula_version": "policy-kb-1.0",
                "calculation_id": None,
                "sources": [
                    {"source_table": "enterprise_knowledge", "record_code": item["document"]}
                    for item in matches[:5]
                ],
                "warnings": [] if matches else ["未找到匹配的企业制度资料"],
            },
        }

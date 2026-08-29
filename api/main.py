from __future__ import annotations

import sqlite3
import uuid
import hmac
import os
import json
from io import BytesIO
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from business_engine import (
    BusinessEngine,
    BusinessEngineError,
    EntityNotFound,
    InvalidCalculationInput,
    SQLiteRepository,
)
from business_engine.core import DEFAULT_AS_OF

from .common import error_response, from_calculation, success
from .models import (
    AIToolRequest,
    AskRequest,
    AssistantConfirmationRequest,
    FeishuFeedbackRequest,
    IdentityBindingRequest,
    MessageCreateRequest,
    MessageProposalRequest,
    NotificationRetryRequest,
    QuoteRequest,
    ReportExportRequest,
    ReportRequest,
    ScenarioRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
)
from .action_hub import ActionHub
from .ai_store import AIAuditStore
from .ai_tools import AIToolService
from .assistant_service import AssistantService
from .report_export import (
    export_docx,
    export_json,
    export_markdown,
    export_pdf,
    export_xlsx,
)
from .store import OperationalStore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "huadong_jinggong_demo.sqlite3"


def _engine(request: Request) -> BusinessEngine:
    return request.app.state.engine


def _repo(request: Request) -> SQLiteRepository:
    return request.app.state.repository


def _store(request: Request) -> OperationalStore:
    return request.app.state.store


def _action_hub(request: Request) -> ActionHub:
    return request.app.state.action_hub


def _date_text(value: Optional[date]) -> str:
    return (value or DEFAULT_AS_OF).isoformat()


def _metric_query(
    repository: SQLiteRepository, metric: str, as_of: date
) -> Dict[str, Any]:
    queries = {
        "sales_order_summary": (
            """
            SELECT COUNT(*) order_count,
                   ROUND(SUM(order_amount),2) order_amount,
                   ROUND(AVG(order_amount),2) average_order_amount
            FROM sales_orders
            WHERE order_date<=?
            """,
            (as_of.isoformat(),),
            ["sales_orders"],
        ),
        "procurement_summary": (
            """
            SELECT COUNT(*) purchase_order_count,
                   ROUND(SUM(order_amount),2) purchase_amount,
                   COUNT(DISTINCT supplier_id) supplier_count
            FROM purchase_orders
            WHERE order_date<=?
            """,
            (as_of.isoformat(),),
            ["purchase_orders"],
        ),
        "production_summary": (
            """
            SELECT COUNT(*) production_order_count,
                   ROUND(AVG(progress_rate),2) average_progress_rate,
                   SUM(CASE WHEN status='已完成' THEN 1 ELSE 0 END) completed_count
            FROM production_orders
            WHERE planned_start_date<=?
            """,
            (as_of.isoformat(),),
            ["production_orders"],
        ),
        "receivables_summary": (
            """
            SELECT COUNT(*) receivable_count,
                   ROUND(SUM(outstanding_amount),2) outstanding_amount,
                   ROUND(SUM(CASE WHEN overdue_days>0 THEN outstanding_amount ELSE 0 END),2)
                       overdue_amount
            FROM ar_snapshots
            WHERE snapshot_date<=?
            """,
            (as_of.isoformat(),),
            ["ar_snapshots"],
        ),
        "supplier_summary": (
            """
            SELECT COUNT(*) supplier_count,
                   SUM(CASE WHEN status='合格' THEN 1 ELSE 0 END) qualified_count,
                   SUM(CASE WHEN risk_level='高' THEN 1 ELSE 0 END) high_risk_count
            FROM suppliers
            """,
            (),
            ["suppliers"],
        ),
    }
    if metric not in queries:
        raise InvalidCalculationInput(
            f"不支持的经营指标: {metric}；可选值为{','.join(queries)}"
        )
    sql, params, sources = queries[metric]
    return {
        "metric": metric,
        "as_of_date": as_of.isoformat(),
        "values": repository.one(sql, params) or {},
        "sources": sources,
    }


def _render_report(report_type: str, brief: Dict[str, Any], as_of: str) -> str:
    names = {"daily": "经营日报", "weekly": "经营周报", "monthly": "经营月报"}
    actions = brief.get("top_actions", [])
    action_lines = "\n".join(
        f"{index}. {item['action']}（责任：{item['owner']}）"
        for index, item in enumerate(actions, 1)
    ) or "1. 当前无紧急管理动作。"
    period = brief.get("period_metrics", {})
    period_lines = ""
    if period:
        period_lines = (
            f"## 本期发生\n\n"
            f"统计期间：{brief['period_start']}至{brief['period_end']}（含首尾日期）\n\n"
            f"- 新增销售订单：{period['sales']['order_count']}张，金额{period['sales']['order_amount']:,.2f}元\n"
            f"- 采购订单：{period['procurement']['purchase_order_count']}张，金额{period['procurement']['purchase_amount']:,.2f}元\n"
            f"- 完工生产订单：{period['production']['completed_order_count']}张\n"
            f"- 发货：{period['shipments']['shipment_count']}笔，金额{period['shipments']['shipment_amount']:,.2f}元\n"
            f"- 回款：{period['payments']['payment_count']}笔，金额{period['payments']['payment_amount']:,.2f}元\n\n"
        )
    return (
        f"# 华东某精工装备有限公司{names[report_type]}\n\n"
        f"报告基准日：{as_of}\n\n"
        f"{period_lines}"
        "## 核心指标\n\n"
        f"- 未来7天待交付订单：{brief['upcoming_7d_order_count']}张\n"
        f"- 高风险订单：{brief['high_risk_order_count']}张\n"
        f"- 缺料项：{brief['shortage_count']}项\n"
        f"- 采购迟交项：{brief['purchase_delay_count']}项\n"
        f"- 采购价格异常：{brief['price_anomaly_count']}项\n"
        f"- 低毛利订单：{brief['low_margin_order_count']}张\n"
        f"- 高风险应收：{brief['high_risk_receivable_count']}笔\n\n"
        "## 管理动作\n\n"
        f"{action_lines}\n"
    )


def _month_sequence(end_date: date, count: int) -> list[str]:
    months = []
    year, month = end_date.year, end_date.month
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return list(reversed(months))


def create_app(database_path: Optional[str | Path] = None) -> FastAPI:
    path = Path(database_path or DEFAULT_DATABASE).resolve()
    repository = SQLiteRepository(path)
    application = FastAPI(
        title="华东某精工装备企业供应链决策智能体API",
        version="6.0.0",
        description="阶段六Dify智能体网关；业务数字来自确定性业务引擎并包含来源和审计字段。",
    )
    application.state.database_path = path
    application.state.repository = repository
    application.state.engine = BusinessEngine(repository)
    application.state.store = OperationalStore(path)
    application.state.ai_audit_store = AIAuditStore(path)
    application.state.action_hub = ActionHub(
        path,
        application.state.ai_audit_store,
        application.state.store,
    )
    application.state.ai_tool_service = AIToolService(
        application.state.engine,
        repository,
        application.state.ai_audit_store,
        ROOT / "knowledge",
    )
    application.state.assistant_service = AssistantService(
        tools=application.state.ai_tool_service,
        audit_store=application.state.ai_audit_store,
        operational_store=application.state.store,
        repository=repository,
        action_hub=application.state.action_hub,
    )
    application.state.ai_tool_token = os.getenv("AI_TOOL_TOKEN", "").strip()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def restrict_cloudflare_tunnel_paths(request: Request, call_next):
        forwarded_host = request.headers.get("x-forwarded-host", "")
        through_tunnel = bool(request.headers.get("cf-ray")) or forwarded_host.endswith(
            ".trycloudflare.com"
        )
        allowed = request.url.path == "/api/v1/health" or request.url.path.startswith(
            "/api/v1/ai-tools/"
        )
        if through_tunnel and not allowed:
            return error_response(
                request,
                403,
                "TUNNEL_PATH_FORBIDDEN",
                "Cloudflare Tunnel仅允许访问健康检查和AI受控工具",
            )
        return await call_next(request)

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(EntityNotFound)
    async def entity_not_found_handler(request: Request, exc: EntityNotFound):
        return error_response(request, 404, exc.code, str(exc))

    @application.exception_handler(InvalidCalculationInput)
    async def invalid_input_handler(request: Request, exc: InvalidCalculationInput):
        return error_response(request, 400, exc.code, str(exc))

    @application.exception_handler(BusinessEngineError)
    async def business_error_handler(request: Request, exc: BusinessEngineError):
        return error_response(request, 400, exc.code, str(exc))

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return error_response(
            request, 422, "REQUEST_VALIDATION_ERROR", "请求参数校验失败", exc.errors()
        )

    @application.exception_handler(sqlite3.Error)
    async def database_error_handler(request: Request, exc: sqlite3.Error):
        return error_response(
            request, 500, "DATABASE_ERROR", "数据库操作失败", str(exc)
        )

    @application.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception):
        return error_response(
            request, 500, "INTERNAL_ERROR", "服务器内部错误", str(exc)
        )

    @application.get("/api/v1/health", tags=["系统"])
    def health(request: Request):
        count = _repo(request).one("SELECT COUNT(*) count FROM companies")
        return success(
            request,
            {
                "status": "healthy",
                "database": "connected",
                "company_count": count["count"],
                "api_version": "6.0.0",
                "assistant_mode": request.app.state.assistant_service.mode,
                "ai_tool_gateway_configured": bool(request.app.state.ai_tool_token),
            },
            "health_check",
            sources=[{"source_table": "companies", "record_code": "count"}],
        )

    @application.get("/api/v1/dashboard", tags=["驾驶舱"])
    def dashboard(request: Request, as_of_date: Optional[date] = None):
        brief = _engine(request).generate_daily_brief(as_of_date)
        result = brief.result
        supplier_top = _repo(request).query(
            """
            SELECT s.supplier_code, s.supplier_name, ss.total_score,
                   ss.supplier_grade AS grade
            FROM supplier_score_snapshots ss
            JOIN suppliers s ON s.supplier_id=ss.supplier_id
            WHERE ss.month=(
                SELECT MAX(month) FROM supplier_score_snapshots
                WHERE month<=?
            )
            ORDER BY ss.total_score DESC LIMIT 5
            """,
            (_date_text(as_of_date)[:7] + "-01",),
        )
        result = {**result, "top_suppliers": supplier_top}
        return success(
            request,
            result,
            "dashboard_summary",
            sources=[
                item.model_dump(mode="json") for item in brief.evidence
            ] + [{"source_table": "supplier_score_snapshots", "record_code": "latest"}],
            warnings=brief.warnings,
            calculation_id=brief.calculation_id,
            formula_version=brief.formula_version,
            as_of_date=brief.as_of_date.isoformat(),
        )

    @application.get("/api/v1/dashboard/trends", tags=["驾驶舱"])
    def dashboard_trends(
        request: Request,
        as_of_date: Optional[date] = None,
        months: int = Query(default=12, ge=3, le=24),
    ):
        resolved = as_of_date or DEFAULT_AS_OF
        month_keys = _month_sequence(resolved, months)
        start = month_keys[0] + "-01"
        order_rows = _repo(request).query(
            """
            SELECT SUBSTR(order_date,1,7) month, ROUND(SUM(order_amount),2) value
            FROM sales_orders WHERE order_date>=? AND order_date<=?
            GROUP BY SUBSTR(order_date,1,7)
            """,
            (start, resolved.isoformat()),
        )
        purchase_rows = _repo(request).query(
            """
            SELECT SUBSTR(order_date,1,7) month, ROUND(SUM(order_amount),2) value
            FROM purchase_orders WHERE order_date>=? AND order_date<=?
            GROUP BY SUBSTR(order_date,1,7)
            """,
            (start, resolved.isoformat()),
        )
        margin_rows = _repo(request).query(
            """
            SELECT SUBSTR(so.order_date,1,7) month,
                   ROUND(SUM(c.gross_profit)/NULLIF(SUM(c.sales_revenue),0),4) value
            FROM order_cost_snapshots c
            JOIN sales_orders so ON so.sales_order_id=c.sales_order_id
            WHERE so.order_date>=? AND so.order_date<=?
            GROUP BY SUBSTR(so.order_date,1,7)
            """,
            (start, resolved.isoformat()),
        )
        receivable_rows = _repo(request).query(
            """
            SELECT SUBSTR(snapshot_date,1,7) month,
                   ROUND(SUM(outstanding_amount),2) value
            FROM ar_snapshots WHERE snapshot_date>=? AND snapshot_date<=?
            GROUP BY SUBSTR(snapshot_date,1,7)
            """,
            (start, resolved.isoformat()),
        )
        def series(rows):
            lookup = {row["month"]: row["value"] or 0 for row in rows}
            return [lookup.get(month, 0) for month in month_keys]
        return success(
            request,
            {
                "months": month_keys,
                "series": {
                    "sales_order_amount": series(order_rows),
                    "purchase_amount": series(purchase_rows),
                    "gross_margin_rate": series(margin_rows),
                    "receivables_amount": series(receivable_rows),
                },
            },
            "dashboard_trends",
            sources=[
                {"source_table": "sales_orders", "record_code": start},
                {"source_table": "purchase_orders", "record_code": start},
                {"source_table": "order_cost_snapshots", "record_code": start},
                {"source_table": "ar_snapshots", "record_code": start},
            ],
            as_of_date=resolved.isoformat(),
        )

    @application.get("/api/v1/orders/risks", tags=["订单"])
    def order_risk_list(
        request: Request,
        as_of_date: Optional[date] = None,
        risk_level: Optional[str] = None,
        scope: str = Query(default="all"),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        if risk_level and risk_level not in {"低", "中", "高"}:
            raise InvalidCalculationInput("risk_level仅支持低、中、高")
        if scope not in {"all", "upcoming_7d"}:
            raise InvalidCalculationInput("scope仅支持all或upcoming_7d")
        resolved = as_of_date or DEFAULT_AS_OF
        if scope == "upcoming_7d":
            candidates = _repo(request).query(
                """
                SELECT sales_order_code
                FROM sales_orders
                WHERE status<>'已完成'
                  AND promised_delivery_date BETWEEN ? AND ?
                ORDER BY promised_delivery_date, sales_order_id
                """,
                (
                    resolved.isoformat(),
                    (resolved + timedelta(days=7)).isoformat(),
                ),
            )
        else:
            candidate_limit = max(limit * 4, 40) if risk_level else limit
            candidates = _repo(request).query(
                """
                SELECT DISTINCT r.entity_code AS sales_order_code
                FROM risk_events r
                WHERE r.entity_type='sales_order'
                ORDER BY CASE WHEN r.entity_code='销售-20260718-01' THEN 0 ELSE 1 END,
                         r.entity_id DESC
                LIMIT ?
                """,
                (candidate_limit,),
            )
        items, sources = [], []
        risks = _engine(request).calculate_order_risks(
            [row["sales_order_code"] for row in candidates],
            as_of_date,
        )
        for risk in risks:
            if risk.result["risk_score"] <= 0:
                continue
            if risk_level and risk.result["risk_level"] != risk_level:
                continue
            items.append(risk.result)
            sources.extend(item.model_dump(mode="json") for item in risk.evidence)
            if len(items) >= limit:
                break
        return success(
            request,
            {
                "count": len(items),
                "items": items,
                "scope": scope,
                "scope_display": "未来7天" if scope == "upcoming_7d" else "全部范围",
            },
            "order_risk_list",
            sources=sources[:200],
            formula_version="3.0.0",
            as_of_date=_date_text(as_of_date),
        )

    @application.get("/api/v1/orders/{order_code}/risk", tags=["订单"])
    def order_risk_detail(
        order_code: str, request: Request, as_of_date: Optional[date] = None
    ):
        return from_calculation(
            request,
            _engine(request).calculate_order_risk(order_code, as_of_date),
            "order_risk_detail",
        )

    @application.get("/api/v1/orders/{order_code}/fulfillment", tags=["订单"])
    def order_fulfillment(
        order_code: str, request: Request, as_of_date: Optional[date] = None
    ):
        return from_calculation(
            request,
            _engine(request).analyze_order_fulfillment(order_code, as_of_date),
            "order_fulfillment",
        )

    @application.get("/api/v1/orders/{order_code}/lifecycle", tags=["订单"])
    def order_lifecycle(
        order_code: str, request: Request, as_of_date: Optional[date] = None
    ):
        repo = _repo(request)
        order = repo.one(
            """
            SELECT so.*, c.customer_code, c.customer_name, p.plant_code, p.plant_name,
                   e.employee_name sales_owner_name
            FROM sales_orders so
            JOIN customers c ON c.customer_id=so.customer_id
            JOIN plants p ON p.plant_id=so.plant_id
            LEFT JOIN employees e ON e.employee_id=so.sales_owner_id
            WHERE so.sales_order_code=?
            """,
            (order_code,),
        )
        if not order:
            raise EntityNotFound(f"销售订单不存在: {order_code}")
        production = repo.query(
            """
            SELECT mo.*, pr.product_code, pr.product_name, sol.order_qty
            FROM production_orders mo
            JOIN sales_order_lines sol ON sol.sales_order_line_id=mo.sales_order_line_id
            JOIN products pr ON pr.product_id=mo.product_id
            WHERE sol.sales_order_id=?
            """,
            (order["sales_order_id"],),
        )
        production_ids = [row["production_order_id"] for row in production]
        requirements = repo.query(
            """
            SELECT r.material_requirement_id, r.production_order_id, r.required_date,
                   r.required_qty, r.issued_qty, r.shortage_qty, r.is_critical, r.status,
                   m.material_code, m.material_name, m.unit,
                   GROUP_CONCAT(DISTINCT po.purchase_order_code) purchase_orders,
                   GROUP_CONCAT(DISTINCT s.supplier_code) suppliers
            FROM production_material_requirements r
            JOIN materials m ON m.material_id=r.material_id
            LEFT JOIN requirement_allocations ra
              ON ra.material_requirement_id=r.material_requirement_id
            LEFT JOIN purchase_order_lines pol
              ON pol.purchase_order_line_id=ra.purchase_order_line_id
            LEFT JOIN purchase_orders po ON po.purchase_order_id=pol.purchase_order_id
            LEFT JOIN suppliers s ON s.supplier_id=po.supplier_id
            WHERE r.production_order_id IN (
                SELECT mo.production_order_id
                FROM production_orders mo
                JOIN sales_order_lines sol
                  ON sol.sales_order_line_id=mo.sales_order_line_id
                WHERE sol.sales_order_id=?
            )
            GROUP BY r.material_requirement_id
            ORDER BY r.is_critical DESC, r.required_date
            """,
            (order["sales_order_id"],),
        )
        purchases = repo.query(
            """
            SELECT DISTINCT po.purchase_order_code, po.order_date,
                   po.promised_delivery_date, po.expected_delivery_date, po.status,
                   po.order_amount, s.supplier_code, s.supplier_name
            FROM requirement_allocations ra
            JOIN production_material_requirements r
              ON r.material_requirement_id=ra.material_requirement_id
            JOIN purchase_order_lines pol
              ON pol.purchase_order_line_id=ra.purchase_order_line_id
            JOIN purchase_orders po ON po.purchase_order_id=pol.purchase_order_id
            JOIN suppliers s ON s.supplier_id=po.supplier_id
            WHERE r.production_order_id IN (
                SELECT mo.production_order_id
                FROM production_orders mo
                JOIN sales_order_lines sol
                  ON sol.sales_order_line_id=mo.sales_order_line_id
                WHERE sol.sales_order_id=?
            )
            ORDER BY po.order_date
            """,
            (order["sales_order_id"],),
        )
        quality = []
        if production_ids:
            placeholders = ",".join("?" for _ in production_ids)
            quality = repo.query(
                f"""
                SELECT inspection_code, inspection_type, inspection_date,
                       inspected_qty, accepted_qty, rejected_qty, result, defect_type
                FROM quality_inspections
                WHERE production_order_id IN ({placeholders})
                ORDER BY inspection_date
                """,
                tuple(production_ids),
            )
        shipments = repo.query(
            "SELECT * FROM shipments WHERE sales_order_id=? ORDER BY shipment_date",
            (order["sales_order_id"],),
        )
        invoices = repo.query(
            "SELECT * FROM invoices WHERE sales_order_id=? ORDER BY invoice_date",
            (order["sales_order_id"],),
        )
        payments = repo.query(
            """
            SELECT DISTINCT p.payment_code, p.payment_date, p.payment_amount,
                   p.payment_method, i.invoice_code
            FROM payment_allocations pa
            JOIN payments p ON p.payment_id=pa.payment_id
            JOIN invoices i ON i.invoice_id=pa.invoice_id
            WHERE i.sales_order_id=?
            ORDER BY p.payment_date
            """,
            (order["sales_order_id"],),
        )
        tasks = repo.query(
            """
            SELECT t.*, r.risk_code, r.rule_code, r.summary
            FROM tasks t JOIN risk_events r ON r.risk_event_id=t.risk_event_id
            WHERE r.entity_type='sales_order' AND r.entity_code=?
            ORDER BY t.due_date
            """,
            (order_code,),
        )
        timeline = [
            {"date": order["order_date"], "type": "订单", "title": "销售订单创建", "code": order_code}
        ]
        timeline.extend(
            {"date": row["planned_start_date"], "type": "生产", "title": "生产计划开始", "code": row["production_order_code"]}
            for row in production
        )
        timeline.extend(
            {"date": row["order_date"], "type": "采购", "title": "采购订单创建", "code": row["purchase_order_code"]}
            for row in purchases
        )
        timeline.extend(
            {"date": row["inspection_date"], "type": "质检", "title": f"质检{row['result']}", "code": row["inspection_code"]}
            for row in quality
        )
        timeline.extend(
            {"date": row["shipment_date"], "type": "发货", "title": "订单发货", "code": row["shipment_code"]}
            for row in shipments
        )
        timeline.extend(
            {"date": row["invoice_date"], "type": "开票", "title": "销售开票", "code": row["invoice_code"]}
            for row in invoices
        )
        timeline.extend(
            {"date": row["payment_date"], "type": "回款", "title": "客户回款", "code": row["payment_code"]}
            for row in payments
        )
        timeline = sorted(
            [item for item in timeline if item["date"]],
            key=lambda item: item["date"],
        )
        return success(
            request,
            {
                "order": order,
                "production": production,
                "requirements": requirements,
                "purchases": purchases,
                "quality": quality,
                "shipments": shipments,
                "invoices": invoices,
                "payments": payments,
                "tasks": tasks,
                "timeline": timeline,
            },
            "order_lifecycle",
            sources=[
                {"source_table": table, "record_code": order_code}
                for table in [
                    "sales_orders", "production_orders",
                    "production_material_requirements", "purchase_orders",
                    "quality_inspections", "shipments", "invoices",
                    "payments", "tasks",
                ]
            ],
            as_of_date=_date_text(as_of_date),
        )

    @application.get("/api/v1/materials/shortages", tags=["物料"])
    def shortages(
        request: Request,
        order_code: Optional[str] = None,
        material_code: Optional[str] = None,
        as_of_date: Optional[date] = None,
    ):
        filters = {
            key: value
            for key, value in {
                "order_code": order_code,
                "material_code": material_code,
            }.items()
            if value
        }
        return from_calculation(
            request,
            _engine(request).analyze_material_shortages(filters, as_of_date),
            "material_shortages",
        )

    @application.get("/api/v1/procurement/price-anomalies", tags=["采购"])
    def price_anomalies(
        request: Request,
        material_code: Optional[str] = None,
        as_of_date: Optional[date] = None,
    ):
        filters = {"material_code": material_code} if material_code else {}
        return from_calculation(
            request,
            _engine(request).detect_purchase_price_anomalies(filters, as_of_date),
            "purchase_price_anomalies",
        )

    @application.get("/api/v1/suppliers/recommendations", tags=["供应商"])
    def supplier_recommendations(
        request: Request,
        material_code: str,
        quantity: float = Query(gt=0),
        need_by_date: date = Query(...),
        as_of_date: Optional[date] = None,
    ):
        return from_calculation(
            request,
            _engine(request).recommend_suppliers(
                material_code, quantity, need_by_date, as_of_date
            ),
            "supplier_recommendation",
        )

    @application.get("/api/v1/suppliers/rankings", tags=["供应商"])
    def supplier_rankings(
        request: Request,
        sort_by: str = "total",
        order: str = "desc",
        limit: int = Query(default=50, ge=1, le=100),
        as_of_date: Optional[date] = None,
    ):
        columns = {
            "total": "ss.total_score",
            "price": "ss.price_score",
            "delivery": "ss.delivery_score",
            "quality": "ss.quality_score",
            "response": "ss.response_score",
            "stability": "ss.stability_score",
        }
        if sort_by not in columns:
            raise InvalidCalculationInput("sort_by值无效")
        if order not in {"asc", "desc"}:
            raise InvalidCalculationInput("order仅支持asc或desc")
        resolved = as_of_date or DEFAULT_AS_OF
        items = _repo(request).query(
            f"""
            SELECT s.supplier_code, s.supplier_name, s.city, s.risk_level,
                   ss.price_score, ss.delivery_score, ss.quality_score,
                   ss.response_score, ss.stability_score, ss.total_score,
                   ss.supplier_grade grade
            FROM supplier_score_snapshots ss
            JOIN suppliers s ON s.supplier_id=ss.supplier_id
            WHERE ss.month=(
                SELECT MAX(month) FROM supplier_score_snapshots WHERE month<=?
            )
            ORDER BY {columns[sort_by]} {order.upper()}, s.supplier_code
            LIMIT ?
            """,
            (resolved.replace(day=1).isoformat(), limit),
        )
        for index, item in enumerate(items, 1):
            item["rank"] = index
        return success(
            request,
            {"count": len(items), "sort_by": sort_by, "items": items},
            "supplier_rankings",
            sources=[{"source_table": "supplier_score_snapshots", "record_code": resolved.isoformat()}],
            as_of_date=resolved.isoformat(),
        )

    @application.get("/api/v1/suppliers/{supplier_code}", tags=["供应商"])
    def supplier_profile(
        supplier_code: str,
        request: Request,
        period: int = Query(default=12, ge=1, le=36),
        as_of_date: Optional[date] = None,
    ):
        supplier = _repo(request).one(
            "SELECT * FROM suppliers WHERE supplier_code=?", (supplier_code,)
        )
        if not supplier:
            raise EntityNotFound(f"供应商不存在: {supplier_code}")
        metrics = _engine(request).calculate_supplier_metrics(
            supplier_code, period, as_of_date
        )
        return success(
            request,
            {"profile": supplier, "metrics": metrics.result},
            "supplier_profile",
            sources=[
                {"source_table": "suppliers", "record_code": supplier_code}
            ] + [item.model_dump(mode="json") for item in metrics.evidence],
            warnings=metrics.warnings,
            calculation_id=metrics.calculation_id,
            formula_version=metrics.formula_version,
            as_of_date=metrics.as_of_date.isoformat(),
        )

    @application.get("/api/v1/orders/{order_code}/cost", tags=["成本报价"])
    def order_cost(
        order_code: str, request: Request, as_of_date: Optional[date] = None
    ):
        return from_calculation(
            request,
            _engine(request).calculate_order_cost(order_code, as_of_date),
            "order_cost",
        )

    @application.get("/api/v1/products", tags=["成本报价"])
    def list_products(request: Request, active_only: bool = True):
        items = _store(request).list_products(active_only)
        return success(
            request,
            {"count": len(items), "items": items},
            "product_list",
            sources=[{"source_table": "products", "record_code": "list"}],
        )

    @application.post("/api/v1/quotes/calculate", tags=["成本报价"])
    def quote(request: Request, payload: QuoteRequest):
        return from_calculation(
            request,
            _engine(request).calculate_quote(
                payload.product_code,
                payload.quantity,
                payload.target_margin,
                payload.options,
                payload.as_of_date,
            ),
            "quote_calculation",
        )

    @application.post("/api/v1/scenarios/run", tags=["情景模拟"])
    def scenario(request: Request, payload: ScenarioRequest):
        return from_calculation(
            request,
            _engine(request).run_procurement_scenario(
                payload.scenario_type, payload.parameters, payload.as_of_date
            ),
            "procurement_scenario",
        )

    @application.get("/api/v1/metrics/query", tags=["经营问数"])
    def metric_query(
        request: Request,
        metric: str,
        as_of_date: Optional[date] = None,
    ):
        resolved = as_of_date or DEFAULT_AS_OF
        result = _metric_query(_repo(request), metric, resolved)
        return success(
            request,
            result,
            "controlled_metric_query",
            sources=[
                {"source_table": table, "record_code": resolved.isoformat()}
                for table in result.pop("sources")
            ],
            as_of_date=resolved.isoformat(),
        )

    @application.post("/api/v1/ai-tools/{tool_name}", tags=["AI受控工具"])
    def invoke_ai_tool(
        tool_name: str,
        request: Request,
        payload: AIToolRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        expected = request.app.state.ai_tool_token
        if not expected:
            raise HTTPException(status_code=503, detail="AI_TOOL_TOKEN尚未配置")
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="AI工具访问令牌无效")
        return request.app.state.ai_tool_service.call(
            tool_name,
            payload.parameters,
            payload.as_of_date,
            payload.trace_id,
        )

    @application.post("/api/v1/assistant/query", tags=["经营问数"])
    def intelligent_ask(request: Request, payload: AskRequest):
        result = request.app.state.assistant_service.query(
            payload.model_dump(mode="json")
        )
        sources = result.get("sources", [])
        warnings = result.get("warnings", [])
        return success(
            request,
            result,
            "intelligent_assistant_query",
            sources=sources,
            warnings=warnings,
            as_of_date=str(payload.as_of_date or DEFAULT_AS_OF),
        )

    @application.post("/api/v1/assistant/query/stream", tags=["经营问数"])
    def intelligent_ask_stream(request: Request, payload: AskRequest):
        def event_stream():
            yield json.dumps(
                {"event": "status", "data": "正在识别业务意图和参数"},
                ensure_ascii=False,
            ) + "\n"
            try:
                result = request.app.state.assistant_service.query(
                    payload.model_dump(mode="json")
                )
            except Exception as exc:
                yield json.dumps(
                    {"event": "error", "data": str(exc)},
                    ensure_ascii=False,
                ) + "\n"
                return
            yield json.dumps(
                {"event": "status", "data": "业务工具调用完成，正在核验数字来源"},
                ensure_ascii=False,
            ) + "\n"
            answer = result.get("answer", "")
            for index in range(0, len(answer), 12):
                yield json.dumps(
                    {"event": "token", "data": answer[index : index + 12]},
                    ensure_ascii=False,
                ) + "\n"
            envelope = success(
                request,
                result,
                "intelligent_assistant_query",
                sources=result.get("sources", []),
                warnings=result.get("warnings", []),
                as_of_date=str(payload.as_of_date or DEFAULT_AS_OF),
            )
            yield json.dumps(
                {"event": "final", "data": envelope},
                ensure_ascii=False,
                default=str,
            ) + "\n"

        return StreamingResponse(
            event_stream(),
            media_type="application/x-ndjson; charset=utf-8",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.post("/api/v1/assistant/confirm", tags=["经营问数"])
    def confirm_assistant_action(
        request: Request, payload: AssistantConfirmationRequest
    ):
        result = request.app.state.assistant_service.confirm(
            payload.confirmation_token,
            payload.actor_open_id,
        )
        return success(
            request,
            result,
            "assistant_action_confirmation",
            sources=result.get("sources", []),
            read_only=False,
        )

    @application.get("/api/v1/receivables", tags=["财务"])
    def receivables(
        request: Request,
        customer_code: Optional[str] = None,
        as_of_date: Optional[date] = None,
    ):
        filters = {"customer_code": customer_code} if customer_code else {}
        return from_calculation(
            request,
            _engine(request).analyze_receivables(filters, as_of_date),
            "receivables_analysis",
        )

    @application.post("/api/v1/reports/generate", tags=["报告"])
    def report(request: Request, payload: ReportRequest):
        brief = _engine(request).generate_business_report(
            payload.report_type, payload.as_of_date
        )
        as_of = brief.as_of_date.isoformat()
        data = {
            "report_type": payload.report_type,
            "report_name": {
                "daily": "经营日报",
                "weekly": "经营周报",
                "monthly": "经营月报",
            }[payload.report_type],
            "as_of_date": as_of,
            "structured_data": brief.result,
        }
        if payload.format == "markdown":
            data["content"] = _render_report(
                payload.report_type, brief.result, as_of
            )
        return success(
            request,
            data,
            "report_generation",
            sources=[item.model_dump(mode="json") for item in brief.evidence],
            warnings=brief.warnings,
            calculation_id=brief.calculation_id,
            formula_version=brief.formula_version,
            as_of_date=as_of,
        )

    @application.post("/api/v1/reports/export", tags=["报告"])
    def report_export(request: Request, payload: ReportExportRequest):
        brief = _engine(request).generate_business_report(
            payload.report_type, payload.as_of_date
        )
        as_of = brief.as_of_date.isoformat()
        report_name = {"daily": "经营日报", "weekly": "经营周报", "monthly": "经营月报"}[payload.report_type]
        title = f"华东某精工装备有限公司{report_name}"
        markdown = _render_report(payload.report_type, brief.result, as_of)
        lines = [line.lstrip("#- ").strip() for line in markdown.splitlines() if line.strip()]
        if lines and lines[0] == title:
            lines = lines[1:]
        exporters = {
            "markdown": (lambda: export_markdown(markdown), "text/markdown; charset=utf-8", "md"),
            "json": (lambda: export_json(brief.result), "application/json", "json"),
            "docx": (lambda: export_docx(title, lines), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
            "pdf": (lambda: export_pdf(title, lines), "application/pdf", "pdf"),
            "xlsx": (lambda: export_xlsx(brief.result), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        }
        build, media_type, extension = exporters[payload.format]
        filename = f"huadong-{payload.report_type}-{as_of}.{extension}"
        return StreamingResponse(
            BytesIO(build()),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Request-ID": getattr(request.state, "request_id", ""),
                "X-Source-Count": str(len(brief.evidence)),
            },
        )

    @application.get("/api/v1/tasks", tags=["任务消息"])
    def list_tasks(
        request: Request,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        items = _store(request).list_tasks(status, priority, limit)
        return success(
            request,
            {"count": len(items), "items": items},
            "task_list",
            sources=[{"source_table": "tasks", "record_code": "list"}],
        )

    @application.post("/api/v1/tasks", status_code=201, tags=["任务消息"])
    def create_task(request: Request, payload: TaskCreateRequest):
        item = _store(request).create_task(payload.model_dump(mode="json"))
        return success(
            request,
            item,
            "task_create",
            sources=[{"source_table": "tasks", "record_code": item["task_code"]}],
            read_only=False,
        )

    @application.get("/api/v1/tasks/{task_code}", tags=["任务消息"])
    def get_task_detail(task_code: str, request: Request):
        item = _store(request).get_task(task_code)
        sources = [
            {"source_table": "tasks", "record_code": task_code},
        ]
        if item.get("risk_code"):
            sources.append(
                {
                    "source_table": "risk_events",
                    "record_code": item["risk_code"],
                }
            )
        sources.extend(
            {
                "source_table": evidence["source_table"],
                "record_code": evidence["source_record_code"],
                "evidence": evidence.get("evidence_value"),
            }
            for evidence in item.get("evidence", [])
        )
        return success(
            request,
            item,
            "task_detail",
            sources=sources,
        )

    @application.patch("/api/v1/tasks/{task_code}", tags=["任务消息"])
    def update_task(
        task_code: str, request: Request, payload: TaskUpdateRequest
    ):
        item = _store(request).update_task(
            task_code, payload.model_dump(mode="json", exclude_none=True)
        )
        return success(
            request,
            item,
            "task_update",
            sources=[{"source_table": "tasks", "record_code": task_code}],
            read_only=False,
        )

    @application.get("/api/v1/messages", tags=["任务消息"])
    def list_messages(
        request: Request,
        task_code: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        items = _store(request).list_messages(task_code, limit)
        return success(
            request,
            {"count": len(items), "items": items},
            "message_list",
            sources=[{"source_table": "messages", "record_code": "list"}],
        )

    @application.post("/api/v1/messages", status_code=201, tags=["任务消息"])
    def create_message(request: Request, payload: MessageCreateRequest):
        item = _store(request).create_message(payload.model_dump(mode="json"))
        return success(
            request,
            item,
            "message_create",
            sources=[
                {"source_table": "messages", "record_code": str(item["message_id"])}
            ],
            read_only=False,
        )

    @application.get("/api/v1/assistant/usage", tags=["智能体审计"])
    def assistant_usage(request: Request):
        return success(request, request.app.state.ai_audit_store.usage_summary(), "assistant_usage")

    @application.get("/api/v1/identities", tags=["身份与通知"])
    def list_identity_bindings(request: Request):
        items = _action_hub(request).list_bindings()
        return success(request, {"count": len(items), "items": items}, "identity_binding_list")

    @application.get("/api/v1/identities/feishu/{open_id}", tags=["身份与通知"])
    def resolve_feishu_identity(open_id: str, request: Request):
        return success(request, _action_hub(request).resolve_identity(open_id), "identity_resolve")

    @application.post("/api/v1/identities", tags=["身份与通知"])
    def bind_feishu_identity(request: Request, payload: IdentityBindingRequest):
        hub = _action_hub(request)
        existing = hub.list_bindings()
        if existing:
            actor = hub.resolve_identity(payload.actor_open_id or "")
            if not actor.get("can_use_agent"):
                raise InvalidCalculationInput("首次绑定后，只有老板或厂长可以维护账号映射")
        item = hub.upsert_binding(payload.model_dump(mode="json"))
        return success(request, item, "identity_binding_upsert", read_only=False)

    @application.post("/api/v1/messages/propose", tags=["身份与通知"])
    def propose_department_message(request: Request, payload: MessageProposalRequest):
        data = payload.model_dump(mode="json")
        conversation_id = data.get("conversation_id")
        if not conversation_id:
            actor = _action_hub(request).resolve_identity(data["actor_open_id"])
            conversation_id = request.app.state.ai_audit_store.ensure_conversation(
                None, data["actor_open_id"], actor.get("assistant_role") or "management",
                "deterministic", "action-bridge", os.getenv("DIFY_WORKFLOW_VERSION", "stage6-v1"),
            )
            data["conversation_id"] = conversation_id
        confirmation = _action_hub(request).propose_message(data)
        return success(request, confirmation, "department_message_proposal", read_only=False)

    @application.get("/api/v1/notifications", tags=["身份与通知"])
    def list_notifications(request: Request, status: Optional[str] = None, limit: int = Query(default=100, ge=1, le=500)):
        items = _action_hub(request).list_notifications(status, limit)
        return success(request, {"count": len(items), "items": items}, "notification_list")

    @application.post("/api/v1/notifications/retry", tags=["身份与通知"])
    def retry_notification(request: Request, payload: NotificationRetryRequest):
        actor = _action_hub(request).resolve_identity(payload.actor_open_id)
        if not actor.get("can_use_agent"):
            raise InvalidCalculationInput("只有老板或厂长可以重试飞书消息")
        item = _action_hub(request).send_notification(payload.notification_id)
        return success(request, item, "notification_retry", read_only=False)

    @application.post("/api/v1/notifications/feishu/callback", tags=["身份与通知"])
    def feishu_notification_callback(
        request: Request,
        payload: FeishuFeedbackRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        expected = request.app.state.ai_tool_token
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if expected and (not supplied or not hmac.compare_digest(supplied, expected)):
            raise HTTPException(status_code=401, detail="回执访问令牌无效")
        item = _action_hub(request).receive_feedback(
            payload.notification_id, payload.actor_open_id,
            payload.action, payload.feedback,
        )
        return success(request, item, "notification_feedback", read_only=False)

    @application.get("/api/v1/operations/audit", tags=["智能体审计"])
    def operation_audit(request: Request, limit: int = Query(default=200, ge=1, le=1000)):
        items = _action_hub(request).list_operations(limit)
        return success(request, {"count": len(items), "items": items}, "operation_audit")

    return application


app = create_app()

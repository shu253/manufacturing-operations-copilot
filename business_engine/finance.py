from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .core import (
    CalculationEnvelope,
    D,
    EntityNotFound,
    Evidence,
    Repository,
    as_money,
    parse_date,
    resolve_as_of,
)
from .fulfillment import (
    _allocation_snapshot,
    analyze_material_shortages,
    calculate_order_risk,
    evaluate_purchase_delays,
)
from .procurement import detect_purchase_price_anomalies


def analyze_receivables(
    repo: Repository, filters: dict[str, Any] | None = None,
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    filters = filters or {}
    customer_code = filters.get("customer_code")
    order_code = filters.get("order_code")
    customer = None
    if customer_code:
        customer = repo.one(
            "SELECT customer_code, customer_name FROM customers "
            "WHERE customer_code=?",
            (customer_code,),
        )
        if not customer:
            raise EntityNotFound(f"客户不存在: {customer_code}")
    if order_code and not repo.one(
        "SELECT 1 FROM sales_orders WHERE sales_order_code=?",
        (order_code,),
    ):
        raise EntityNotFound(f"销售订单不存在: {order_code}")
    rows = repo.query(
        """
        SELECT ar.*, c.customer_code, c.customer_name, i.invoice_code,
               so.sales_order_code
        FROM ar_snapshots ar
        JOIN (
            SELECT invoice_id, MAX(snapshot_date) AS snapshot_date
            FROM ar_snapshots
            WHERE snapshot_date<=?
            GROUP BY invoice_id
        ) latest
          ON latest.invoice_id=ar.invoice_id
         AND latest.snapshot_date=ar.snapshot_date
        JOIN customers c ON c.customer_id=ar.customer_id
        JOIN invoices i ON i.invoice_id=ar.invoice_id
        JOIN sales_orders so ON so.sales_order_id=i.sales_order_id
        """,
        (as_of.isoformat(),),
    )
    items = []
    total_outstanding = Decimal("0")
    total_overdue = Decimal("0")
    partial_payment_count = 0
    partial_payment_outstanding = Decimal("0")
    aging_totals = {
        bucket: {"receivable_count": 0, "outstanding_amount": Decimal("0")}
        for bucket in ("未到期", "1-30天", "31-60天", "61-90天", "90天以上")
    }
    for row in rows:
        if customer_code and row["customer_code"] != customer_code:
            continue
        if order_code and row["sales_order_code"] != order_code:
            continue
        outstanding = D(row["outstanding_amount"])
        paid = D(row["paid_amount"])
        overdue_days = int(row["overdue_days"])
        if outstanding <= 0:
            continue
        score = 0 if overdue_days <= 0 else 30 if overdue_days <= 30 else 60 if overdue_days <= 60 else 80 if overdue_days <= 90 else 100
        level = "低" if score < 30 else "中" if score < 60 else "高"
        total_outstanding += outstanding
        if overdue_days > 0:
            total_overdue += outstanding
        if paid > 0:
            partial_payment_count += 1
            partial_payment_outstanding += outstanding
        aging = aging_totals[row["aging_bucket"]]
        aging["receivable_count"] += 1
        aging["outstanding_amount"] += outstanding
        items.append({
            "customer_code": row["customer_code"],
            "customer_name": row["customer_name"],
            "sales_order_code": row["sales_order_code"],
            "invoice_code": row["invoice_code"],
            "invoice_amount": row["invoice_amount"],
            "paid_amount": row["paid_amount"],
            "outstanding_amount": row["outstanding_amount"],
            "due_date": row["due_date"],
            "overdue_days": overdue_days,
            "aging_bucket": row["aging_bucket"],
            "risk_score": score,
            "risk_level": level,
        })
    shipped_not_invoiced = repo.query(
        """
        SELECT sh.shipment_code, so.sales_order_code, c.customer_code,
               c.customer_name, sh.shipment_date, sh.shipment_amount
        FROM shipments sh
        JOIN sales_orders so ON so.sales_order_id=sh.sales_order_id
        JOIN customers c ON c.customer_id=sh.customer_id
        LEFT JOIN invoices i ON i.shipment_id=sh.shipment_id
        WHERE i.invoice_id IS NULL AND sh.shipment_date<=?
        """,
        (as_of.isoformat(),),
    )
    shipped_not_invoiced = [
        row
        for row in shipped_not_invoiced
        if (not customer_code or row["customer_code"] == customer_code)
        and (not order_code or row["sales_order_code"] == order_code)
    ]
    items.sort(key=lambda x: (-x["risk_score"], -float(x["outstanding_amount"])))
    shipped_not_invoiced.sort(
        key=lambda x: (-float(x["shipment_amount"]), x["shipment_date"])
    )
    shipped_not_invoiced_amount = sum(
        (D(row["shipment_amount"]) for row in shipped_not_invoiced),
        Decimal("0"),
    )
    aging_summary = [
        {
            "aging_bucket": bucket,
            "receivable_count": values["receivable_count"],
            "outstanding_amount": float(as_money(values["outstanding_amount"])),
        }
        for bucket, values in aging_totals.items()
    ]
    query_scope = (
        f"客户{customer_code}（{customer['customer_name']}）"
        if customer_code
        else "全部客户"
    )
    if order_code:
        query_scope += f"、销售订单{order_code}"
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "query_scope_display": query_scope,
            "customer_code": customer_code,
            "customer_name": customer["customer_name"] if customer else None,
            "sales_order_code": order_code,
            "total_outstanding_amount": float(as_money(total_outstanding)),
            "total_overdue_amount": float(as_money(total_overdue)),
            "open_receivable_count": len(items),
            "high_risk_count": sum(1 for x in items if x["risk_level"] == "高"),
            "partial_payment_count": partial_payment_count,
            "partial_payment_outstanding_amount": float(
                as_money(partial_payment_outstanding)
            ),
            "aging_summary": aging_summary,
            "receivables": items,
            "shipped_not_invoiced_count": len(shipped_not_invoiced),
            "shipped_not_invoiced_amount": float(
                as_money(shipped_not_invoiced_amount)
            ),
            "shipped_not_invoiced": shipped_not_invoiced,
        },
        evidence=[
            Evidence(source_table="ar_snapshots", record_code=as_of.isoformat(), description="应收账款账龄快照", value=len(items)),
            Evidence(source_table="shipments", record_code=as_of.isoformat(), description="已发货未开票记录", value=len(shipped_not_invoiced)),
        ],
        warnings=[],
    )


def generate_daily_brief(
    repo: Repository, as_of_date: str | date | None = None
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    upcoming = repo.query(
        """
        SELECT sales_order_code, promised_delivery_date, order_amount, status
        FROM sales_orders
        WHERE status<>'已完成' AND promised_delivery_date BETWEEN ? AND ?
        ORDER BY promised_delivery_date
        """,
        (as_of.isoformat(), (as_of + timedelta(days=7)).isoformat()),
    )
    allocation_cache = _allocation_snapshot(repo, as_of)
    purchase_delay_envelope = evaluate_purchase_delays(repo, {}, as_of)
    purchase_delay_items = purchase_delay_envelope.result["items"]
    risk_items = []
    for order in upcoming:
        risk = calculate_order_risk(
            repo,
            order["sales_order_code"],
            as_of,
            _allocation_cache=allocation_cache,
            _purchase_delay_items=purchase_delay_items,
        ).result
        if risk["risk_score"] > 0:
            risk_items.append({**risk, "promised_delivery_date": order["promised_delivery_date"]})
    risk_items.sort(key=lambda x: (-x["risk_score"], x["promised_delivery_date"]))
    shortages = analyze_material_shortages(repo, {}, as_of).result
    purchase_delays = purchase_delay_envelope.result
    price_anomalies = detect_purchase_price_anomalies(repo, {}, as_of).result
    low_margin = repo.query(
        """
        SELECT so.sales_order_code, c.gross_margin_rate, c.gross_profit, c.sales_revenue
        FROM order_cost_snapshots c
        JOIN sales_orders so ON so.sales_order_id=c.sales_order_id
        WHERE so.status<>'已完成' AND c.gross_margin_rate<0.16
        ORDER BY c.gross_margin_rate ASC LIMIT 50
        """
    )
    receivables = analyze_receivables(repo, {}, as_of).result
    actions = []
    if risk_items:
        actions.append({"action": f"立即处理{risk_items[0]['sales_order_code']}交付风险", "owner": "计划/采购/生产"})
    if shortages["count"]:
        actions.append({"action": f"确认{shortages['count']}项缺料的补齐计划", "owner": "采购部"})
    if purchase_delays["count"]:
        actions.append({"action": f"跟进{purchase_delays['count']}项采购迟交", "owner": "采购部"})
    if low_margin:
        actions.append({"action": f"复核{len(low_margin)}张低毛利订单", "owner": "销售/财务"})
    if receivables["high_risk_count"]:
        actions.append({"action": f"催收{receivables['high_risk_count']}笔高风险应收", "owner": "财务/销售"})
    actions = actions[:5]
    for priority, action in enumerate(actions, start=1):
        action["priority"] = priority
    potential = sum(D(r["potential_amount"]) for r in risk_items)
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "brief_date": as_of.isoformat(),
            "upcoming_7d_order_count": len(upcoming),
            "risk_order_count": len(risk_items),
            "high_risk_order_count": sum(1 for r in risk_items if r["risk_level"] == "高"),
            "risk_order_amount": float(as_money(potential)),
            "shortage_count": shortages["count"],
            "purchase_delay_count": purchase_delays["count"],
            "price_anomaly_count": price_anomalies["count"],
            "low_margin_order_count": len(low_margin),
            "high_risk_receivable_count": receivables["high_risk_count"],
            "high_risk_orders": [
                item for item in risk_items if item["risk_level"] == "高"
            ][:20],
            "top_actions": actions,
        },
        evidence=[
            Evidence(source_table="sales_orders", record_code=as_of.isoformat(), description="未来7天订单", value=len(upcoming)),
            Evidence(source_table="production_material_requirements", record_code=as_of.isoformat(), description="缺料汇总", value=shortages["count"]),
            Evidence(source_table="ar_snapshots", record_code=as_of.isoformat(), description="应收风险", value=receivables["high_risk_count"]),
        ],
        warnings=[],
    )


def generate_business_report(
    repo: Repository,
    report_type: str = "daily",
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    """Generate a real day, week-to-date, or month-to-date report."""
    if report_type not in {"daily", "weekly", "monthly"}:
        raise InvalidCalculationInput("report_type仅支持daily、weekly或monthly")
    as_of = resolve_as_of(as_of_date)
    if report_type == "weekly":
        period_start = as_of - timedelta(days=as_of.weekday())
    elif report_type == "monthly":
        period_start = as_of.replace(day=1)
    else:
        period_start = as_of

    snapshot = generate_daily_brief(repo, as_of)
    start_text, end_text = period_start.isoformat(), as_of.isoformat()

    def aggregate(sql: str) -> dict[str, Any]:
        return repo.one(sql, (start_text, end_text)) or {}

    sales = aggregate(
        "SELECT COUNT(*) order_count, ROUND(COALESCE(SUM(order_amount),0),2) order_amount "
        "FROM sales_orders WHERE order_date BETWEEN ? AND ?"
    )
    procurement = aggregate(
        "SELECT COUNT(*) purchase_order_count, ROUND(COALESCE(SUM(order_amount),0),2) purchase_amount "
        "FROM purchase_orders WHERE order_date BETWEEN ? AND ?"
    )
    production = aggregate(
        "SELECT COUNT(*) completed_order_count, ROUND(COALESCE(SUM(completed_qty),0),4) completed_quantity "
        "FROM production_orders WHERE actual_finish_date BETWEEN ? AND ? AND status='已完成'"
    )
    shipments = aggregate(
        "SELECT COUNT(*) shipment_count, ROUND(COALESCE(SUM(shipment_amount),0),2) shipment_amount "
        "FROM shipments WHERE shipment_date BETWEEN ? AND ?"
    )
    payments = aggregate(
        "SELECT COUNT(*) payment_count, ROUND(COALESCE(SUM(payment_amount),0),2) payment_amount "
        "FROM payments WHERE payment_date BETWEEN ? AND ?"
    )
    result = dict(snapshot.result)
    result.update({
        "report_type": report_type,
        "period_start": start_text,
        "period_end": end_text,
        "period_days": (as_of - period_start).days + 1,
        "period_metrics": {
            "sales": sales,
            "procurement": procurement,
            "production": production,
            "shipments": shipments,
            "payments": payments,
        },
    })
    period_code = f"{start_text}/{end_text}"
    evidence = list(snapshot.evidence) + [
        Evidence(source_table="sales_orders", record_code=period_code, description="期间新增销售订单", value=sales.get("order_count", 0)),
        Evidence(source_table="purchase_orders", record_code=period_code, description="期间采购订单", value=procurement.get("purchase_order_count", 0)),
        Evidence(source_table="production_orders", record_code=period_code, description="期间完工生产订单", value=production.get("completed_order_count", 0)),
        Evidence(source_table="shipments", record_code=period_code, description="期间发货", value=shipments.get("shipment_count", 0)),
        Evidence(source_table="payments", record_code=period_code, description="期间回款", value=payments.get("payment_count", 0)),
    ]
    return CalculationEnvelope(
        as_of_date=as_of,
        result=result,
        evidence=evidence,
        warnings=snapshot.warnings,
    )

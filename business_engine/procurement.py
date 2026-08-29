from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .core import (
    CalculationEnvelope,
    D,
    EntityNotFound,
    Evidence,
    InvalidCalculationInput,
    Repository,
    clamp,
    parse_date,
    resolve_as_of,
)


def _material(repo: Repository, material_code: str) -> dict[str, Any]:
    row = repo.one("SELECT * FROM materials WHERE material_code=?", (material_code,))
    if not row:
        raise EntityNotFound(f"物料不存在: {material_code}")
    return row


def _supplier(repo: Repository, supplier_code: str) -> dict[str, Any]:
    row = repo.one("SELECT * FROM suppliers WHERE supplier_code=?", (supplier_code,))
    if not row:
        raise EntityNotFound(f"供应商不存在: {supplier_code}")
    return row


def detect_purchase_price_anomalies(
    repo: Repository, filters: dict[str, Any] | None = None,
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    filters = filters or {}
    materials = repo.query("SELECT material_id, material_code, material_name FROM materials")
    if filters.get("material_code"):
        materials = [m for m in materials if m["material_code"] == filters["material_code"]]
        if not materials:
            raise EntityNotFound(f"物料不存在: {filters['material_code']}")
    items, evidence = [], []
    for material in materials:
        history = repo.query(
            """
            SELECT * FROM material_price_history
            WHERE material_id=? AND month<=?
            ORDER BY month DESC
            LIMIT 13
            """,
            (material["material_id"], as_of.replace(day=1).isoformat()),
        )
        if not history:
            continue
        latest = history[0]
        previous = history[1] if len(history) > 1 else None
        last_year = history[12] if len(history) > 12 else None
        latest_price = D(latest["average_purchase_price"])
        mom = (latest_price / D(previous["average_purchase_price"]) - 1) if previous and D(previous["average_purchase_price"]) else Decimal("0")
        yoy = (latest_price / D(last_year["average_purchase_price"]) - 1) if last_year and D(last_year["average_purchase_price"]) else Decimal("0")
        market = D(latest["market_reference_price"])
        market_dev = (latest_price / market - 1) if market else Decimal("0")
        supplier_prices = [
            D(r["unit_price"]) for r in repo.query(
                """
                SELECT pol.unit_price
                FROM purchase_order_lines pol
                JOIN purchase_orders po ON po.purchase_order_id=pol.purchase_order_id
                WHERE pol.material_id=? AND po.order_date>=? AND po.order_date<=?
                """,
                (material["material_id"], (as_of - timedelta(days=180)).isoformat(), as_of.isoformat()),
            )
        ]
        median_price = Decimal(str(statistics.median([float(x) for x in supplier_prices]))) if supplier_prices else latest_price
        supplier_dev = (latest_price / median_price - 1) if median_price else Decimal("0")
        triggers = []
        if abs(mom) >= Decimal("0.05"):
            triggers.append("环比异常")
        if abs(yoy) >= Decimal("0.10"):
            triggers.append("同比异常")
        if abs(market_dev) >= Decimal("0.08"):
            triggers.append("市场价偏差")
        if abs(supplier_dev) >= Decimal("0.08"):
            triggers.append("供应商价差")
        if not triggers:
            continue
        severity = "高" if max(abs(mom), abs(yoy), abs(market_dev), abs(supplier_dev)) >= Decimal("0.15") else "中"
        related = repo.query(
            """
            SELECT po.purchase_order_code, s.supplier_code, pol.unit_price
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON po.purchase_order_id=pol.purchase_order_id
            JOIN suppliers s ON s.supplier_id=po.supplier_id
            WHERE pol.material_id=? AND po.order_date>=?
            ORDER BY po.order_date DESC LIMIT 10
            """,
            (material["material_id"], (as_of - timedelta(days=180)).isoformat()),
        )
        items.append({
            "material_code": material["material_code"],
            "material_name": material["material_name"],
            "latest_price": float(latest_price),
            "month_over_month_rate": float(mom.quantize(Decimal("0.0001"))),
            "year_over_year_rate": float(yoy.quantize(Decimal("0.0001"))),
            "market_deviation_rate": float(market_dev.quantize(Decimal("0.0001"))),
            "supplier_deviation_rate": float(supplier_dev.quantize(Decimal("0.0001"))),
            "triggers": triggers,
            "severity": severity,
            "related_purchase_orders": related,
        })
        evidence.append(Evidence(
            source_table="material_price_history",
            record_code=str(latest["price_history_id"]),
            description=f"{material['material_code']}：{'、'.join(triggers)}",
            value=float(latest_price),
        ))
    items.sort(key=lambda x: (x["severity"] != "高", -abs(x["month_over_month_rate"])))
    return CalculationEnvelope(
        as_of_date=as_of,
        result={"count": len(items), "items": items},
        evidence=evidence,
        warnings=[],
    )


def calculate_supplier_metrics(
    repo: Repository, supplier_code: str, period: int = 12,
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    if period <= 0:
        raise InvalidCalculationInput("统计周期必须大于0个月")
    supplier = _supplier(repo, supplier_code)
    start = as_of - timedelta(days=period * 31)
    po_rows = repo.query(
        """
        SELECT po.purchase_order_id, po.purchase_order_code, po.promised_delivery_date,
               r.receipt_date, pol.material_id, pol.unit_price, pol.line_amount
        FROM purchase_orders po
        JOIN purchase_order_lines pol ON pol.purchase_order_id=po.purchase_order_id
        LEFT JOIN receipts r ON r.purchase_order_id=po.purchase_order_id
        WHERE po.supplier_id=? AND po.order_date BETWEEN ? AND ?
        """,
        (supplier["supplier_id"], start.isoformat(), as_of.isoformat()),
    )
    due_rows = [r for r in po_rows if parse_date(r["promised_delivery_date"]) and parse_date(r["promised_delivery_date"]) <= as_of]
    on_time = [
        r for r in due_rows
        if r["receipt_date"] and parse_date(r["receipt_date"]) <= parse_date(r["promised_delivery_date"])
    ]
    delivery_rate = Decimal(len(on_time)) / Decimal(len(due_rows)) if due_rows else Decimal("0")
    quality = repo.one(
        """
        SELECT SUM(inspected_qty) AS inspected, SUM(accepted_qty) AS accepted
        FROM quality_inspections
        WHERE supplier_id=? AND inspection_date BETWEEN ? AND ?
        """,
        (supplier["supplier_id"], start.isoformat(), as_of.isoformat()),
    ) or {}
    inspected, accepted = D(quality.get("inspected")), D(quality.get("accepted"))
    quality_rate = accepted / inspected if inspected else Decimal("0")

    all_prices: dict[int, list[float]] = {}
    for row in repo.query(
        """
        SELECT pol.material_id, pol.unit_price
        FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.purchase_order_id=pol.purchase_order_id
        WHERE po.order_date BETWEEN ? AND ?
        """,
        (start.isoformat(), as_of.isoformat()),
    ):
        all_prices.setdefault(row["material_id"], []).append(float(row["unit_price"]))
    ratios = []
    for row in po_rows:
        prices = all_prices.get(row["material_id"], [])
        if prices:
            ratios.append(D(row["unit_price"]) / Decimal(str(statistics.median(prices))))
    avg_ratio = sum(ratios, Decimal("0")) / Decimal(len(ratios)) if ratios else Decimal("1")
    price_score = clamp(Decimal("100") - max(Decimal("0"), avg_ratio - Decimal("0.90")) * 200, Decimal("40"), Decimal("100"))
    delivery_score = delivery_rate * 100
    quality_score = quality_rate * 100
    snapshot = repo.one(
        """
        SELECT response_score, stability_score
        FROM supplier_score_snapshots
        WHERE supplier_id=? AND month<=?
        ORDER BY month DESC LIMIT 1
        """,
        (supplier["supplier_id"], as_of.replace(day=1).isoformat()),
    ) or {"response_score": 70, "stability_score": 70}
    response_score = D(snapshot["response_score"])
    stability_score = D(snapshot["stability_score"])
    total = (
        price_score * Decimal("0.25")
        + delivery_score * Decimal("0.30")
        + quality_score * Decimal("0.25")
        + response_score * Decimal("0.10")
        + stability_score * Decimal("0.10")
    )
    grade = "A" if total >= 90 else "B" if total >= 80 else "C" if total >= 70 else "D"
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "supplier_code": supplier_code,
            "supplier_name": supplier["supplier_name"],
            "period_months": period,
            "purchase_order_count": len(po_rows),
            "price_ratio_to_market_median": float(avg_ratio.quantize(Decimal("0.0001"))),
            "on_time_delivery_rate": float(delivery_rate.quantize(Decimal("0.0001"))),
            "quality_acceptance_rate": float(quality_rate.quantize(Decimal("0.0001"))),
            "scores": {
                "price": float(price_score.quantize(Decimal("0.01"))),
                "delivery": float(delivery_score.quantize(Decimal("0.01"))),
                "quality": float(quality_score.quantize(Decimal("0.01"))),
                "response": float(response_score.quantize(Decimal("0.01"))),
                "stability": float(stability_score.quantize(Decimal("0.01"))),
                "total": float(total.quantize(Decimal("0.01"))),
                "grade": grade,
            },
        },
        evidence=[
            Evidence(source_table="purchase_orders", record_code=supplier_code, description="采购交付统计", value=len(po_rows)),
            Evidence(source_table="quality_inspections", record_code=supplier_code, description="质量检验统计", value=float(inspected)),
            Evidence(source_table="supplier_score_snapshots", record_code=supplier_code, description="响应与稳定性快照"),
        ],
        warnings=[] if po_rows else ["统计周期内没有采购订单，部分指标使用默认值"],
    )


def recommend_suppliers(
    repo: Repository, material_code: str, quantity: float,
    need_by_date: str | date, as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    if D(quantity) <= 0:
        raise InvalidCalculationInput("采购数量必须大于0")
    material = _material(repo, material_code)
    need_by = parse_date(need_by_date)
    if not need_by:
        raise InvalidCalculationInput("需求日期不能为空")
    candidates = repo.query(
        """
        SELECT sm.*, s.supplier_code, s.supplier_name, s.risk_level
        FROM supplier_materials sm
        JOIN suppliers s ON s.supplier_id=sm.supplier_id
        WHERE sm.material_id=? AND sm.is_approved=1
        """,
        (material["material_id"],),
    )
    output, evidence = [], []
    for row in candidates:
        metrics = calculate_supplier_metrics(repo, row["supplier_code"], 12, as_of).result
        total = D(metrics["scores"]["total"])
        arrival = as_of + timedelta(days=int(row["lead_time_days"]))
        on_time = arrival <= need_by
        lead_score = Decimal("100") if on_time else max(Decimal("0"), Decimal("100") - Decimal((arrival - need_by).days * 10))
        qty_fit = Decimal("100") if D(quantity) >= D(row["minimum_order_qty"]) else Decimal("60")
        recommendation_score = total * Decimal("0.75") + lead_score * Decimal("0.15") + qty_fit * Decimal("0.10")
        advantages, risks = [], []
        if metrics["scores"]["price"] >= 80:
            advantages.append("价格竞争力较好")
        if metrics["on_time_delivery_rate"] >= 0.85:
            advantages.append("交付稳定")
        if metrics["quality_acceptance_rate"] >= 0.95:
            advantages.append("质量表现较好")
        if not on_time:
            risks.append(f"预计晚于需求日期{(arrival - need_by).days}天")
        if row["risk_level"] == "高":
            risks.append("供应商基础风险较高")
        output.append({
            "supplier_code": row["supplier_code"],
            "supplier_name": row["supplier_name"],
            "quoted_price": row["quoted_price"],
            "lead_time_days": row["lead_time_days"],
            "expected_arrival_date": arrival.isoformat(),
            "minimum_order_qty": row["minimum_order_qty"],
            "supplier_total_score": metrics["scores"]["total"],
            "recommendation_score": float(recommendation_score.quantize(Decimal("0.01"))),
            "advantages": advantages,
            "risks": risks,
            "negotiation_advice": "以历史中位价和备选供应商报价作为议价依据",
        })
        evidence.append(Evidence(
            source_table="supplier_materials",
            record_code=row["supplier_material_code"],
            description=f"{row['supplier_code']}供货能力",
            value=row["quoted_price"],
        ))
    output.sort(key=lambda x: (-x["recommendation_score"], float(x["quoted_price"])))
    for index, row in enumerate(output, 1):
        row["rank"] = index
    return CalculationEnvelope(
        as_of_date=as_of,
        result={"material_code": material_code, "quantity": quantity, "count": len(output), "items": output},
        evidence=evidence,
        warnings=[] if output else ["没有已准入的供应商"],
    )


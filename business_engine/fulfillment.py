from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from .core import (
    CalculationEnvelope,
    D,
    EntityNotFound,
    Evidence,
    Repository,
    as_money,
    as_qty,
    clamp,
    parse_date,
    resolve_as_of,
)

DISCRETE_UNITS = {"件", "个", "套", "台"}
RISK_RULE_NAMES = {
    "MATERIAL_SHORTAGE": "关键物料短缺",
    "PURCHASE_LATE": "采购预计迟交",
    "PRODUCTION_DELAY": "生产进度落后",
    "QUALITY_REWORK": "质量返工",
    "DUE_SOON": "临近交期",
}


def _display_quantity(value: Any, unit: str) -> str:
    quantity = D(value)
    if unit in DISCRETE_UNITS and quantity == quantity.to_integral_value():
        number = f"{int(quantity):,}"
    else:
        number = f"{quantity:,.4f}".rstrip("0").rstrip(".")
    if not unit:
        return number
    separator = "" if unit in DISCRETE_UNITS else " "
    return f"{number}{separator}{unit}"


def _latest_operational_snapshot_date(repo: Repository) -> date | None:
    """Return the common demo-data cutoff used by snapshot-dependent metrics."""
    row = repo.one(
        "SELECT MAX(snapshot_date) AS snapshot_date FROM inventory_balances"
    )
    return parse_date(row["snapshot_date"]) if row and row["snapshot_date"] else None


def _order(repo: Repository, order_code: str) -> dict[str, Any]:
    row = repo.one(
        """
        SELECT so.*, sol.sales_order_line_id, sol.product_id, sol.order_qty,
               p.product_code, p.product_name,
               mo.production_order_id, mo.production_order_code,
               mo.planned_start_date, mo.planned_finish_date,
               mo.progress_rate, mo.status AS production_status
        FROM sales_orders so
        JOIN sales_order_lines sol ON sol.sales_order_id=so.sales_order_id
        JOIN products p ON p.product_id=sol.product_id
        JOIN production_orders mo ON mo.sales_order_line_id=sol.sales_order_line_id
        WHERE so.sales_order_code=?
        """,
        (order_code,),
    )
    if not row:
        raise EntityNotFound(f"销售订单不存在: {order_code}")
    return row


def _allocation_snapshot(repo: Repository, as_of: date) -> dict[int, dict[str, Any]]:
    requirements = repo.query(
        """
        SELECT r.*, mo.plant_id, so.promised_delivery_date, so.status AS order_status
        FROM production_material_requirements r
        JOIN production_orders mo ON mo.production_order_id=r.production_order_id
        JOIN sales_order_lines sol ON sol.sales_order_line_id=mo.sales_order_line_id
        JOIN sales_orders so ON so.sales_order_id=sol.sales_order_id
        WHERE so.status <> '已完成'
        ORDER BY r.required_date, so.promised_delivery_date, r.is_critical DESC,
                 r.material_requirement_id
        """
    )
    inventory = {
        (r["plant_id"], r["material_id"]): D(r["available_qty"])
        for r in repo.query(
            """
            SELECT plant_id, material_id, SUM(available_qty) AS available_qty
            FROM inventory_balances
            WHERE snapshot_date<=?
            GROUP BY plant_id, material_id
            """,
            (as_of.isoformat(),),
        )
    }
    inbound: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in repo.query(
        """
        SELECT ra.material_requirement_id, ra.allocated_qty,
               po.purchase_order_code, po.expected_delivery_date,
               po.promised_delivery_date, po.status
        FROM requirement_allocations ra
        JOIN purchase_order_lines pol ON pol.purchase_order_line_id=ra.purchase_order_line_id
        JOIN purchase_orders po ON po.purchase_order_id=pol.purchase_order_id
        """
    ):
        inbound[row["material_requirement_id"]].append(row)

    result: dict[int, dict[str, Any]] = {}
    for req in requirements:
        required = D(req["required_qty"])
        issued = min(required, D(req["issued_qty"]))
        remaining = max(Decimal("0"), required - issued)
        key = (req["plant_id"], req["material_id"])
        stock_used = min(inventory.get(key, Decimal("0")), remaining)
        inventory[key] = max(Decimal("0"), inventory.get(key, Decimal("0")) - stock_used)
        still_needed = remaining - stock_used
        required_date = parse_date(req["required_date"])
        on_time_inbound = Decimal("0")
        late_inbound = Decimal("0")
        linked_pos: list[dict[str, Any]] = []
        for po in inbound.get(req["material_requirement_id"], []):
            expected = parse_date(po["expected_delivery_date"])
            allocated = D(po["allocated_qty"])
            if expected and required_date and expected <= required_date:
                used = min(allocated, still_needed - on_time_inbound)
                on_time_inbound += max(Decimal("0"), used)
            else:
                late_inbound += allocated
            linked_pos.append(po)
        shortage = max(Decimal("0"), still_needed - on_time_inbound)
        fulfilled = required - shortage
        result[req["material_requirement_id"]] = {
            **req,
            "required_qty": as_qty(required),
            "issued_qty": as_qty(issued),
            "stock_allocated_qty": as_qty(stock_used),
            "on_time_inbound_qty": as_qty(on_time_inbound),
            "late_inbound_qty": as_qty(late_inbound),
            "shortage_qty": as_qty(shortage),
            "fulfilled_qty": as_qty(fulfilled),
            "is_fully_kitted": shortage <= 0,
            "linked_purchase_orders": linked_pos,
        }
    return result


def analyze_order_fulfillment(
    repo: Repository, order_code: str, as_of_date: str | date | None = None,
    *, _allocation_cache: dict[int, dict[str, Any]] | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    order = _order(repo, order_code)
    allocations = _allocation_cache if _allocation_cache is not None else _allocation_snapshot(repo, as_of)
    rows = [
        row for row in allocations.values()
        if row["production_order_id"] == order["production_order_id"]
    ]
    material_by_id = {
        r["material_id"]: r
        for r in repo.query("SELECT material_id, material_code, material_name, unit FROM materials")
    }
    total_required = sum((D(r["required_qty"]) for r in rows), Decimal("0"))
    total_fulfilled = sum((D(r["fulfilled_qty"]) for r in rows), Decimal("0"))
    full_lines = sum(1 for r in rows if r["is_fully_kitted"])
    line_rate = Decimal(full_lines) / Decimal(len(rows)) if rows else Decimal("0")
    qty_rate = total_fulfilled / total_required if total_required else Decimal("0")
    details, evidence = [], []
    for row in rows:
        material = material_by_id[row["material_id"]]
        details.append({
            "material_code": material["material_code"],
            "material_name": material["material_name"],
            "unit": material["unit"],
            "required_date": row["required_date"],
            "required_qty": row["required_qty"],
            "issued_qty": row["issued_qty"],
            "stock_allocated_qty": row["stock_allocated_qty"],
            "on_time_inbound_qty": row["on_time_inbound_qty"],
            "late_inbound_qty": row["late_inbound_qty"],
            "shortage_qty": row["shortage_qty"],
            "is_critical": bool(row["is_critical"]),
            "is_fully_kitted": row["is_fully_kitted"],
            "purchase_orders": [p["purchase_order_code"] for p in row["linked_purchase_orders"]],
        })
        if D(row["shortage_qty"]) > 0:
            evidence.append(Evidence(
                source_table="production_material_requirements",
                record_code=str(row["material_requirement_id"]),
                description=f"{material['material_code']}存在短缺",
                value=str(row["shortage_qty"]),
            ))
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "sales_order_code": order_code,
            "production_order_code": order["production_order_code"],
            "line_kitting_rate": float(line_rate.quantize(Decimal("0.0001"))),
            "quantity_kitting_rate": float(qty_rate.quantize(Decimal("0.0001"))),
            "fully_kitted_lines": full_lines,
            "total_material_lines": len(rows),
            "shortage_line_count": len(rows) - full_lines,
            "materials": details,
        },
        evidence=evidence,
        warnings=[] if rows else ["订单没有生产物料需求数据"],
    )


def analyze_material_shortages(
    repo: Repository, filters: dict[str, Any] | None = None,
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    filters = filters or {}
    if filters.get("order_code"):
        _order(repo, filters["order_code"])
    if filters.get("material_code") and not repo.one(
        "SELECT 1 FROM materials WHERE material_code=?", (filters["material_code"],)
    ):
        raise EntityNotFound(f"物料不存在: {filters['material_code']}")
    allocations = _allocation_snapshot(repo, as_of)
    order_map = {
        r["production_order_id"]: r
        for r in repo.query(
            """
            SELECT mo.production_order_id, so.sales_order_code, so.promised_delivery_date,
                   mo.production_order_code
            FROM production_orders mo
            JOIN sales_order_lines sol ON sol.sales_order_line_id=mo.sales_order_line_id
            JOIN sales_orders so ON so.sales_order_id=sol.sales_order_id
            """
        )
    }
    material_map = {
        r["material_id"]: r
        for r in repo.query("SELECT material_id, material_code, material_name, unit FROM materials")
    }
    output, evidence = [], []
    for row in allocations.values():
        if D(row["shortage_qty"]) <= 0:
            continue
        material = material_map[row["material_id"]]
        order = order_map[row["production_order_id"]]
        if filters.get("order_code") and order["sales_order_code"] != filters["order_code"]:
            continue
        if filters.get("material_code") and material["material_code"] != filters["material_code"]:
            continue
        late_dates = [
            parse_date(p["expected_delivery_date"]) for p in row["linked_purchase_orders"]
            if p.get("expected_delivery_date")
        ]
        expected_recovery = max(late_dates).isoformat() if late_dates else None
        po_codes = [p["purchase_order_code"] for p in row["linked_purchase_orders"]]
        item = {
            "sales_order_code": order["sales_order_code"],
            "production_order_code": order["production_order_code"],
            "material_code": material["material_code"],
            "material_name": material["material_name"],
            "unit": material["unit"],
            "required_date": row["required_date"],
            "shortage_qty": row["shortage_qty"],
            "shortage_qty_display": _display_quantity(
                row["shortage_qty"], material["unit"]
            ),
            "expected_recovery_date": expected_recovery,
            "purchase_orders": po_codes,
            "is_critical": bool(row["is_critical"]),
        }
        output.append(item)
        evidence.append(Evidence(
            source_table="production_material_requirements",
            record_code=str(row["material_requirement_id"]),
            description=f"{order['sales_order_code']}缺少{material['material_code']}",
            value=str(row["shortage_qty"]),
        ))
    output.sort(
        key=lambda x: (
            not x["is_critical"],
            x["required_date"],
            x["material_code"],
            x["sales_order_code"],
        )
    )
    critical_items = [item for item in output if item["is_critical"]]
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "count": len(output),
            "shortage_record_count": len(output),
            "critical_shortage_count": len(critical_items),
            "critical_shortage_record_count": len(critical_items),
            "critical_material_count": len(
                {item["material_code"] for item in critical_items}
            ),
            "affected_order_count": len(
                {item["sales_order_code"] for item in output}
            ),
            "items": output,
        },
        evidence=evidence[:100],
        warnings=[],
    )


def evaluate_purchase_delays(
    repo: Repository, filters: dict[str, Any] | None = None,
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    filters = filters or {}
    if filters.get("order_code"):
        _order(repo, filters["order_code"])
    if filters.get("material_code") and not repo.one(
        "SELECT 1 FROM materials WHERE material_code=?",
        (filters["material_code"],),
    ):
        raise EntityNotFound(f"物料不存在: {filters['material_code']}")
    if filters.get("supplier_code") and not repo.one(
        "SELECT 1 FROM suppliers WHERE supplier_code=?",
        (filters["supplier_code"],),
    ):
        raise EntityNotFound(f"供应商不存在: {filters['supplier_code']}")
    if filters.get("purchase_order_code") and not repo.one(
        "SELECT 1 FROM purchase_orders WHERE purchase_order_code=?",
        (filters["purchase_order_code"],),
    ):
        raise EntityNotFound(f"采购订单不存在: {filters['purchase_order_code']}")
    rows = repo.query(
        """
        SELECT so.sales_order_code, so.promised_delivery_date,
               r.material_requirement_id, r.required_date,
               m.material_code, m.material_name, m.unit,
               po.purchase_order_code, po.expected_delivery_date,
               po.promised_delivery_date AS po_promised_date,
               po.status, s.supplier_code, s.supplier_name,
               ra.allocated_qty
        FROM requirement_allocations ra
        JOIN production_material_requirements r
          ON r.material_requirement_id=ra.material_requirement_id
        JOIN materials m ON m.material_id=r.material_id
        JOIN production_orders mo ON mo.production_order_id=r.production_order_id
        JOIN sales_order_lines sol ON sol.sales_order_line_id=mo.sales_order_line_id
        JOIN sales_orders so ON so.sales_order_id=sol.sales_order_id
        JOIN purchase_order_lines pol ON pol.purchase_order_line_id=ra.purchase_order_line_id
        JOIN purchase_orders po ON po.purchase_order_id=pol.purchase_order_id
        JOIN suppliers s ON s.supplier_id=po.supplier_id
        WHERE so.status <> '已完成'
        """
    )
    output, evidence = [], []
    for row in rows:
        if filters.get("order_code") and row["sales_order_code"] != filters["order_code"]:
            continue
        if filters.get("material_code") and row["material_code"] != filters["material_code"]:
            continue
        if filters.get("supplier_code") and row["supplier_code"] != filters["supplier_code"]:
            continue
        if filters.get("purchase_order_code") and row["purchase_order_code"] != filters["purchase_order_code"]:
            continue
        expected = parse_date(row["expected_delivery_date"])
        required = parse_date(row["required_date"])
        order_due = parse_date(row["promised_delivery_date"])
        if not expected:
            continue
        late_req = max(0, (expected - required).days) if required else 0
        late_order = max(0, (expected - order_due).days) if order_due else 0
        if late_req <= 0 and late_order <= 0:
            continue
        item = {
            **row,
            "late_vs_requirement_days": late_req,
            "late_vs_order_days": late_order,
            "impact_delay_days": late_order,
            "severity": "高" if late_order >= 5 or late_req >= 10 else "中",
            "allocated_qty_display": _display_quantity(
                row["allocated_qty"], row["unit"]
            ),
        }
        output.append(item)
        evidence.append(Evidence(
            source_table="purchase_orders",
            record_code=row["purchase_order_code"],
            description=(
                f"预计到货晚于订单交期{late_order}天"
                if late_order > 0
                else f"预计到货晚于物料需求日{late_req}天"
            ),
            value=row["expected_delivery_date"],
        ))
    output.sort(key=lambda x: (-x["impact_delay_days"], -x["late_vs_requirement_days"]))
    high_severity_items = [item for item in output if item["severity"] == "高"]
    delayed_beyond_order = [
        item for item in output if item["late_vs_order_days"] > 0
    ]
    delayed_beyond_requirement = [
        item for item in output if item["late_vs_requirement_days"] > 0
    ]
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "count": len(output),
            "delay_record_count": len(output),
            "affected_order_count": len(
                {item["sales_order_code"] for item in output}
            ),
            "affected_material_count": len(
                {item["material_code"] for item in output}
            ),
            "affected_supplier_count": len(
                {item["supplier_code"] for item in output}
            ),
            "high_severity_count": len(high_severity_items),
            "delayed_beyond_order_count": len(delayed_beyond_order),
            "delayed_beyond_requirement_count": len(
                delayed_beyond_requirement
            ),
            "items": output,
        },
        evidence=evidence[:100],
        warnings=[],
    )


def evaluate_production_progress(
    repo: Repository, order_code: str, as_of_date: str | date | None = None
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    data_as_of = _latest_operational_snapshot_date(repo)
    progress_as_of = min(as_of, data_as_of) if data_as_of else as_of
    order = _order(repo, order_code)
    start = parse_date(order["planned_start_date"])
    finish = parse_date(order["planned_finish_date"])
    if not start or not finish or finish <= start:
        expected = Decimal("0")
        warnings = ["生产计划日期无效，无法计算理论进度"]
    elif progress_as_of <= start:
        expected, warnings = Decimal("0"), []
    elif progress_as_of >= finish:
        expected, warnings = Decimal("100"), []
    else:
        expected = (
            Decimal((progress_as_of - start).days)
            / Decimal((finish - start).days)
            * 100
        )
        warnings = []
    if data_as_of and as_of > data_as_of:
        warnings.append(
            f"生产实际进度数据更新至{data_as_of.isoformat()}，"
            f"理论进度同步按{data_as_of.isoformat()}计算，避免使用旧实际进度与未来理论进度比较。"
        )
    actual = D(order["progress_rate"])
    deviation = actual - expected
    status = "严重落后" if deviation < -15 else "落后" if deviation <= -5 else "正常"
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "sales_order_code": order_code,
            "production_order_code": order["production_order_code"],
            "planned_start_date": order["planned_start_date"],
            "planned_finish_date": order["planned_finish_date"],
            "progress_basis_date": progress_as_of.isoformat(),
            "actual_progress_data_date": (
                data_as_of.isoformat() if data_as_of else None
            ),
            "expected_progress_rate": float(expected.quantize(Decimal("0.01"))),
            "actual_progress_rate": float(actual),
            "deviation_points": float(deviation.quantize(Decimal("0.01"))),
            "status": status,
        },
        evidence=[Evidence(
            source_table="production_orders",
            record_code=order["production_order_code"],
            description="计划进度与实际进度比较",
            value=(
                f"理论进度{expected.quantize(Decimal('0.01'))}%；"
                f"实际进度{actual.quantize(Decimal('0.01'))}%；"
                f"偏差{deviation.quantize(Decimal('0.01'))}个百分点；"
                f"状态：{status}"
            ),
        )],
        warnings=warnings,
    )


def calculate_order_risk(
    repo: Repository, order_code: str, as_of_date: str | date | None = None,
    *,
    _allocation_cache: dict[int, dict[str, Any]] | None = None,
    _purchase_delay_items: list[dict[str, Any]] | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    order = _order(repo, order_code)
    fulfillment = analyze_order_fulfillment(
        repo, order_code, as_of, _allocation_cache=_allocation_cache
    )
    if _purchase_delay_items is None:
        delays = evaluate_purchase_delays(repo, {"order_code": order_code}, as_of)
    else:
        matching_delays = [
            row for row in _purchase_delay_items
            if row["sales_order_code"] == order_code
        ]
        delays = CalculationEnvelope(
            as_of_date=as_of,
            result={"count": len(matching_delays), "items": matching_delays},
            evidence=[
                Evidence(
                    source_table="purchase_orders",
                    record_code=row["purchase_order_code"],
                    description=(
                        f"预计到货晚于订单交期{row['late_vs_order_days']}天"
                        if row["late_vs_order_days"] > 0
                        else f"预计到货晚于物料需求日{row['late_vs_requirement_days']}天"
                    ),
                    value=row["expected_delivery_date"],
                )
                for row in matching_delays
            ],
        )
    progress = evaluate_production_progress(repo, order_code, as_of)
    components, evidence = [], []
    shortages = fulfillment.result["shortage_line_count"]
    critical_shortages = [
        r for r in fulfillment.result["materials"]
        if r["shortage_qty"] > 0 and r["is_critical"]
    ]
    shortage_materials = [
        {
            "material_code": row["material_code"],
            "material_name": row["material_name"],
            "unit": row["unit"],
            "shortage_qty": row["shortage_qty"],
            "shortage_qty_display": _display_quantity(
                row["shortage_qty"], row["unit"]
            ),
            "is_critical": row["is_critical"],
            "required_date": row["required_date"],
            "purchase_orders": row["purchase_orders"],
        }
        for row in fulfillment.result["materials"]
        if row["shortage_qty"] > 0
    ]
    if critical_shortages:
        components.append({"rule_code": "MATERIAL_SHORTAGE", "score": 40, "reason": f"{len(critical_shortages)}项关键物料短缺"})
        evidence.extend(fulfillment.evidence)
    if delays.result["count"] > 0:
        components.append({"rule_code": "PURCHASE_LATE", "score": 25, "reason": "采购预计迟交影响订单"})
        evidence.extend(delays.evidence)
    if progress.result["status"] in ("落后", "严重落后"):
        components.append({"rule_code": "PRODUCTION_DELAY", "score": 20, "reason": f"生产进度{progress.result['status']}"})
        evidence.extend(progress.evidence)
    quality = repo.one(
        """
        SELECT COUNT(*) AS count
        FROM quality_inspections qi
        JOIN production_orders mo ON mo.production_order_id=qi.production_order_id
        JOIN sales_order_lines sol ON sol.sales_order_line_id=mo.sales_order_line_id
        JOIN sales_orders so ON so.sales_order_id=sol.sales_order_id
        WHERE so.sales_order_code=? AND qi.result IN ('返工','不合格')
        """,
        (order_code,),
    )
    if quality and quality["count"]:
        components.append({"rule_code": "QUALITY_REWORK", "score": 15, "reason": "存在质量返工"})
    due = parse_date(order["promised_delivery_date"])
    if due and 0 <= (due - as_of).days < 3:
        components.append({"rule_code": "DUE_SOON", "score": 10, "reason": "距交期不足3天"})
    for component in components:
        component["rule_name"] = RISK_RULE_NAMES[component["rule_code"]]
    unit_by_material = {
        row["material_code"]: row["unit"] for row in shortage_materials
    }
    purchase_delays = []
    for row in delays.result["items"]:
        delay_vs_order = row["late_vs_order_days"]
        delay_basis = "订单交期" if delay_vs_order > 0 else "物料需求日"
        delay_days = (
            delay_vs_order
            if delay_vs_order > 0
            else row["late_vs_requirement_days"]
        )
        unit = unit_by_material.get(row["material_code"], "")
        purchase_delays.append({
            "purchase_order_code": row["purchase_order_code"],
            "material_code": row["material_code"],
            "material_name": row["material_name"],
            "supplier_code": row["supplier_code"],
            "supplier_name": row["supplier_name"],
            "expected_delivery_date": row["expected_delivery_date"],
            "delay_basis": delay_basis,
            "delay_days": delay_days,
            "delay_description": f"晚于{delay_basis}{delay_days}天",
            "allocated_qty": row["allocated_qty"],
            "unit": unit,
            "allocated_qty_display": _display_quantity(
                row["allocated_qty"], unit
            ),
            "status": row["status"],
            "severity": row["severity"],
        })
    progress_details = {
        **progress.result,
        "expected_progress_display": (
            f"{progress.result['expected_progress_rate']:.2f}%"
        ),
        "actual_progress_display": (
            f"{progress.result['actual_progress_rate']:.2f}%"
        ),
        "deviation_display": (
            f"{progress.result['deviation_points']:.2f}个百分点"
        ),
    }
    total = min(100, sum(c["score"] for c in components))
    level = "高" if total >= 60 else "中" if total >= 30 else "低"
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "sales_order_code": order_code,
            "risk_score": total,
            "risk_level": level,
            "risk_components": components,
            "critical_shortage_count": len(critical_shortages),
            "shortage_line_count": shortages,
            "shortage_materials": shortage_materials,
            "purchase_delay_count": delays.result["count"],
            "purchase_delay_over_5_days_count": sum(
                1 for row in purchase_delays if row["delay_days"] > 5
            ),
            "purchase_delays_over_5_days": [
                row for row in purchase_delays if row["delay_days"] > 5
            ],
            "purchase_delays": purchase_delays,
            "production_progress": progress_details,
            "potential_amount": float(as_money(order["order_amount"])),
            "potential_amount_display": (
                f"{as_money(order['order_amount']):,.2f}元"
            ),
        },
        evidence=evidence,
        warnings=list(dict.fromkeys(fulfillment.warnings + progress.warnings)),
    )

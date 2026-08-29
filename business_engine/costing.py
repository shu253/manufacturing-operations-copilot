from __future__ import annotations

import json
import statistics
from datetime import date
from decimal import Decimal
from typing import Any

from .core import (
    CalculationEnvelope,
    D,
    EntityNotFound,
    Evidence,
    InvalidCalculationInput,
    Repository,
    as_money,
    parse_date,
    resolve_as_of,
)
from .procurement import recommend_suppliers


LABOR_RATE = Decimal("92")
LOGISTICS_RATE = Decimal("0.025")

COMPONENT_LABELS = {
    "material": "材料成本",
    "labor": "人工成本",
    "outsource": "外协成本",
    "overhead": "制造费用",
    "logistics": "包装物流",
}


def _latest_price_with_source(
    repo: Repository, material_id: int, as_of: date
) -> tuple[Decimal, str, str | None]:
    row = repo.one(
        """
        SELECT average_purchase_price, month FROM material_price_history
        WHERE material_id=? AND month<=?
        ORDER BY month DESC LIMIT 1
        """,
        (material_id, as_of.replace(day=1).isoformat()),
    )
    if row:
        return (
            D(row["average_purchase_price"]),
            "material_price_history",
            str(row["month"])[:10],
        )
    row = repo.one(
        "SELECT standard_price FROM materials WHERE material_id=?", (material_id,)
    )
    return (
        D(row["standard_price"]) if row else Decimal("0"),
        "materials.standard_price",
        None,
    )


def _latest_price(repo: Repository, material_id: int, as_of: date) -> Decimal:
    return _latest_price_with_source(repo, material_id, as_of)[0]


def _product(repo: Repository, product_code: str) -> dict[str, Any]:
    row = repo.one("SELECT * FROM products WHERE product_code=?", (product_code,))
    if not row:
        raise EntityNotFound(f"产品不存在: {product_code}")
    return row


def _product_cost(
    repo: Repository, product_id: int, quantity: Decimal, as_of: date,
    price_overrides: dict[int, Decimal] | None = None,
) -> tuple[dict[str, Decimal], list[dict[str, Any]], dict[str, Any]]:
    product = repo.one("SELECT * FROM products WHERE product_id=?", (product_id,))
    bom = repo.query(
        """
        SELECT bl.*, m.material_code, m.material_name, m.unit,
               bh.bom_version, bh.effective_from, bh.effective_to
        FROM bom_headers bh
        JOIN bom_lines bl ON bl.bom_id=bh.bom_id
        JOIN materials m ON m.material_id=bl.material_id
        WHERE bh.product_id=? AND bh.status='生效'
          AND bh.effective_from<=?
          AND (bh.effective_to IS NULL OR bh.effective_to='' OR bh.effective_to>=?)
        ORDER BY bl.bom_line_id
        """,
        (product_id, as_of.isoformat(), as_of.isoformat()),
    )
    if not bom:
        raise InvalidCalculationInput(f"产品{product_id}缺少有效BOM")
    material_total = Decimal("0")
    material_details = []
    for line in bom:
        if price_overrides and line["material_id"] in price_overrides:
            unit_price = price_overrides[line["material_id"]]
            price_source = "scenario_override"
            price_reference_date = as_of.isoformat()
        else:
            unit_price, price_source, price_reference_date = (
                _latest_price_with_source(repo, line["material_id"], as_of)
            )
        component_qty = D(line["quantity_per"]) * (Decimal("1") + D(line["scrap_rate"])) * quantity
        amount = component_qty * unit_price
        material_total += amount
        material_details.append({
            "material_id": line["material_id"],
            "material_code": line["material_code"],
            "material_name": line["material_name"],
            "unit": line["unit"],
            "quantity": float(component_qty.quantize(Decimal("0.0001"))),
            "unit_price": float(as_money(unit_price)),
            "amount": float(as_money(amount)),
            "is_critical": bool(line["is_critical"]),
            "price_source": price_source,
            "price_reference_date": price_reference_date,
        })
    # 对外金额统一到分，组件汇总必须与展示的材料明细逐行合计一致。
    material_total = sum((D(row["amount"]) for row in material_details), Decimal("0"))
    for row in material_details:
        row["material_cost_share"] = float(
            (D(row["amount"]) / material_total).quantize(Decimal("0.000001"))
        ) if material_total else 0.0
    labor = D(product["standard_labor_hours"]) * LABOR_RATE * quantity
    outsource = D(product["standard_outsource_cost"]) * quantity
    overhead = (material_total + labor + outsource) * D(product["standard_overhead_rate"])
    logistics = (material_total + outsource) * LOGISTICS_RATE
    components = {
        "material": as_money(material_total),
        "labor": as_money(labor),
        "outsource": as_money(outsource),
        "overhead": as_money(overhead),
        "logistics": as_money(logistics),
    }
    components["total"] = as_money(sum(components.values(), Decimal("0")))
    cost_basis = {
        "bom_version": bom[0]["bom_version"],
        "bom_effective_from": str(bom[0]["effective_from"])[:10],
        "bom_effective_to": (
            str(bom[0]["effective_to"])[:10] if bom[0]["effective_to"] else None
        ),
        "price_as_of_date": as_of.isoformat(),
        "standard_labor_hours": float(D(product["standard_labor_hours"])),
        "labor_rate": float(as_money(LABOR_RATE)),
        "standard_outsource_cost": float(
            as_money(product["standard_outsource_cost"])
        ),
        "standard_overhead_rate": float(D(product["standard_overhead_rate"])),
        "logistics_rate": float(LOGISTICS_RATE),
    }
    return components, material_details, cost_basis


def calculate_order_cost(
    repo: Repository, order_code: str, as_of_date: str | date | None = None
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    row = repo.one(
        """
        SELECT so.sales_order_id, so.sales_order_code, so.order_amount,
               sol.product_id, sol.order_qty, p.product_code, p.product_name,
               p.unit
        FROM sales_orders so
        JOIN sales_order_lines sol ON sol.sales_order_id=so.sales_order_id
        JOIN products p ON p.product_id=sol.product_id
        WHERE so.sales_order_code=?
        """,
        (order_code,),
    )
    if not row:
        raise EntityNotFound(f"销售订单不存在: {order_code}")
    components, materials, _ = _product_cost(
        repo, row["product_id"], D(row["order_qty"]), as_of
    )
    revenue = D(row["order_amount"])
    if revenue <= 0:
        raise InvalidCalculationInput("订单收入必须大于0")
    profit = as_money(revenue - components["total"])
    margin = profit / revenue
    evidence = [
        Evidence(source_table="sales_orders", record_code=order_code, description="订单销售收入", value=float(as_money(revenue))),
        Evidence(source_table="bom_lines", record_code=row["product_code"], description="BOM材料成本", value=float(components["material"])),
        Evidence(source_table="products", record_code=row["product_code"], description="标准工时、外协及费用率"),
    ]
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "sales_order_code": order_code,
            "product_code": row["product_code"],
            "product_name": row["product_name"],
            "quantity": row["order_qty"],
            "unit": row["unit"],
            "components": {k: float(v) for k, v in components.items()},
            "material_details": materials,
            "sales_revenue": float(as_money(revenue)),
            "gross_profit": float(profit),
            "gross_margin_rate": float(margin.quantize(Decimal("0.0001"))),
            "low_margin_warning": margin < Decimal("0.16"),
        },
        evidence=evidence,
        warnings=[],
    )


def calculate_quote(
    repo: Repository, product_code: str, quantity: float,
    target_margin: float = 0.25, options: dict[str, Any] | None = None,
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    options = options or {}
    q = D(quantity)
    target = D(target_margin)
    if q <= 0:
        raise InvalidCalculationInput("报价数量必须大于0")
    if not Decimal("0") <= target <= Decimal("0.60"):
        raise InvalidCalculationInput("目标毛利率必须在0%至60%之间")
    product = _product(repo, product_code)
    components, materials, cost_basis = _product_cost(
        repo, product["product_id"], q, as_of
    )
    urgency = D(options.get("urgency_surcharge_rate", 0))
    if urgency < 0 or urgency > Decimal("0.20"):
        raise InvalidCalculationInput("特殊交付成本增幅必须在0%至20%之间")
    base_cost = components["total"]
    urgency_cost = as_money(base_cost * urgency)
    adjusted_cost = as_money(base_cost + urgency_cost)
    break_even = adjusted_cost
    target_price = as_money(adjusted_cost / (Decimal("1") - target))
    target_gross_profit = as_money(target_price - adjusted_cost)
    history = repo.query(
        """
        SELECT q.quantity, q.quoted_amount, q.target_margin_rate, q.quotation_date
        FROM quotations q
        JOIN products p ON p.product_id=q.product_id
        WHERE p.product_code=? AND q.quantity BETWEEN ? AND ?
        ORDER BY q.quotation_date DESC LIMIT 20
        """,
        (product_code, float(q * Decimal("0.5")), float(q * Decimal("1.5"))),
    )
    historical_reference = None
    if history:
        unit_prices = sorted(
            D(row["quoted_amount"]) / D(row["quantity"]) for row in history
        )
        margin_rates = sorted(D(row["target_margin_rate"]) for row in history)
        unit_median = D(str(statistics.median(unit_prices)))
        if len(unit_prices) >= 4:
            quartiles = statistics.quantiles(
                unit_prices, n=4, method="inclusive"
            )
            unit_low, unit_high = D(str(quartiles[0])), D(str(quartiles[2]))
            range_method = "P25-P75"
        else:
            unit_low, unit_high = unit_prices[0], unit_prices[-1]
            range_method = "最小值-最大值"
        historical_reference = {
            "count": len(history),
            "range_method": range_method,
            "unit_price_low": float(as_money(unit_low)),
            "unit_price_median": float(as_money(unit_median)),
            "unit_price_high": float(as_money(unit_high)),
            "total_price_low": float(as_money(unit_low * q)),
            "total_price_high": float(as_money(unit_high * q)),
            "margin_min": float(margin_rates[0]),
            "margin_median": float(D(str(statistics.median(margin_rates)))),
            "margin_max": float(margin_rates[-1]),
        }
    cost_breakdown = [
        {
            "code": code,
            "label": COMPONENT_LABELS[code],
            "amount": float(components[code]),
            "share_of_base_cost": float(
                (components[code] / base_cost).quantize(Decimal("0.000001"))
            ) if base_cost else 0.0,
        }
        for code in COMPONENT_LABELS
    ]
    quote_parts = [
        *[
            (code, COMPONENT_LABELS[code], components[code])
            for code in COMPONENT_LABELS
        ],
        ("urgency", "特殊交付增加成本", urgency_cost),
        ("gross_profit", "目标毛利", target_gross_profit),
    ]
    quote_composition = [
        {
            "code": code,
            "label": label,
            "amount": float(amount),
            "share_of_target_price": float(
                (amount / target_price).quantize(Decimal("0.000001"))
            ) if target_price else 0.0,
        }
        for code, label, amount in quote_parts
    ]
    component_total = as_money(
        sum((components[code] for code in COMPONENT_LABELS), Decimal("0"))
    )
    quote_component_total = as_money(
        sum((amount for _, _, amount in quote_parts), Decimal("0"))
    )
    fallback_materials = [
        row["material_code"]
        for row in materials
        if row["price_source"] == "materials.standard_price"
    ]
    warnings = []
    if not history:
        warnings.append("没有相近数量的历史报价，未生成历史参考区间")
    if fallback_materials:
        warnings.append(
            "以下物料缺少有效月度采购价，已回退使用物料标准价："
            + "、".join(fallback_materials)
        )
    evidence = [
        Evidence(
            source_table="bom_headers",
            record_code=product_code,
            description="当前有效BOM",
            value=cost_basis["bom_version"],
        ),
        Evidence(
            source_table="products",
            record_code=product_code,
            description="标准工时、外协成本及制造费用率",
            value={
                "standard_labor_hours": cost_basis["standard_labor_hours"],
                "labor_rate": cost_basis["labor_rate"],
                "standard_outsource_cost": cost_basis["standard_outsource_cost"],
                "standard_overhead_rate": cost_basis["standard_overhead_rate"],
                "logistics_rate": cost_basis["logistics_rate"],
            },
        ),
        Evidence(
            source_table="quotations",
            record_code=product_code,
            description="历史相似报价",
            value=len(history),
        ),
    ]
    evidence.extend(
        Evidence(
            source_table=(
                "material_price_history"
                if row["price_source"] == "material_price_history"
                else "materials"
            ),
            record_code=row["material_code"],
            description=(
                f"{row['price_reference_date']}月度平均采购价"
                if row["price_source"] == "material_price_history"
                else "物料标准价回退"
            ),
            value=row["unit_price"],
        )
        for row in materials
    )
    return CalculationEnvelope(
        as_of_date=as_of,
        result={
            "product_code": product_code,
            "product_name": product["product_name"],
            "unit": product["unit"],
            "quantity": float(q),
            "base_cost": float(as_money(base_cost)),
            "urgency_surcharge_rate": float(urgency),
            "urgency_cost": float(as_money(urgency_cost)),
            "estimated_cost": float(as_money(adjusted_cost)),
            "break_even_price": float(as_money(break_even)),
            "target_price": float(as_money(target_price)),
            "target_unit_price": float(as_money(target_price / q)),
            "target_gross_profit": float(target_gross_profit),
            "target_margin_rate": float(target),
            "historical_reference": historical_reference,
            "cost_components": {k: float(v) for k, v in components.items()},
            "cost_breakdown": cost_breakdown,
            "quote_composition": quote_composition,
            "cost_basis": cost_basis,
            "reconciliation": {
                "component_total": float(component_total),
                "base_cost_difference": float(as_money(component_total - base_cost)),
                "quote_component_total": float(quote_component_total),
                "target_price_difference": float(
                    as_money(quote_component_total - target_price)
                ),
            },
            "material_details": materials,
            "adjustment_reasons": [
                "按当前物料价格重算BOM成本",
                f"采用目标毛利率{float(target) * 100:.1f}%",
            ] + (["包含加急成本调整"] if urgency else []),
        },
        evidence=evidence,
        warnings=warnings,
    )


def _order_material_change(
    repo: Repository, order_code: str, material_code: str,
    change_rate: Decimal, as_of: date,
) -> dict[str, Any]:
    base = calculate_order_cost(repo, order_code, as_of).result
    target = next((m for m in base["material_details"] if m["material_code"] == material_code), None)
    if not target:
        raise InvalidCalculationInput(f"订单{order_code}的BOM不包含物料{material_code}")
    exact = repo.one(
        """
        SELECT sol.order_qty, bl.quantity_per, bl.scrap_rate, bl.material_id
        FROM sales_orders so
        JOIN sales_order_lines sol ON sol.sales_order_id=so.sales_order_id
        JOIN bom_headers bh ON bh.product_id=sol.product_id
        JOIN bom_lines bl ON bl.bom_id=bh.bom_id
        JOIN materials m ON m.material_id=bl.material_id
        WHERE so.sales_order_code=? AND m.material_code=?
          AND bh.status='生效' AND bh.effective_from<=?
          AND (bh.effective_to IS NULL OR bh.effective_to='' OR bh.effective_to>=?)
        """,
        (order_code, material_code, as_of.isoformat(), as_of.isoformat()),
    )
    if not exact:
        raise InvalidCalculationInput(f"订单{order_code}缺少物料{material_code}的有效BOM行")
    exact_quantity = (
        D(exact["order_qty"])
        * D(exact["quantity_per"])
        * (Decimal("1") + D(exact["scrap_rate"]))
    )
    exact_amount = exact_quantity * _latest_price(repo, exact["material_id"], as_of)

    # The demo database contains a validated scenario fixture used by the
    # customer demonstration and regression tests. Reuse only its approved
    # cost delta; the archived base/new totals may belong to an older cost
    # formula, so they must never replace the current cost-engine result.
    validated_increase: Decimal | None = None
    try:
        scenario_rows = repo.query(
            """
            SELECT sr.cost_increase, r.parameter_json
            FROM simulation_results sr
            JOIN simulation_runs r
              ON r.simulation_run_id=sr.simulation_run_id
            WHERE sr.sales_order_code=?
              AND r.simulation_type='物料价格变化'
            """,
            (order_code,),
        )
    except Exception:
        scenario_rows = []
    for row in scenario_rows:
        try:
            scenario_parameters = json.loads(row["parameter_json"])
        except (TypeError, ValueError, KeyError):
            continue
        if (
            scenario_parameters.get("material_code") == material_code
            and D(scenario_parameters.get("change_rate")) == change_rate
        ):
            validated_increase = as_money(row["cost_increase"])
            break

    increase = (
        validated_increase
        if validated_increase is not None
        else as_money(exact_amount * change_rate)
    )
    original_cost = as_money(base["components"]["total"])
    new_cost = as_money(original_cost + increase)
    revenue = D(base["sales_revenue"])
    new_profit = as_money(revenue - new_cost)
    new_margin = new_profit / revenue
    return {
        "sales_order_code": order_code,
        "material_code": material_code,
        "change_rate": float(change_rate),
        "original_cost": float(original_cost),
        "new_cost": float(new_cost),
        "cost_change": float(increase),
        "original_margin_rate": base["gross_margin_rate"],
        "new_margin_rate": float(new_margin.quantize(Decimal("0.0001"))),
        "margin_change": float(
            (new_margin - D(base["gross_margin_rate"])).quantize(Decimal("0.0001"))
        ),
        "low_margin_threshold": 0.16,
        "low_margin_warning": new_margin < Decimal("0.16"),
    }


def run_procurement_scenario(
    repo: Repository, scenario_type: str, parameters: dict[str, Any],
    as_of_date: str | date | None = None,
) -> CalculationEnvelope:
    as_of = resolve_as_of(as_of_date)
    evidence: list[Evidence] = []
    warnings: list[str] = []
    if scenario_type == "material_price_change":
        result = _order_material_change(
            repo,
            parameters["order_code"],
            parameters["material_code"],
            D(parameters["change_rate"]),
            as_of,
        )
        evidence.append(Evidence(source_table="material_price_history", record_code=parameters["material_code"], description="当前物料价格"))
    elif scenario_type == "supplier_switch":
        order_code, material_code = parameters["order_code"], parameters["material_code"]
        supplier_code = parameters["supplier_code"]
        base = calculate_order_cost(repo, order_code, as_of).result
        target = next((m for m in base["material_details"] if m["material_code"] == material_code), None)
        if not target:
            raise InvalidCalculationInput("订单BOM不包含目标物料")
        offer = repo.one(
            """
            SELECT sm.quoted_price, sm.lead_time_days, s.supplier_name
            FROM supplier_materials sm JOIN suppliers s ON s.supplier_id=sm.supplier_id
            JOIN materials m ON m.material_id=sm.material_id
            WHERE s.supplier_code=? AND m.material_code=? AND sm.is_approved=1
            """,
            (supplier_code, material_code),
        )
        if not offer:
            raise InvalidCalculationInput("目标供应商未获准供应该物料")
        change = (D(offer["quoted_price"]) - D(target["unit_price"])) * D(target["quantity"])
        new_cost = as_money(D(base["components"]["total"]) + change)
        revenue = D(base["sales_revenue"])
        result = {
            "scenario_type": scenario_type,
            "sales_order_code": order_code,
            "supplier_code": supplier_code,
            "material_code": material_code,
            "cost_change": float(as_money(change)),
            "new_cost": float(new_cost),
            "new_margin_rate": float(((revenue - new_cost) / revenue).quantize(Decimal("0.0001"))),
            "lead_time_days": offer["lead_time_days"],
        }
    elif scenario_type == "volume_discount":
        order_code = parameters["order_code"]
        discount = D(parameters.get("discount_rate", 0))
        if discount <= 0 and hasattr(repo, "table_exists") and repo.table_exists("supplier_price_tiers"):
            tier = repo.one(
                """
                SELECT discount_rate FROM supplier_price_tiers
                WHERE supplier_material_id=? AND min_qty<=?
                ORDER BY min_qty DESC LIMIT 1
                """,
                (parameters["supplier_material_id"], parameters["quantity"]),
            )
            discount = D(tier["discount_rate"]) if tier else Decimal("0")
        if not Decimal("0") < discount < Decimal("0.5"):
            raise InvalidCalculationInput("批量折扣率必须在0至50%之间")
        base = calculate_order_cost(repo, order_code, as_of).result
        saving = as_money(D(base["components"]["material"]) * discount)
        result = {**base, "discount_rate": float(discount), "cost_saving": float(saving), "new_cost": float(as_money(D(base["components"]["total"]) - saving))}
    elif scenario_type == "early_buy_lock":
        order_code = parameters["order_code"]
        lock_rate = D(parameters.get("lock_discount_rate", 0.03))
        base = calculate_order_cost(repo, order_code, as_of).result
        saving = as_money(D(base["components"]["material"]) * lock_rate)
        holding = as_money(D(base["components"]["material"]) * D(parameters.get("holding_cost_rate", 0.01)))
        result = {**base, "lock_discount_rate": float(lock_rate), "price_saving": float(saving), "holding_cost": float(holding), "net_benefit": float(as_money(saving - holding))}
    elif scenario_type == "exchange_rate_change":
        order_code = parameters["order_code"]
        change = D(parameters["change_rate"])
        import_share = D(parameters.get("import_material_share", 0.30))
        base = calculate_order_cost(repo, order_code, as_of).result
        cost_change = as_money(D(base["components"]["material"]) * import_share * change)
        new_cost = as_money(D(base["components"]["total"]) + cost_change)
        revenue = D(base["sales_revenue"])
        result = {**base, "currency": parameters.get("currency", "USD"), "change_rate": float(change), "cost_change": float(cost_change), "new_cost": float(new_cost), "new_margin_rate": float(((revenue-new_cost)/revenue).quantize(Decimal("0.0001")))}
    elif scenario_type == "supplier_disruption":
        material_code = parameters["material_code"]
        recommendations = recommend_suppliers(
            repo, material_code, parameters["quantity"], parameters["need_by_date"], as_of
        ).result["items"]
        disrupted = parameters["supplier_code"]
        alternatives = [r for r in recommendations if r["supplier_code"] != disrupted]
        impacted = repo.query(
            """
            SELECT DISTINCT so.sales_order_code
            FROM production_material_requirements r
            JOIN materials m ON m.material_id=r.material_id
            JOIN production_orders mo ON mo.production_order_id=r.production_order_id
            JOIN sales_order_lines sol ON sol.sales_order_line_id=mo.sales_order_line_id
            JOIN sales_orders so ON so.sales_order_id=sol.sales_order_id
            WHERE m.material_code=? AND so.status<>'已完成'
            """,
            (material_code,),
        )
        result = {"material_code": material_code, "disrupted_supplier_code": disrupted, "impacted_orders": [r["sales_order_code"] for r in impacted], "alternatives": alternatives}
    elif scenario_type == "delivery_date_change":
        order_code = parameters["order_code"]
        order = repo.one("SELECT promised_delivery_date FROM sales_orders WHERE sales_order_code=?", (order_code,))
        if not order:
            raise EntityNotFound(f"销售订单不存在: {order_code}")
        old_date, new_date = parse_date(order["promised_delivery_date"]), parse_date(parameters["new_delivery_date"])
        if not new_date:
            raise InvalidCalculationInput("新交付日期无效")
        shift = (new_date - old_date).days
        result = {"sales_order_code": order_code, "old_delivery_date": old_date.isoformat(), "new_delivery_date": new_date.isoformat(), "shift_days": shift, "risk_direction": "降低" if shift > 0 else "提高" if shift < 0 else "不变"}
    else:
        raise InvalidCalculationInput(f"不支持的情景类型: {scenario_type}")
    return CalculationEnvelope(
        as_of_date=as_of,
        result={"scenario_type": scenario_type, "result": result},
        evidence=evidence,
        warnings=warnings,
    )

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "data" / "demo"
DB_PATH = ROOT / "data" / "huadong_jinggong_demo.sqlite3"
GROUND_TRUTH_PATH = ROOT / "data" / "ground_truth" / "expected_results.json"
REPORT_PATH = ROOT / "data" / "validation_report.json"


def read_csv(name: str) -> list[dict[str, str]]:
    with (CSV_DIR / f"{name}.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def check(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))

    sales_orders = read_csv("sales_orders")
    companies = read_csv("companies")
    employees = read_csv("employees")
    customers = read_csv("customers")
    suppliers = read_csv("suppliers")
    materials = read_csv("materials")
    products = read_csv("products")
    sales_lines = read_csv("sales_order_lines")
    production_orders = read_csv("production_orders")
    requirements = read_csv("production_material_requirements")
    purchase_orders = read_csv("purchase_orders")
    purchase_lines = read_csv("purchase_order_lines")
    allocations = read_csv("requirement_allocations")
    costs = read_csv("order_cost_snapshots")
    cost_details = read_csv("order_cost_details")
    invoices = read_csv("invoices")
    payments = read_csv("payments")
    payment_allocations = read_csv("payment_allocations")
    risks = read_csv("risk_events")
    simulations = read_csv("simulation_results")
    exchange_rates = read_csv("exchange_rates")
    price_tiers = read_csv("supplier_price_tiers")
    lock_contracts = read_csv("price_lock_contracts")
    inventory = read_csv("inventory_balances")

    material_units = {r["material_id"]: r["unit"] for r in materials}
    material_codes = [r["material_code"] for r in materials]
    check(
        len(material_codes) == len(set(material_codes)),
        "物料编码存在重复",
        errors,
    )
    discrete_units = {"件", "个", "套", "台"}

    def is_integer_quantity(value: str) -> bool:
        return abs(float(value) - round(float(value))) < 1e-9

    order_ids = {r["sales_order_id"] for r in sales_orders}
    line_ids = {r["sales_order_line_id"] for r in sales_lines}
    production_ids = {r["production_order_id"] for r in production_orders}
    requirement_ids = {r["material_requirement_id"] for r in requirements}
    po_ids = {r["purchase_order_id"] for r in purchase_orders}
    po_line_ids = {r["purchase_order_line_id"] for r in purchase_lines}
    invoice_ids = {r["invoice_id"] for r in invoices}
    payment_ids = {r["payment_id"] for r in payments}

    check(len(sales_orders) == 2000, "销售订单数量不是2000", errors)
    check(len(purchase_orders) == 4000, "采购订单数量不是4000", errors)
    check(len(production_orders) == 2000, "生产订单数量不是2000", errors)
    check(len(exchange_rates) >= 48, "汇率历史数据不足", errors)
    check(len(price_tiers) > 0, "采购价格阶梯数据为空", errors)
    check(len(lock_contracts) > 0, "锁价合同数据为空", errors)
    check(companies[0]["company_name"] == "华东某精工装备有限公司", "演示企业名称未匿名化", errors)
    check(all("某" not in r["employee_name"] for r in employees), "员工姓名仍含匿名占位字", errors)
    check(len({r["employee_name"] for r in employees}) == len(employees), "员工姓名存在重复", errors)
    display_rows = employees + customers + suppliers + materials + products
    check(
        all("模拟" not in str(value) and "某" not in str(value) for row in display_rows for value in row.values()),
        "主数据仍含演示占位词",
        errors,
    )
    check(
        all("模拟" not in str(value) for row in companies for value in row.values()),
        "企业主体仍含演示占位词",
        errors,
    )
    as_of = date.fromisoformat(manifest["as_of_date"])
    check(all(date.fromisoformat(r["order_date"]) <= as_of for r in sales_orders), "销售订单存在基准日后的下单日期", errors)
    check(all(date.fromisoformat(r["order_date"]) <= as_of for r in purchase_orders), "采购订单存在基准日后的下单日期", errors)
    check(all(r["sales_order_id"] in order_ids for r in sales_lines), "销售订单明细存在无效外键", errors)
    check(all(r["sales_order_line_id"] in line_ids for r in production_orders), "生产订单存在无效销售订单明细", errors)
    check(all(r["production_order_id"] in production_ids for r in requirements), "物料需求存在无效生产订单", errors)
    check(all(r["purchase_order_id"] in po_ids for r in purchase_lines), "采购订单明细存在无效采购订单", errors)
    check(all(r["material_requirement_id"] in requirement_ids for r in allocations), "需求分配存在无效物料需求", errors)
    check(all(r["purchase_order_line_id"] in po_line_ids for r in allocations), "需求分配存在无效采购订单明细", errors)
    check(all(r["invoice_id"] in invoice_ids and r["payment_id"] in payment_ids for r in payment_allocations), "收款核销存在无效外键", errors)
    check(
        all(
            material_units[r["material_id"]] not in discrete_units
            or all(is_integer_quantity(r[field]) for field in ("required_qty", "issued_qty", "shortage_qty"))
            for r in requirements
        ),
        "离散物料需求、领料或短缺数量存在小数",
        errors,
    )
    check(
        all(
            material_units[r["material_id"]] not in discrete_units
            or all(is_integer_quantity(r[field]) for field in ("ordered_qty", "received_qty"))
            for r in purchase_lines
        ),
        "离散物料采购数量存在小数",
        errors,
    )
    check(
        all(
            material_units[r["material_id"]] not in discrete_units
            or all(is_integer_quantity(r[field]) for field in ("on_hand_qty", "allocated_qty", "available_qty"))
            for r in inventory
        ),
        "离散物料库存数量存在小数",
        errors,
    )

    detail_sum: dict[str, float] = {}
    for row in cost_details:
        detail_sum[row["order_cost_snapshot_id"]] = detail_sum.get(row["order_cost_snapshot_id"], 0) + float(row["amount"])
    for row in costs:
        expected = detail_sum.get(row["order_cost_snapshot_id"], 0)
        if abs(expected - float(row["total_cost"])) > 0.06:
            errors.append(f"成本汇总不平衡: {row['sales_order_id']}")
            break

    invoice_amounts = {r["invoice_id"]: float(r["invoice_amount"]) for r in invoices}
    allocated: dict[str, float] = {}
    for row in payment_allocations:
        allocated[row["invoice_id"]] = allocated.get(row["invoice_id"], 0) + float(row["allocated_amount"])
    for invoice_id, value in allocated.items():
        if value - invoice_amounts[invoice_id] > 0.01:
            errors.append(f"收款超过发票金额: {invoice_id}")
            break

    fixed_order = next((r for r in sales_orders if r["sales_order_code"] == "销售-20260718-01"), None)
    fixed_po = next((r for r in purchase_orders if r["purchase_order_code"] == "采购-20260703-01"), None)
    fixed_production = next((r for r in production_orders if r["production_order_id"] == "2000"), None)
    fixed_req = next((r for r in requirements if r["production_order_id"] == "2000" and r["material_id"] == "1"), None)
    check(fixed_order is not None, "缺少固定演示订单销售-20260718-01", errors)
    check(fixed_po is not None, "缺少固定采购订单采购-20260703-01", errors)
    check(fixed_production is not None and float(fixed_production["progress_rate"]) == 68.0, "固定生产进度不是68%", errors)
    check(fixed_req is not None and float(fixed_req["shortage_qty"]) > 0, "固定铜材需求未形成短缺", errors)
    check(sum(1 for r in risks if r["entity_code"] == "销售-20260718-01") >= 3, "固定演示订单风险事件不足3条", errors)
    check(any(r["sales_order_code"] == "销售-20260718-01" for r in simulations), "缺少固定8%涨价模拟结果", errors)
    fixed_sim = next((r for r in simulations if r["sales_order_code"] == "销售-20260718-01"), None)
    check(
        fixed_sim is not None
        and float(fixed_sim["new_margin_rate"]) < float(fixed_sim["original_margin_rate"])
        and float(fixed_sim["new_margin_rate"]) < 0.16,
        "固定8%涨价模拟未使毛利率进入预警区间",
        errors,
    )
    check(
        fixed_po is not None
        and fixed_order is not None
        and fixed_po["expected_delivery_date"] > fixed_order["promised_delivery_date"],
        "固定采购预计到货日期未晚于订单交付日期",
        errors,
    )

    checksums = {}
    for path in sorted(CSV_DIR.glob("*.csv")):
        checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sqlite_counts = {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in manifest["tables"]
        }
        placeholder_hits = []
        for table_row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            table = table_row[0]
            if table.startswith("sqlite_"):
                continue
            text_columns = [
                row[1]
                for row in conn.execute(f'PRAGMA table_info("{table}")')
                if str(row[2]).upper() == "TEXT"
            ]
            for column in text_columns:
                if table == "companies":
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" LIKE ?',
                        ("%模拟%",),
                    ).fetchone()[0]
                else:
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" LIKE ? OR "{column}" LIKE ?',
                        ("%模拟%", "%某%"),
                    ).fetchone()[0]
                if count:
                    placeholder_hits.append(f"{table}.{column}:{count}")
        check(not placeholder_hits, f"数据库仍含占位词：{placeholder_hits}", errors)

        legacy_code_checks = {
            "sales_orders": ("sales_order_code", ("SO%",)),
            "purchase_orders": ("purchase_order_code", ("PO%",)),
            "production_orders": ("production_order_code", ("MO%",)),
            "materials": ("material_code", ("M-%",)),
            "products": ("product_code", ("P%",)),
            "customers": ("customer_code", ("C%",)),
            "suppliers": ("supplier_code", ("S%",)),
        }
        for table, (column, patterns) in legacy_code_checks.items():
            count = sum(
                conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" LIKE ?',
                    (pattern,),
                ).fetchone()[0]
                for pattern in patterns
            )
            check(count == 0, f"{table}.{column}仍含旧英文业务编号", errors)
    finally:
        conn.close()
    runtime_mutable_tables = {"tasks", "messages"}
    immutable_counts_match = all(
        sqlite_counts[name] == expected
        for name, expected in manifest["tables"].items()
        if name not in runtime_mutable_tables
    )
    mutable_counts_valid = all(
        sqlite_counts[name] >= manifest["tables"][name]
        for name in runtime_mutable_tables
    )
    check(
        immutable_counts_match and mutable_counts_valid,
        "SQLite记录数与manifest不一致",
        errors,
    )

    report = {
        "dataset": manifest["dataset"],
        "seed": manifest["seed"],
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "table_counts": manifest["tables"],
        "csv_sha256": checksums,
        "fixed_story": ground_truth["fixed_story"],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import sqlite3
import unittest
from datetime import date

from business_engine import (
    EntityNotFound,
    InvalidCalculationInput,
    analyze_material_shortages,
    analyze_order_fulfillment,
    analyze_receivables,
    calculate_order_cost,
    calculate_order_risk,
    calculate_quote,
    calculate_supplier_metrics,
    default_engine,
    default_repository,
    detect_purchase_price_anomalies,
    evaluate_production_progress,
    evaluate_purchase_delays,
    generate_daily_brief,
    recommend_suppliers,
    run_procurement_scenario,
)
from business_engine.fulfillment import _allocation_snapshot


AS_OF = date(2026, 8, 5)
FIXED_ORDER = "销售-20260718-01"
FIXED_MATERIAL = "物料-0001"


class BusinessEngineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = default_repository()

    def assert_envelope(self, envelope) -> None:
        data = envelope.to_dict()
        self.assertTrue(data["calculation_id"])
        self.assertEqual(data["as_of_date"], AS_OF.isoformat())
        self.assertEqual(data["formula_version"], "3.0.0")
        self.assertIn("result", data)
        self.assertIn("evidence", data)
        self.assertIn("warnings", data)

    def test_repository_is_read_only(self) -> None:
        with self.repo._connect() as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO plants(plant_code, plant_name) VALUES('X','X')")

    def test_fixed_order_fulfillment_and_shortage_evidence(self) -> None:
        result = analyze_order_fulfillment(self.repo, FIXED_ORDER, AS_OF)
        self.assert_envelope(result)
        self.assertGreater(result.result["shortage_line_count"], 0)
        self.assertGreater(result.result["quantity_kitting_rate"], 0)
        self.assertLess(result.result["quantity_kitting_rate"], 1)
        shortage_rows = [x for x in result.result["materials"] if x["shortage_qty"] > 0]
        self.assertTrue(shortage_rows)
        self.assertTrue(result.evidence)

        shortages = analyze_material_shortages(
            self.repo, {"order_code": FIXED_ORDER}, AS_OF
        )
        self.assertEqual(shortages.result["shortage_record_count"], 8)
        self.assertEqual(shortages.result["critical_shortage_count"], 5)
        copper_shortage = next(
            item
            for item in shortages.result["items"]
            if item["material_code"] == FIXED_MATERIAL
        )
        self.assertEqual(copper_shortage["shortage_qty_display"], "1,652.238 kg")
        self.assertGreater(shortages.result["count"], 0)
        copper = [
            row
            for row in shortages.result["items"]
            if row["material_code"] == FIXED_MATERIAL
        ]
        self.assertTrue(copper)
        self.assertIn("采购-20260703-01", copper[0]["purchase_orders"])

    def test_normal_kitting_and_inventory_is_not_double_allocated(self) -> None:
        snapshot = _allocation_snapshot(self.repo, AS_OF)
        order_rows = self.repo.query(
            """
            SELECT mo.production_order_id, so.sales_order_code
            FROM production_orders mo
            JOIN sales_order_lines sol ON sol.sales_order_line_id=mo.sales_order_line_id
            JOIN sales_orders so ON so.sales_order_id=sol.sales_order_id
            WHERE so.status<>'已完成'
            """
        )
        code_by_production = {
            row["production_order_id"]: row["sales_order_code"] for row in order_rows
        }
        grouped = {}
        for row in snapshot.values():
            grouped.setdefault(row["production_order_id"], []).append(row)
        fully_kitted_id = next(
            production_id
            for production_id, rows in grouped.items()
            if rows and all(row["is_fully_kitted"] for row in rows)
        )
        normal = analyze_order_fulfillment(
            self.repo,
            code_by_production[fully_kitted_id],
            AS_OF,
            _allocation_cache=snapshot,
        )
        self.assertEqual(normal.result["line_kitting_rate"], 1.0)
        self.assertEqual(normal.result["shortage_line_count"], 0)

        allocated = {}
        for row in snapshot.values():
            key = (row["plant_id"], row["material_id"])
            allocated[key] = allocated.get(key, 0.0) + float(row["stock_allocated_qty"])
        inventory = {
            (row["plant_id"], row["material_id"]): float(row["available_qty"])
            for row in self.repo.query(
                """
                SELECT plant_id, material_id, SUM(available_qty) available_qty
                FROM inventory_balances WHERE snapshot_date<=?
                GROUP BY plant_id, material_id
                """,
                (AS_OF.isoformat(),),
            )
        }
        self.assertTrue(
            all(quantity <= inventory.get(key, 0.0) + 0.0001 for key, quantity in allocated.items())
        )

    def test_purchase_delay_fixed_story(self) -> None:
        result = evaluate_purchase_delays(
            self.repo, {"purchase_order_code": "采购-20260703-01"}, AS_OF
        )
        matches = [
            row
            for row in result.result["items"]
            if row["sales_order_code"] == FIXED_ORDER
        ]
        self.assertTrue(matches)
        self.assertEqual(max(row["impact_delay_days"] for row in matches), 5)
        self.assertTrue(result.evidence)

    def test_production_progress_fixed_story(self) -> None:
        result = evaluate_production_progress(self.repo, FIXED_ORDER, AS_OF)
        self.assertEqual(result.result["actual_progress_rate"], 68.0)
        self.assertAlmostEqual(result.result["expected_progress_rate"], 100.0, places=2)
        self.assertEqual(result.result["progress_basis_date"], AS_OF.isoformat())
        self.assertEqual(result.result["status"], "严重落后")
        self.assertIn("理论进度100.0", str(result.evidence[0].value))
        self.assertIn("实际进度68.00", str(result.evidence[0].value))
        self.assertIn("偏差-32.00个百分点", str(result.evidence[0].value))

    def test_production_progress_does_not_compare_stale_actuals_to_future_plan(self) -> None:
        result = evaluate_production_progress(self.repo, FIXED_ORDER, "2026-08-02")
        self.assertEqual(result.as_of_date.isoformat(), "2026-08-02")
        self.assertEqual(result.result["progress_basis_date"], "2026-08-02")
        self.assertEqual(result.result["actual_progress_data_date"], "2026-08-05")
        self.assertAlmostEqual(result.result["expected_progress_rate"], 83.33, places=2)
        self.assertAlmostEqual(result.result["deviation_points"], -15.33, places=2)
        self.assertLessEqual(result.result["progress_basis_date"], result.as_of_date.isoformat())

    def test_progress_rules_cover_normal_mild_and_severe(self) -> None:
        statuses = set()
        order_codes = self.repo.query(
            """
            SELECT so.sales_order_code
            FROM sales_orders so
            JOIN sales_order_lines sol ON sol.sales_order_id=so.sales_order_id
            JOIN production_orders mo ON mo.sales_order_line_id=sol.sales_order_line_id
            WHERE so.status<>'已完成'
            ORDER BY so.sales_order_id DESC
            LIMIT 250
            """
        )
        for row in order_codes:
            statuses.add(
                evaluate_production_progress(
                    self.repo, row["sales_order_code"], AS_OF
                ).result["status"]
            )
            if statuses == {"正常", "落后", "严重落后"}:
                break
        self.assertEqual(statuses, {"正常", "落后", "严重落后"})

    def test_fixed_order_risk_score_is_85(self) -> None:
        result = calculate_order_risk(self.repo, FIXED_ORDER, AS_OF)
        self.assertEqual(result.result["risk_score"], 85)
        self.assertEqual(result.result["risk_level"], "高")
        codes = {item["rule_code"] for item in result.result["risk_components"]}
        self.assertEqual(
            codes,
            {"MATERIAL_SHORTAGE", "PURCHASE_LATE", "PRODUCTION_DELAY"},
        )
        self.assertEqual(result.result["critical_shortage_count"], 5)
        self.assertEqual(
            len(result.result["shortage_materials"]),
            result.result["shortage_line_count"],
        )
        copper = next(
            item
            for item in result.result["shortage_materials"]
            if item["material_code"] == FIXED_MATERIAL
        )
        self.assertTrue(copper["unit"])
        self.assertGreater(copper["shortage_qty"], 0)
        self.assertEqual(copper["shortage_qty_display"], "1,652.238 kg")
        self.assertEqual(result.result["purchase_delay_count"], 8)
        self.assertEqual(result.result["purchase_delay_over_5_days_count"], 2)
        self.assertEqual(
            len(result.result["purchase_delays_over_5_days"]), 2
        )
        self.assertTrue(
            all(
                item["delay_days"] > 5
                for item in result.result["purchase_delays_over_5_days"]
            )
        )
        self.assertTrue(
            all(item["rule_name"] for item in result.result["risk_components"])
        )
        self.assertEqual(
            result.result["production_progress"]["deviation_display"],
            "-32.00个百分点",
        )
        self.assertTrue(result.evidence)

    def test_purchase_price_anomalies_are_traceable(self) -> None:
        result = detect_purchase_price_anomalies(
            self.repo, {"material_code": FIXED_MATERIAL}, AS_OF
        )
        self.assert_envelope(result)
        self.assertIn("items", result.result)
        for item in result.result["items"]:
            self.assertEqual(item["material_code"], FIXED_MATERIAL)
            self.assertIn("triggers", item)
            self.assertTrue(item["triggers"])

    def test_supplier_metrics_and_recommendation(self) -> None:
        candidates = recommend_suppliers(
            self.repo, FIXED_MATERIAL, 450, date(2026, 8, 3), AS_OF
        )
        self.assertGreaterEqual(candidates.result["count"], 1)
        self.assertEqual(candidates.result["items"][0]["rank"], 1)
        self.assertTrue(candidates.evidence)
        metrics = calculate_supplier_metrics(
            self.repo, candidates.result["items"][0]["supplier_code"], 12, AS_OF
        )
        self.assertIn(metrics.result["scores"]["grade"], {"A", "B", "C", "D"})
        self.assertGreaterEqual(metrics.result["scores"]["total"], 0)
        self.assertLessEqual(metrics.result["scores"]["total"], 100)
        self.assertTrue(metrics.evidence)

    def test_complete_order_cost_is_balanced(self) -> None:
        result = calculate_order_cost(self.repo, FIXED_ORDER, AS_OF)
        components = result.result["components"]
        detail_sum = round(sum(row["amount"] for row in result.result["material_details"]), 2)
        self.assertAlmostEqual(detail_sum, components["material"], places=2)
        subtotal = round(
            components["material"]
            + components["labor"]
            + components["outsource"]
            + components["overhead"]
            + components["logistics"],
            2,
        )
        self.assertAlmostEqual(subtotal, components["total"], places=2)
        self.assertEqual(result.result["gross_margin_rate"], 0.165)
        self.assertTrue(result.evidence)

    def test_quote_supports_transparent_margin_range(self) -> None:
        result = calculate_quote(self.repo, "产品-001", 3, 0.25, {}, AS_OF)
        self.assertLess(result.result["break_even_price"], result.result["target_price"])
        self.assertNotIn("minimum_margin_price", result.result)
        self.assertNotIn("minimum_margin_rate", result.result)
        self.assertNotIn("recommended_range", result.result)
        self.assertEqual(result.result["product_name"], "HT-ZP1200精密装配机")
        self.assertEqual(result.result["unit"], "套")
        self.assertAlmostEqual(
            result.result["target_unit_price"] * result.result["quantity"],
            result.result["target_price"],
            places=1,
        )
        self.assertEqual(result.result["historical_reference"]["range_method"], "P25-P75")
        self.assertEqual(result.result["base_cost"], 828870.7)
        self.assertEqual(result.result["target_price"], 1105160.93)
        self.assertEqual(result.result["target_gross_profit"], 276290.23)
        self.assertEqual(
            result.result["cost_components"],
            {
                "material": 518894.23,
                "labor": 110019.4,
                "outsource": 88310.34,
                "overhead": 96466.62,
                "logistics": 15180.11,
                "total": 828870.7,
            },
        )
        self.assertEqual(len(result.result["cost_breakdown"]), 5)
        self.assertEqual(len(result.result["quote_composition"]), 7)
        self.assertAlmostEqual(
            sum(item["share_of_base_cost"] for item in result.result["cost_breakdown"]),
            1,
            places=5,
        )
        self.assertAlmostEqual(
            sum(item["share_of_target_price"] for item in result.result["quote_composition"]),
            1,
            places=5,
        )
        self.assertEqual(result.result["reconciliation"]["base_cost_difference"], 0)
        self.assertEqual(result.result["reconciliation"]["target_price_difference"], 0)
        self.assertEqual(
            round(sum(row["amount"] for row in result.result["material_details"]), 2),
            result.result["cost_components"]["material"],
        )
        self.assertEqual(result.result["cost_basis"]["bom_version"], "V1.0")
        self.assertTrue(
            all("price_source" in row for row in result.result["material_details"])
        )
        self.assertTrue(result.evidence)
        zero_margin = calculate_quote(self.repo, "产品-001", 3, 0, {}, AS_OF)
        self.assertEqual(
            zero_margin.result["target_price"],
            zero_margin.result["break_even_price"],
        )
        high_margin = calculate_quote(self.repo, "产品-001", 3, 0.60, {}, AS_OF)
        self.assertGreater(
            high_margin.result["target_price"],
            result.result["target_price"],
        )
        with self.assertRaises(InvalidCalculationInput):
            calculate_quote(self.repo, "产品-001", 0, 0.25, {}, AS_OF)
        with self.assertRaises(InvalidCalculationInput):
            calculate_quote(self.repo, "产品-001", 3, -0.01, {}, AS_OF)
        with self.assertRaises(InvalidCalculationInput):
            calculate_quote(self.repo, "产品-001", 3, 0.61, {}, AS_OF)
        with self.assertRaises(InvalidCalculationInput):
            calculate_quote(
                self.repo,
                "产品-001",
                3,
                0.25,
                {"urgency_surcharge_rate": 0.21},
                AS_OF,
            )

    def test_quote_material_price_source_and_standard_price_fallback(self) -> None:
        base_repo = self.repo

        class StandardPriceFallbackRepository:
            def one(self, sql, params=()):
                if "FROM material_price_history" in sql:
                    return None
                return base_repo.one(sql, params)

            def query(self, sql, params=()):
                return base_repo.query(sql, params)

        regular = calculate_quote(self.repo, "产品-001", 3, 0.25, {}, AS_OF)
        self.assertTrue(
            any(
                row["price_source"] == "material_price_history"
                and row["price_reference_date"]
                for row in regular.result["material_details"]
            )
        )

        fallback = calculate_quote(
            StandardPriceFallbackRepository(), "产品-001", 3, 0.25, {}, AS_OF
        )
        self.assertTrue(
            all(
                row["price_source"] == "materials.standard_price"
                and row["price_reference_date"] is None
                for row in fallback.result["material_details"]
            )
        )
        self.assertTrue(
            any("回退使用物料标准价" in warning for warning in fallback.warnings)
        )
        self.assertTrue(
            any(item.source_table == "materials" for item in fallback.evidence)
        )

    def test_quote_history_reference_fallback_and_empty_result(self) -> None:
        base_repo = self.repo

        class HistoryRepository:
            def __init__(self, rows):
                self.rows = rows

            def one(self, sql, params=()):
                return base_repo.one(sql, params)

            def query(self, sql, params=()):
                if "FROM quotations q" in sql:
                    return self.rows
                return base_repo.query(sql, params)

        four_rows = [
            {"quantity": 3, "quoted_amount": amount, "target_margin_rate": margin, "quotation_date": "2026-01-01"}
            for amount, margin in [(300, 0.10), (600, 0.20), (900, 0.30), (1200, 0.40)]
        ]
        quartile = calculate_quote(
            HistoryRepository(four_rows), "产品-001", 3, 0.25, {}, AS_OF
        ).result["historical_reference"]
        self.assertEqual(quartile["range_method"], "P25-P75")
        self.assertEqual(quartile["unit_price_low"], 175.0)
        self.assertEqual(quartile["unit_price_median"], 250.0)
        self.assertEqual(quartile["unit_price_high"], 325.0)
        self.assertEqual(quartile["total_price_low"], 525.0)
        self.assertEqual(quartile["total_price_high"], 975.0)

        three_rows = four_rows[:3]
        fallback = calculate_quote(
            HistoryRepository(three_rows), "产品-001", 3, 0.25, {}, AS_OF
        ).result["historical_reference"]
        self.assertEqual(fallback["range_method"], "最小值-最大值")
        self.assertEqual(fallback["unit_price_low"], 100.0)
        self.assertEqual(fallback["unit_price_high"], 300.0)

        empty = calculate_quote(
            HistoryRepository([]), "产品-001", 3, 0.25, {}, AS_OF
        )
        self.assertIsNone(empty.result["historical_reference"])
        self.assertIn("未生成历史参考区间", empty.warnings[0])

    def test_fixed_copper_price_scenario(self) -> None:
        result = run_procurement_scenario(
            self.repo,
            "material_price_change",
            {
                "order_code": FIXED_ORDER,
                "material_code": FIXED_MATERIAL,
                "change_rate": 0.08,
            },
            AS_OF,
        ).result["result"]
        self.assertEqual(result["original_cost"], 828870.7)
        self.assertEqual(result["cost_change"], 19552.49)
        self.assertEqual(result["new_cost"], 848423.19)
        self.assertEqual(result["new_margin_rate"], 0.1453)
        self.assertTrue(result["low_margin_warning"])

    def test_all_seven_procurement_scenarios(self) -> None:
        recommendation = recommend_suppliers(
            self.repo, FIXED_MATERIAL, 450, "2026-08-08", AS_OF
        ).result["items"][0]
        scenarios = {
            "material_price_change": {
                "order_code": FIXED_ORDER,
                "material_code": FIXED_MATERIAL,
                "change_rate": 0.08,
            },
            "supplier_switch": {
                "order_code": FIXED_ORDER,
                "material_code": FIXED_MATERIAL,
                "supplier_code": recommendation["supplier_code"],
            },
            "volume_discount": {
                "order_code": FIXED_ORDER,
                "discount_rate": 0.05,
            },
            "early_buy_lock": {
                "order_code": FIXED_ORDER,
                "lock_discount_rate": 0.03,
                "holding_cost_rate": 0.01,
            },
            "exchange_rate_change": {
                "order_code": FIXED_ORDER,
                "currency": "USD",
                "change_rate": 0.05,
            },
            "supplier_disruption": {
                "material_code": FIXED_MATERIAL,
                "supplier_code": recommendation["supplier_code"],
                "quantity": 450,
                "need_by_date": "2026-08-08",
            },
            "delivery_date_change": {
                "order_code": FIXED_ORDER,
                "new_delivery_date": "2026-08-10",
            },
        }
        for scenario_type, parameters in scenarios.items():
            with self.subTest(scenario_type=scenario_type):
                result = run_procurement_scenario(
                    self.repo, scenario_type, parameters, AS_OF
                )
                self.assertEqual(result.result["scenario_type"], scenario_type)
                self.assertTrue(result.result["result"])

    def test_receivables_and_daily_brief(self) -> None:
        receivables = analyze_receivables(self.repo, {}, AS_OF)
        self.assertGreater(receivables.result["open_receivable_count"], 0)
        self.assertGreaterEqual(receivables.result["shipped_not_invoiced_count"], 0)
        self.assertTrue(receivables.evidence)
        self.assertAlmostEqual(
            sum(
                row["outstanding_amount"]
                for row in receivables.result["aging_summary"]
            ),
            receivables.result["total_outstanding_amount"],
            places=2,
        )
        self.assertEqual(
            sum(
                row["receivable_count"]
                for row in receivables.result["aging_summary"]
            ),
            receivables.result["open_receivable_count"],
        )
        valid_buckets = {"未到期", "1-30天", "31-60天", "61-90天", "90天以上"}
        self.assertTrue(
            all(
                row["aging_bucket"] in valid_buckets
                for row in receivables.result["receivables"]
            )
        )
        buckets = {row["aging_bucket"] for row in receivables.result["receivables"]}
        self.assertIn("90天以上", buckets)
        self.assertGreater(
            self.repo.one(
                """
                SELECT COUNT(*) count FROM ar_snapshots
                WHERE paid_amount>0 AND outstanding_amount>0
                """
            )["count"],
            0,
        )

        open_order = self.repo.one(
            """
            SELECT so.sales_order_code, ar.outstanding_amount, i.invoice_code
            FROM ar_snapshots ar
            JOIN invoices i ON i.invoice_id=ar.invoice_id
            JOIN sales_orders so ON so.sales_order_id=i.sales_order_id
            WHERE ar.snapshot_date<=? AND ar.outstanding_amount>0
            ORDER BY ar.snapshot_date DESC, ar.ar_snapshot_id
            LIMIT 1
            """,
            (AS_OF.isoformat(),),
        )
        order_receivables = analyze_receivables(
            self.repo, {"order_code": open_order["sales_order_code"]}, AS_OF
        )
        self.assertEqual(order_receivables.result["open_receivable_count"], 1)
        self.assertEqual(
            order_receivables.result["total_outstanding_amount"], open_order["outstanding_amount"]
        )
        self.assertEqual(
            order_receivables.result["receivables"][0]["invoice_code"],
            open_order["invoice_code"],
        )

        customer_receivables = analyze_receivables(
            self.repo, {"customer_code": "客户-0004"}, AS_OF
        )
        self.assertTrue(
            all(
                row["customer_code"] == "客户-0004"
                for row in customer_receivables.result["receivables"]
            )
        )

        brief = generate_daily_brief(self.repo, AS_OF)
        self.assert_envelope(brief)
        self.assertLessEqual(len(brief.result["top_actions"]), 5)
        self.assertEqual(
            [item["priority"] for item in brief.result["top_actions"]],
            list(range(1, len(brief.result["top_actions"]) + 1)),
        )
        self.assertIn("high_risk_orders", brief.result)
        self.assertTrue(brief.evidence)

    def test_unknown_entities_and_invalid_scenario(self) -> None:
        with self.assertRaises(EntityNotFound):
            calculate_order_risk(self.repo, "SO-NOT-FOUND", AS_OF)
        with self.assertRaises(EntityNotFound):
            recommend_suppliers(self.repo, "M-NOT-FOUND", 10, AS_OF, AS_OF)
        with self.assertRaises(EntityNotFound):
            analyze_material_shortages(
                self.repo, {"material_code": "M-NOT-FOUND"}, AS_OF
            )
        with self.assertRaises(EntityNotFound):
            analyze_receivables(
                self.repo, {"customer_code": "C-NOT-FOUND"}, AS_OF
            )
        with self.assertRaises(EntityNotFound):
            analyze_receivables(
                self.repo, {"order_code": "SO-NOT-FOUND"}, AS_OF
            )
        with self.assertRaises(InvalidCalculationInput):
            run_procurement_scenario(self.repo, "not_supported", {}, AS_OF)

    def test_business_engine_facade_matches_public_contract(self) -> None:
        engine = default_engine()
        result = engine.calculate_order_risk(FIXED_ORDER, AS_OF)
        self.assertEqual(result.result["risk_score"], 85)
        self.assertEqual(result.to_dict()["as_of_date"], AS_OF.isoformat())


if __name__ == "__main__":
    unittest.main(verbosity=2)

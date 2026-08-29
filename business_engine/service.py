from __future__ import annotations

from datetime import date
from typing import Any

from .core import Repository, resolve_as_of
from .costing import calculate_order_cost, calculate_quote, run_procurement_scenario
from .finance import analyze_receivables, generate_business_report, generate_daily_brief
from .fulfillment import (
    _allocation_snapshot,
    analyze_material_shortages,
    analyze_order_fulfillment,
    calculate_order_risk,
    evaluate_production_progress,
    evaluate_purchase_delays,
)
from .procurement import (
    calculate_supplier_metrics,
    detect_purchase_price_anomalies,
    recommend_suppliers,
)


class BusinessEngine:
    """持有只读Repository的稳定业务门面，供后续FastAPI直接包装。"""

    def __init__(self, repository: Repository):
        self.repository = repository

    def analyze_order_fulfillment(self, order_code: str, as_of_date=None):
        return analyze_order_fulfillment(self.repository, order_code, as_of_date)

    def analyze_material_shortages(self, filters=None, as_of_date=None):
        return analyze_material_shortages(self.repository, filters, as_of_date)

    def evaluate_purchase_delays(self, filters=None, as_of_date=None):
        return evaluate_purchase_delays(self.repository, filters, as_of_date)

    def evaluate_production_progress(self, order_code: str, as_of_date=None):
        return evaluate_production_progress(self.repository, order_code, as_of_date)

    def calculate_order_risk(self, order_code: str, as_of_date=None):
        return calculate_order_risk(self.repository, order_code, as_of_date)

    def calculate_order_risks(self, order_codes: list[str], as_of_date=None):
        """批量计算订单风险，并复用整批订单共有的供应数据快照。"""
        as_of = resolve_as_of(as_of_date)
        allocation_cache = _allocation_snapshot(self.repository, as_of)
        purchase_delay_items = evaluate_purchase_delays(
            self.repository, {}, as_of
        ).result["items"]
        return [
            calculate_order_risk(
                self.repository,
                order_code,
                as_of,
                _allocation_cache=allocation_cache,
                _purchase_delay_items=purchase_delay_items,
            )
            for order_code in order_codes
        ]

    def detect_purchase_price_anomalies(self, filters=None, as_of_date=None):
        return detect_purchase_price_anomalies(self.repository, filters, as_of_date)

    def calculate_supplier_metrics(
        self, supplier_code: str, period: int = 12, as_of_date=None
    ):
        return calculate_supplier_metrics(
            self.repository, supplier_code, period, as_of_date
        )

    def recommend_suppliers(
        self, material_code: str, quantity: float, need_by_date: str | date,
        as_of_date=None,
    ):
        return recommend_suppliers(
            self.repository, material_code, quantity, need_by_date, as_of_date
        )

    def calculate_order_cost(self, order_code: str, as_of_date=None):
        return calculate_order_cost(self.repository, order_code, as_of_date)

    def calculate_quote(
        self, product_code: str, quantity: float, target_margin: float = 0.25,
        options: dict[str, Any] | None = None, as_of_date=None,
    ):
        return calculate_quote(
            self.repository,
            product_code,
            quantity,
            target_margin,
            options,
            as_of_date,
        )

    def run_procurement_scenario(
        self, scenario_type: str, parameters: dict[str, Any], as_of_date=None
    ):
        return run_procurement_scenario(
            self.repository, scenario_type, parameters, as_of_date
        )

    def analyze_receivables(self, filters=None, as_of_date=None):
        return analyze_receivables(self.repository, filters, as_of_date)

    def generate_daily_brief(self, as_of_date=None):
        return generate_daily_brief(self.repository, as_of_date)

    def generate_business_report(self, report_type="daily", as_of_date=None):
        return generate_business_report(self.repository, report_type, as_of_date)

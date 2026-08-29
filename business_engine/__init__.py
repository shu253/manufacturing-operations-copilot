from pathlib import Path

from .core import (
    BusinessEngineError,
    CalculationEnvelope,
    DataQualityWarning,
    EntityNotFound,
    InvalidCalculationInput,
    SQLiteRepository,
)
from .costing import calculate_order_cost, calculate_quote, run_procurement_scenario
from .finance import analyze_receivables, generate_business_report, generate_daily_brief
from .fulfillment import (
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
from .service import BusinessEngine


DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data" / "huadong_jinggong_demo.sqlite3"


def default_repository() -> SQLiteRepository:
    return SQLiteRepository(DEFAULT_DATABASE)


def default_engine() -> BusinessEngine:
    return BusinessEngine(default_repository())


__all__ = [
    "CalculationEnvelope",
    "BusinessEngineError",
    "DataQualityWarning",
    "EntityNotFound",
    "InvalidCalculationInput",
    "SQLiteRepository",
    "BusinessEngine",
    "default_repository",
    "default_engine",
    "analyze_order_fulfillment",
    "analyze_material_shortages",
    "evaluate_purchase_delays",
    "evaluate_production_progress",
    "calculate_order_risk",
    "detect_purchase_price_anomalies",
    "calculate_supplier_metrics",
    "recommend_suppliers",
    "calculate_order_cost",
    "calculate_quote",
    "run_procurement_scenario",
    "analyze_receivables",
    "generate_daily_brief",
    "generate_business_report",
]

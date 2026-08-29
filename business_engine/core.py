from __future__ import annotations

import sqlite3
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union

from pydantic import BaseModel, Field


# Used only when a caller does not explicitly choose a business date.
# Fixed acceptance tests continue to pass their own historical date.
DEFAULT_AS_OF = date.today()
FORMULA_VERSION = "3.0.0"
MONEY = Decimal("0.01")
QUANTITY = Decimal("0.0001")


class BusinessEngineError(Exception):
    code = "BUSINESS_ENGINE_ERROR"


class EntityNotFound(BusinessEngineError):
    code = "ENTITY_NOT_FOUND"


class InvalidCalculationInput(BusinessEngineError):
    code = "INVALID_CALCULATION_INPUT"


class DataQualityWarning(Warning):
    code = "DATA_QUALITY_WARNING"


class Evidence(BaseModel):
    source_table: str
    record_code: str
    description: str
    value: Optional[Any] = None


class CalculationEnvelope(BaseModel):
    calculation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    as_of_date: date
    formula_version: str = FORMULA_VERSION
    result: Union[Dict[str, Any], List[Any]]
    evidence: List[Evidence] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Repository(Protocol):
    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...
    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None: ...


class SQLiteRepository:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{Path(self.database_path).resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def table_exists(self, name: str) -> bool:
        return self.one(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ) is not None


def D(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def as_money(value: Any) -> Decimal:
    return D(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def as_qty(value: Any) -> Decimal:
    return D(value).quantize(QUANTITY, rounding=ROUND_HALF_UP)


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(high, max(low, value))


def parse_date(value: str | date | None) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def resolve_as_of(value: str | date | None) -> date:
    parsed = parse_date(value)
    return parsed or DEFAULT_AS_OF

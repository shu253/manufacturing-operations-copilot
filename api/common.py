from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, Iterable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from business_engine import CalculationEnvelope


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def audit(request: Request, operation: str, read_only: bool = True) -> Dict[str, Any]:
    return {
        "operation": operation,
        "actor": request.headers.get("X-Actor", "anonymous"),
        "request_path": request.url.path,
        "read_only": read_only,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def data_as_of_date(request: Request) -> Optional[str]:
    """Return the latest completed operational snapshot date."""
    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        return None
    row = repository.one(
        "SELECT MAX(snapshot_date) AS data_as_of_date FROM inventory_balances"
    )
    return row["data_as_of_date"] if row else None


def success(
    request: Request,
    data: Any,
    operation: str,
    *,
    sources: Optional[Iterable[Dict[str, Any]]] = None,
    warnings: Optional[Iterable[str]] = None,
    calculation_id: Optional[str] = None,
    formula_version: Optional[str] = None,
    as_of_date: Optional[str] = None,
    read_only: bool = True,
) -> Dict[str, Any]:
    latest_data_date = data_as_of_date(request)
    response_warnings = list(warnings or [])
    if (
        as_of_date
        and latest_data_date
        and date.fromisoformat(latest_data_date) < date.fromisoformat(as_of_date)
    ):
        response_warnings.append(
            f"当前分析基于截至{latest_data_date}的业务数据，"
            f"可能不包含{latest_data_date}之后发生的业务变化。"
        )
    return {
        "success": True,
        "request_id": request_id(request),
        "data": data,
        "meta": {
            "calculation_id": calculation_id,
            "as_of_date": as_of_date,
            "data_as_of_date": latest_data_date,
            "formula_version": formula_version,
            "sources": list(sources or []),
            "warnings": list(dict.fromkeys(response_warnings)),
            "audit": audit(request, operation, read_only),
        },
    }


def from_calculation(
    request: Request,
    envelope: CalculationEnvelope,
    operation: str,
) -> Dict[str, Any]:
    payload = envelope.to_dict()
    return success(
        request,
        payload["result"],
        operation,
        sources=payload["evidence"],
        warnings=payload["warnings"],
        calculation_id=payload["calculation_id"],
        formula_version=payload["formula_version"],
        as_of_date=payload["as_of_date"],
    )


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "request_id": request_id(request),
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "meta": {
                "sources": [],
                "warnings": [],
                "audit": audit(request, "error", True),
            },
        },
    )

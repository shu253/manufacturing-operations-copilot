"""Dify Code 节点：合并并裁剪受控工具结果。"""

import json


def _parse(value):
    if value in (None, "", "null"):
        return None
    parsed = value
    if not isinstance(value, (dict, list)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {"success": False, "raw": str(value), "meta": {"warnings": ["工具结果不是合法JSON"]}}

    # Dify 自定义工具的 json 输出可能显示为 Array[Object]，即使 HTTP
    # 响应本身只有一个对象。自动解开单元素数组，兼容 Object 和
    # Array[Object] 两种节点输出类型。
    while isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {
            "success": False,
            "data": {"items": parsed},
            "meta": {"warnings": ["工具返回了多元素数组，无法识别统一响应信封"]},
        }
    else:
        return {"success": False, "raw": str(value), "meta": {"warnings": ["工具结果不是合法JSON"]}}


def _trim_lists(value, limit=5):
    if isinstance(value, list):
        return [_trim_lists(item, limit) for item in value[:limit]]
    if isinstance(value, dict):
        return {key: _trim_lists(item, limit) for key, item in value.items()}
    return value


def _compact_tool_result(parsed):
    """删除只供审计存储使用、但不需要重复发给LLM的大型来源明细。"""
    compact = {
        "success": parsed.get("success", False),
        "tool_name": parsed.get("tool_name"),
        "data": _trim_lists(parsed.get("data") or {}, 5),
    }
    meta = parsed.get("meta") or {}
    compact["meta"] = {
        key: meta.get(key)
        for key in (
            "as_of_date",
            "data_as_of_date",
            "formula_version",
            "calculation_id",
            "warnings",
        )
        if meta.get(key) not in (None, "", [])
    }
    source_summaries = []
    seen_sources = set()
    for source in meta.get("sources") or []:
        summary = {
            key: source.get(key)
            for key in ("source_name", "record_code")
            if source.get(key) not in (None, "")
        }
        marker = (summary.get("source_name"), summary.get("record_code"))
        if summary and marker not in seen_sources:
            seen_sources.add(marker)
            source_summaries.append(summary)
        if len(source_summaries) >= 8:
            break
    if source_summaries:
        compact["meta"]["sources"] = source_summaries
    return compact


def main(
    risk_result=None,
    fulfillment_result=None,
    shortage_result=None,
    purchase_result=None,
    production_result=None,
    cost_result=None,
    scenario_result=None,
    supplier_result=None,
):
    named_results = {
        "order_risk": risk_result,
        "order_fulfillment": fulfillment_result,
        "material_shortage": shortage_result,
        "purchase_delay": purchase_result,
        "production_progress": production_result,
        "order_cost": cost_result,
        "scenario": scenario_result,
        "supplier_recommendation": supplier_result,
    }
    evidence = {}
    source_refs = []
    warnings = []
    failed_tools = []

    for name, raw in named_results.items():
        parsed = _parse(raw)
        if parsed is None:
            continue
        parsed = _trim_lists(parsed)
        evidence[name] = _compact_tool_result(parsed)
        if not parsed.get("success", False):
            failed_tools.append(name)
        meta = parsed.get("meta") or {}
        calculation_id = meta.get("calculation_id")
        if calculation_id:
            source_refs.append(calculation_id)
        for source in meta.get("sources") or []:
            record_code = source.get("record_code")
            if record_code:
                source_refs.append(record_code)
        warnings.extend(meta.get("warnings") or [])

    source_refs = list(dict.fromkeys(str(item) for item in source_refs if item))
    warnings = list(dict.fromkeys(str(item) for item in warnings if item))
    return {
        "evidence_json": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        "source_refs": source_refs,
        "warnings": warnings,
        "tool_count": len(evidence),
        "failed_tools": failed_tools,
        "decision_ready": len(evidence) > 0 and not failed_tools,
    }

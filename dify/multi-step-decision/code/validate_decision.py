"""Dify Code 节点：验证最终 JSON、来源引用和指标数字。"""

import json


def _parse(value):
    if isinstance(value, dict):
        return value
    return json.loads(value)


def _all_scalars(value):
    output = set()
    if isinstance(value, dict):
        for item in value.values():
            output.update(_all_scalars(item))
    elif isinstance(value, list):
        for item in value:
            output.update(_all_scalars(item))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        output.add(round(float(value), 8))
    return output


def _text_list(values, limit=3):
    return "；".join(str(item).strip() for item in (values or [])[:limit] if str(item).strip())


def _format_metric(metric):
    value = metric.get("value")
    unit = metric.get("unit") or ""
    if isinstance(value, float) and unit == "元":
        value_text = f"{value:,.2f}"
    elif isinstance(value, int) and unit == "元":
        value_text = f"{value:,}"
    else:
        value_text = str(value)
    return f"- **{metric.get('label') or metric.get('code') or '指标'}：** {value_text}{unit}"


def _render_markdown(decision):
    entities = decision.get("entities") or {}
    object_code = (
        entities.get("order_code")
        or entities.get("sales_order_code")
        or entities.get("purchase_order_code")
        or entities.get("material_code")
        or "本次事项"
    )
    lines = [f"## 多步骤经营决策分析｜{object_code}", ""]

    summary = decision.get("executive_summary") or decision.get("answer")
    if summary:
        lines.extend(["### 一、管理结论", str(summary).strip(), ""])

    metrics = decision.get("metrics") or []
    if metrics:
        lines.append("### 二、核心指标")
        lines.extend(_format_metric(item) for item in metrics[:6])
        lines.append("")

    chain = decision.get("evidence_chain") or []
    if chain:
        lines.append("### 三、风险证据链")
        for index, item in enumerate(chain[:5], 1):
            finding = str(item.get("finding") or "").strip()
            impact = str(item.get("impact") or "").strip()
            line = f"{index}. **{finding}**"
            if impact:
                line += f" 影响：{impact}"
            lines.append(line)
        lines.append("")

    options = decision.get("options") or []
    if options:
        lines.append("### 四、方案比较")
        for item in options[:3]:
            lines.append(f"**{item.get('name') or '备选方案'}**")
            benefits = _text_list(item.get("benefits"), 2)
            risks = _text_list(item.get("risks"), 2)
            prerequisites = _text_list(item.get("prerequisites"), 2)
            if benefits:
                lines.append(f"- 收益：{benefits}")
            if risks:
                lines.append(f"- 风险：{risks}")
            if prerequisites:
                lines.append(f"- 前置条件：{prerequisites}")
        lines.append("")

    recommendation = decision.get("recommendation") or {}
    if recommendation:
        lines.extend(
            [
                "### 五、推荐方案",
                f"**{recommendation.get('option') or '建议方案'}**",
                str(recommendation.get("reason") or "").strip(),
            ]
        )
        approvals = recommendation.get("approval_required") or []
        if approvals:
            lines.append("**需要管理层确认：**")
            lines.extend(f"- {item}" for item in approvals[:4])
        lines.append("")

    actions = decision.get("next_actions") or []
    if actions:
        lines.append("### 六、行动清单")
        for item in actions[:6]:
            prefix = " · ".join(
                str(value)
                for value in (
                    item.get("priority"),
                    item.get("timeframe"),
                    item.get("owner_role"),
                )
                if value
            )
            lines.append(f"- **{prefix}：** {item.get('action') or ''}")
        lines.append("")

    warnings = decision.get("warnings") or []
    if warnings:
        lines.append("### 数据提醒")
        lines.extend(f"- {item}" for item in warnings[:5])
        lines.append("")

    questions = decision.get("suggested_questions") or []
    if questions:
        lines.append("### 可继续追问")
        lines.extend(f"- {item}" for item in questions[:3])

    return "\n".join(lines).strip()


def main(decision_json, evidence_json):
    try:
        decision = _parse(decision_json)
        evidence = _parse(evidence_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "final_json": "",
            "final_text": "本次决策分析输出格式异常，请重新运行。",
            "errors": [f"模型输出或工具证据不是合法JSON: {exc}"],
        }

    errors = []
    required = {"answer", "intent", "evidence_chain", "recommendation", "metrics", "next_actions", "source_refs", "warnings"}
    missing = sorted(required.difference(decision))
    if missing:
        errors.append("缺少字段: " + ", ".join(missing))

    evidence_numbers = _all_scalars(evidence)
    for index, metric in enumerate(decision.get("metrics") or [], 1):
        value = metric.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if round(float(value), 8) not in evidence_numbers:
                errors.append(f"metrics[{index}]的数值{value}在工具证据中不存在")
        if not metric.get("source_ref"):
            errors.append(f"metrics[{index}]缺少source_ref")

    for index, item in enumerate(decision.get("evidence_chain") or [], 1):
        if not item.get("source_ref"):
            errors.append(f"evidence_chain[{index}]缺少source_ref")

    if errors:
        fallback = {
            "answer": "本次决策分析未通过业务数字与来源校验，请重新运行或查看数据依据。",
            "intent": decision.get("intent", "multi_step_decision"),
            "entities": decision.get("entities", {}),
            "evidence_chain": [],
            "options": [],
            "recommendation": {},
            "metrics": [],
            "risks": [],
            "next_actions": [],
            "source_refs": [],
            "warnings": errors,
            "suggested_questions": ["请重新执行多步骤决策分析。"],
            "visualization": None,
        }
        return {
            "passed": False,
            "final_json": json.dumps(fallback, ensure_ascii=False),
            "final_text": fallback["answer"] + "\n\n" + "；".join(errors),
            "errors": errors,
        }

    return {
        "passed": True,
        "final_json": json.dumps(decision, ensure_ascii=False),
        "final_text": _render_markdown(decision),
        "errors": [],
    }

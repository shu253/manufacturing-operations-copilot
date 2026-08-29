"""Dify Code节点：校验可读中文正文中的数字是否来自工具证据。"""

import json
import re
from decimal import Decimal, InvalidOperation


NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?")
FORBIDDEN_MARKDOWN = ("```", "**", "###", "__")


def _parse_evidence(value):
    if isinstance(value, dict):
        return value
    return json.loads(value)


def _normalize_number(token):
    raw = token.replace(",", "").rstrip("%")
    try:
        return str(Decimal(raw).normalize())
    except InvalidOperation:
        return raw


def _number_tokens(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return {_normalize_number(item) for item in NUMBER_PATTERN.findall(text)}


def main(decision_text, evidence_json):
    answer = str(decision_text or "").strip()
    errors = []

    try:
        evidence = _parse_evidence(evidence_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "final_text": "本次决策分析的数据依据无法解析，请重新运行。",
            "errors": [f"业务工具证据不是合法JSON: {exc}"],
        }

    if not answer:
        errors.append("模型未返回分析正文")

    if any(marker in answer for marker in FORBIDDEN_MARKDOWN):
        errors.append("回答包含不允许展示的Markdown或代码标记")

    if answer.startswith("{") or '"answer"' in answer:
        errors.append("回答仍为原始JSON，没有生成可读中文正文")

    required_sections = (
        "一、决策结论",
        "二、分析对象与查询范围",
        "三、风险构成",
        "四、跨环节证据链",
        "五、备选方案",
        "六、推荐处理顺序",
        "七、需要管理层确认",
        "八、计算与数据依据",
    )
    missing_sections = [item for item in required_sections if item not in answer]
    if missing_sections:
        errors.append("缺少回答章节: " + "、".join(missing_sections))

    evidence_numbers = _number_tokens(evidence)
    answer_numbers = _number_tokens(answer)
    unsupported = sorted(answer_numbers.difference(evidence_numbers))
    if unsupported:
        errors.append("回答包含工具证据中不存在的数字: " + "、".join(unsupported[:20]))

    if errors:
        return {
            "passed": False,
            "final_text": "本次多步骤决策分析未通过业务数字与格式校验，请重新运行。\n\n校验提示：" + "；".join(errors),
            "errors": errors,
        }

    return {
        "passed": True,
        "final_text": answer,
        "errors": [],
    }


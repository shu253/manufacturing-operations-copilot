from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "dify" / "multi-step-decision" / "code" / "validate_readable_answer.py"
SPEC = importlib.util.spec_from_file_location("validate_readable_answer", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ReadableDecisionValidatorTestCase(unittest.TestCase):
    def _answer(self, metric="85"):
        sections = (
            "一、决策结论",
            "二、分析对象与查询范围",
            "三、风险构成",
            "四、跨环节证据链",
            "五、备选方案",
            "六、推荐处理顺序",
            "七、需要管理层确认",
            "八、计算与数据依据",
        )
        return "\n".join([sections[0], f"订单风险分为{metric}分。", *sections[1:]])

    def test_accepts_readable_grounded_answer(self):
        output = MODULE.main(
            self._answer(),
            json.dumps({"order_risk": {"data": {"risk_score": 85}}}),
        )
        self.assertTrue(output["passed"])

    def test_blocks_unsupported_number(self):
        output = MODULE.main(
            self._answer("99"),
            json.dumps({"order_risk": {"data": {"risk_score": 85}}}),
        )
        self.assertFalse(output["passed"])
        self.assertIn("99", " ".join(output["errors"]))


if __name__ == "__main__":
    unittest.main()

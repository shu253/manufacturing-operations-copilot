from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "dify" / "multi-step-decision"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载测试模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MultiStepWorkflowAssetTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.normalizer = load_module(
            "normalize_evidence",
            ASSET_ROOT / "code" / "normalize_evidence.py",
        )
        cls.validator = load_module(
            "validate_decision",
            ASSET_ROOT / "code" / "validate_decision.py",
        )

    def test_normalizer_merges_sources_and_warnings(self) -> None:
        risk = {
            "success": True,
            "tool_name": "get_order_risk",
            "data": {"risk_score": 85, "items": list(range(20))},
            "meta": {
                "calculation_id": "calc-risk-1",
                "sources": [
                    {"source_table": "sales_orders", "record_code": "销售-20260718-01"}
                ],
                "warnings": ["数据截至2026-08-05"],
            },
        }
        output = self.normalizer.main(risk_result=json.dumps(risk, ensure_ascii=False))
        evidence = json.loads(output["evidence_json"])

        self.assertTrue(output["decision_ready"])
        self.assertEqual(output["tool_count"], 1)
        self.assertEqual(len(evidence["order_risk"]["data"]["items"]), 5)
        self.assertEqual(output["source_refs"], ["calc-risk-1", "销售-20260718-01"])
        self.assertEqual(output["warnings"], ["数据截至2026-08-05"])

    def test_normalizer_accepts_dify_single_object_array(self) -> None:
        risk = [{
            "success": True,
            "tool_name": "get_order_risk",
            "data": {"risk_score": 85},
            "meta": {"calculation_id": "calc-array-1", "sources": [], "warnings": []},
        }]
        output = self.normalizer.main(risk_result=risk)
        self.assertTrue(output["decision_ready"])
        self.assertEqual(output["source_refs"], ["calc-array-1"])

    def test_validator_accepts_grounded_metrics(self) -> None:
        evidence = {
            "order_risk": {
                "success": True,
                "data": {"risk_score": 85},
            }
        }
        decision = {
            "answer": "订单风险较高。",
            "intent": "order_risk_decision",
            "entities": {"order_code": "销售-20260718-01"},
            "evidence_chain": [
                {"step": 1, "finding": "高风险", "impact": "需处理", "source_ref": "calc-1"}
            ],
            "options": [],
            "recommendation": {"option": "优先补料"},
            "metrics": [
                {"code": "risk_score", "label": "风险分", "value": 85, "unit": "分", "source_ref": "calc-1"}
            ],
            "risks": [],
            "next_actions": [],
            "source_refs": ["calc-1"],
            "warnings": [],
            "suggested_questions": [],
            "visualization": "comparison",
        }
        output = self.validator.main(
            json.dumps(decision, ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False),
        )
        self.assertTrue(output["passed"])
        self.assertEqual(json.loads(output["final_json"])["metrics"][0]["value"], 85)
        self.assertIn("多步骤经营决策分析", output["final_text"])
        self.assertIn("风险分", output["final_text"])

    def test_validator_blocks_unsupported_metric(self) -> None:
        decision = {
            "answer": "模型编造了一个金额。",
            "intent": "cost_scenario",
            "evidence_chain": [],
            "recommendation": {},
            "metrics": [
                {"code": "cost_change", "label": "成本增加", "value": 99999, "unit": "元", "source_ref": "calc-1"}
            ],
            "next_actions": [],
            "source_refs": ["calc-1"],
            "warnings": [],
        }
        output = self.validator.main(
            json.dumps(decision, ensure_ascii=False),
            json.dumps({"scenario": {"data": {"cost_change": 14596.47}}}, ensure_ascii=False),
        )
        self.assertFalse(output["passed"])
        self.assertIn("99999", " ".join(output["errors"]))
        self.assertIn("未通过", output["final_text"])


if __name__ == "__main__":
    unittest.main()

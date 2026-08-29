from __future__ import annotations

import json
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records: list[dict[str, str]] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"test": self.getDescription(test), "status": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append(
            {
                "test": self.getDescription(test),
                "status": "failed",
                "message": self._exc_info_to_string(err, test),
            }
        )

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append(
            {
                "test": self.getDescription(test),
                "status": "error",
                "message": self._exc_info_to_string(err, test),
            }
        )


def main() -> int:
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "tests.test_business_engine"
    )
    runner = unittest.TextTestRunner(
        verbosity=2,
        resultclass=RecordingResult,
    )
    result: RecordingResult = runner.run(suite)
    payload = {
        "report_name": "阶段三业务计算引擎自动测试报告",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python_version": sys.version.split()[0],
        "formula_version": "3.0.0",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "tests_run": result.testsRun,
        "passed": len([x for x in result.records if x["status"] == "passed"]),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "successful": result.wasSuccessful(),
        "records": result.records,
    }
    output = ROOT / "data" / "business_engine_test_report.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n测试报告: {output}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

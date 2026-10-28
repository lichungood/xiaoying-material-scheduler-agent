"""Run real unittest checks and persist their actual outcomes in examples/."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({"test": test.id(), "status": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append({"test": test.id(), "status": "failed"})

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append({"test": test.id(), "status": "error"})


if __name__ == "__main__":
    stream = io.StringIO()
    start = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordedResult).run(suite)
    destination = ROOT / "examples" / "verification"
    destination.mkdir(parents=True, exist_ok=True)
    log = stream.getvalue()
    (destination / "unittest.txt").write_text(log, encoding="utf-8")
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "duration_seconds": round(time.perf_counter() - start, 3),
              "successful": result.wasSuccessful(), "live_model_evaluated": False, "cases": result.cases}
    (destination / "tests.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(log, end="")
    raise SystemExit(0 if result.wasSuccessful() else 1)

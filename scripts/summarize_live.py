"""Summarize actual response receipts; never creates or fabricates model actions."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.scheduler.providers import SYSTEM_PROMPT


def summarize(directory: Path):
    evaluation = json.loads((directory / "evaluation.json").read_text(encoding="utf-8"))
    outputs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*/output*.json"))]
    receipts = [step["model_receipt"] for output in outputs for step in output["trace"] if "model_receipt" in step]
    totals = Counter()
    for receipt in receipts:
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            totals[name] += receipt.get("usage", {}).get(name, 0)
    paths = sorted({tuple(step["tool"] for step in output["trace"]) for output in outputs})
    source_hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted((ROOT / "src/scheduler").glob("*.py"))}
    (directory / "system-prompt.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "evidence_scope": "live_model_run",
              "scenarios": evaluation["scenarios"], "passed": evaluation["passed"], "output_files": len(outputs),
              "model_response_count": len(receipts), "distinct_path_count": len(paths), "distinct_paths": paths,
              "requested_models": sorted({receipt["requested_model"] for receipt in receipts}),
              "returned_models": sorted({receipt["returned_model"] for receipt in receipts if receipt.get("returned_model")}),
              "service_hosts": sorted({receipt["service_host"] for receipt in receipts}),
              "token_usage": dict(totals), "response_ids": [receipt["response_id"] for receipt in receipts],
              "source_sha256": source_hashes,
              "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
              "limits": "Synthetic inputs and local business tools; one evaluated run per case, not a statistical quality claim."}
    (directory / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("scenarios", "passed", "model_response_count", "distinct_path_count", "requested_models", "token_usage")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "examples/live")
    summarize(parser.parse_args().root)

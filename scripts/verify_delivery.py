"""Verify local artifact consistency and document links, with a saved report."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def verify():
    checks = []

    def check(name, passed):
        checks.append({"check": name, "passed": bool(passed)})

    required = ["README.md", "requirements.txt", ".env.example"] + [
        "docs/" + name for name in ("01-requirements.md", "02-solution.md", "03-evaluation.md", "04-ai-usage.md", "05-retrospective.md")]
    check("required_files", all((ROOT / name).is_file() for name in required))
    broken = []
    for doc in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for ref in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            if "://" in ref or ref.startswith("#"):
                continue
            if not (doc.parent / ref.split("#")[0]).exists():
                broken.append(str(doc.relative_to(ROOT)) + ":" + ref)
    check("document_links_resolve", not broken)
    evaluation = json.loads((ROOT / "examples/mock/evaluation.json").read_text(encoding="utf-8"))
    check("all_scenarios_pass", evaluation["passed"] == evaluation["scenarios"] == 13)
    outputs = sorted((ROOT / "examples/mock").glob("*/output*.json"))
    check("at_least_three_actual_runs", len(outputs) >= 3)
    actual_traces = 0
    for output in outputs:
        value = json.loads(output.read_text(encoding="utf-8"))
        suffix = output.stem.removeprefix("output")
        trace_path = output.parent / ("trace" + suffix + ".jsonl")
        input_path = output.parent / ("input" + suffix + ".json")
        trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        check(str(output.relative_to(ROOT)) + ":trace_matches", trace == value["trace"])
        check(str(output.relative_to(ROOT)) + ":bounded", len(trace) == value["steps_used"] <= value["max_steps"])
        check(str(output.relative_to(ROOT)) + ":honest_scope", value["provider"] == "mock" and value["evidence_scope"] == "offline_workflow_only" and not value["published"])
        check(str(output.relative_to(ROOT)) + ":input_exists", input_path.is_file())
        check(str(output.relative_to(ROOT)) + ":step_fields", all({"step", "material_id", "tool", "arguments", "result", "result_summary", "reason", "next_action"} <= set(step) for step in trace))
        actual_traces += len(trace)
    tests = json.loads((ROOT / "examples/verification/tests.json").read_text(encoding="utf-8"))
    check("all_tests_pass", tests["successful"] and tests["tests_run"] == len(tests["cases"]) and not tests["failures"] and not tests["errors"] and not tests["skipped"])
    # Targeted repository scan: test placeholders and empty templates are permitted.
    suspicious = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(x in path.relative_to(ROOT).parts for x in ("work", "__pycache__", ".git")):
            continue
        if path.suffix not in {".py", ".md", ".json", ".jsonl", ".txt", ".example"}:
            continue
        text = path.read_text(encoding="utf-8")
        # Construct at runtime so the scanner's own source does not match.
        pattern = "s" + "k-" + r"[A-Za-z0-9_-]{20,}"
        if re.search(pattern, text):
            suspicious.append(str(path.relative_to(ROOT)))
    check("no_api_key_patterns", not suspicious)
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "successful": all(x["passed"] for x in checks),
              "checks_run": len(checks), "actual_output_files": len(outputs), "actual_trace_steps": actual_traces,
              "broken_links": broken, "suspicious_files": suspicious, "checks": checks,
              "live_model_evaluated": False}
    destination = ROOT / "examples/verification/delivery.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("successful", "checks_run", "actual_output_files", "actual_trace_steps")}, ensure_ascii=False))
    return report["successful"]


if __name__ == "__main__":
    raise SystemExit(0 if verify() else 1)

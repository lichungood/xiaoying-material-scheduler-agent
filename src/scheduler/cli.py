"""CLI and reproducible acceptance scenario runner (stdlib only)."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sys
import tempfile
from .agent import Agent
from .config import read_private_config
from .domain import Request
from .providers import MockProvider, LiveProvider
from .storage import DraftStore
from .tools import BusinessTools

ROOT = Path(__file__).resolve().parents[2]
TOOL_NAMES = {"read_material", "check_rules", "query_slots", "save_draft"}


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def provider_for(name, env_file=None):
    if name == "mock":
        if env_file is not None:
            raise ValueError("--env-file 仅用于 live 模式")
        return MockProvider()
    return LiveProvider(read_private_config(env_file) if env_file is not None else None)


def execute(raw, provider, store, data_dir, max_steps=30, faults=None):
    request = Request.parse(raw)
    tools = BusinessTools(request, store, data_dir, faults)
    return Agent(tools, provider, max_steps).run()


def write_run(out_dir, raw, result, suffix=""):
    write_json(out_dir / f"input{suffix}.json", raw)
    write_json(out_dir / f"output{suffix}.json", result)
    (out_dir / f"trace{suffix}.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in result["trace"]), encoding="utf-8")


SCENARIOS = [
    ("normal", "completed", {}, 1, 1),
    ("missing", "needs_information", {}, 1, 0),
    ("risk", "blocked", {}, 1, 0),
    ("conflict", "needs_confirmation", {}, 1, 1),
    ("duplicate", "completed", {}, 2, 1),
    ("save_failure", "failed", {"save_draft": 1}, 1, 0),
    ("supplement", "completed", {}, 1, 1),
    ("query_failure", "completed", {"query_slots": 1}, 1, 1),
    ("no_slots", "no_feasible_slot", {}, 1, 0),
    ("confirmation", "completed", {}, 2, 1),
    ("batch", "partial", {}, 1, 2),
    ("step_limit", "incomplete", {}, 1, 0),
    ("changed_schedule", "completed", {}, 1, 1),
]


def demo(args):
    provider = provider_for(args.provider, args.env_file)
    out_root = args.out or ROOT / "examples" / args.provider
    reports = []
    for name, expected, faults, repeats, count in SCENARIOS:
        raw = json.loads((ROOT / "examples" / "inputs" / f"{name}.json").read_text(encoding="utf-8-sig"))
        out_dir = out_root / name
        with tempfile.TemporaryDirectory(prefix="material_scheduler_") as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(args.data, data_dir)
            if name == "changed_schedule":
                write_json(data_dir / "schedule.json", [{"channel": "douyin", "at": "2026-11-01T19:00+08:00", "source_id": "changed-synthetic"}])
            write_json(out_dir / "scenario.json", {"provider": args.provider, "faults": faults,
                "max_steps": 2 if name == "step_limit" else 30,
                "schedule": json.loads((data_dir / "schedule.json").read_text(encoding="utf-8-sig")),
                "repetitions": repeats, "expected_final_status": expected})
            with closing(DraftStore(Path(temp) / "drafts.sqlite3")) as store:
                outputs = []
                for number in range(repeats):
                    current = dict(raw)
                    if name == "confirmation" and number == 1:
                        # This fixture represents a separate explicit user input, not model consent.
                        current["confirmed_slots"] = {"M01": "2026-11-01T19:00+08:00"}
                    result = execute(current, provider, store, data_dir, 2 if name == "step_limit" else 30, faults)
                    write_run(out_dir, current, result, "" if number == 0 else f"-{number + 1}")
                    outputs.append(result)
                drafts = store.rows()
                write_json(out_dir / "drafts.json", drafts)
        checks = {
            "final_status": outputs[-1]["task_status"] == expected,
            "draft_count": len(drafts) == count,
            "never_published": all(result["published"] is False for result in outputs),
            "bounded": all(result["steps_used"] <= result["max_steps"] for result in outputs),
        }
        if name == "duplicate":
            checks["same_draft_id"] = outputs[0]["items"][0]["draft"]["draft_id"] == outputs[1]["items"][0]["draft"]["draft_id"] if all(x["items"][0]["draft"] for x in outputs) else False
            checks["duplicate_reported"] = outputs[1]["items"][0]["save_status"] == "duplicate"
        if name == "conflict":
            item = outputs[-1]["items"][0]
            checks["pending_confirmation"] = bool(item["draft"] and item["draft"]["confirmation_status"] == "pending" and item["requested_at"] != item["suggested_at"])
        if name == "confirmation":
            checks["explicit_confirmation_only"] = bool(outputs[0]["items"][0]["draft"] and outputs[0]["items"][0]["draft"]["confirmation_status"] == "pending" and drafts and drafts[0]["confirmation_status"] == "confirmed")
        reports.append({"scenario": name, "expected": expected, "actual": outputs[-1]["task_status"],
                        "draft_count": len(drafts), "checks": checks, "passed": all(checks.values()),
                        "artifacts": str(out_dir.relative_to(out_root))})
    evaluation = {"provider": args.provider,
                  "evidence_scope": "offline_workflow_only" if args.provider == "mock" else "live_model_run",
                  "scenarios": len(reports), "passed": sum(x["passed"] for x in reports), "results": reports}
    write_json(out_root / "evaluation.json", evaluation)
    table = [f"# {args.provider} 实际运行结果", "", "离线 Mock 只证明流程与约束，不证明真实模型决策效果。" if args.provider == "mock" else "本文件来自真实模型运行；需逐项检查 Trace。", "",
             "| 场景 | 预期 | 实际 | 草稿数 | 通过 |", "|---|---|---|---:|---|"]
    table += [f"| {r['scenario']} | {r['expected']} | {r['actual']} | {r['draft_count']} | {r['passed']} |" for r in reports]
    (out_root / "summary.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print(json.dumps({"scenarios": len(reports), "passed": evaluation["passed"], "evidence_scope": evaluation["evidence_scope"]}, ensure_ascii=False))
    return 0 if evaluation["passed"] == len(reports) else 1


def parse_faults(values):
    result = {}
    for value in values:
        name, count = value.split(":", 1)
        if name not in TOOL_NAMES or not 1 <= int(count) <= 100:
            raise ValueError("fault 格式为 工具名:次数，次数范围 1..100")
        result[name] = int(count)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="素材审核与排期 Agent（仅保存草稿）")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="处理一个 JSON 请求")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--db", type=Path, default=Path("work/drafts.sqlite3"))
    run.add_argument("--out", type=Path, default=Path("work/last-run"))
    run.add_argument("--max-steps", type=int, default=30)
    run.add_argument("--fault", action="append", default=[], help="故障注入，如 save_draft:1")
    scenarios = sub.add_parser("demo", help="运行完整验收场景并保存真实执行文件")
    for command in (run, scenarios):
        command.add_argument("--provider", choices=("mock", "live"), default="mock")
        command.add_argument("--data", type=Path, default=ROOT / "data")
        command.add_argument("--env-file", type=Path, help="显式读取本机私有模型配置；仅 live 可用，不执行文件内容")
    scenarios.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            return demo(args)
        raw = json.loads(args.input.read_text(encoding="utf-8-sig"))
        Request.parse(raw)  # Fail before opening/creating a DB for invalid requests.
        provider = provider_for(args.provider, args.env_file)
        with closing(DraftStore(args.db)) as store:
            result = execute(raw, provider, store, args.data, args.max_steps, parse_faults(args.fault))
        write_run(args.out, raw, result)
        print(json.dumps({k: v for k, v in result.items() if k != "trace"}, ensure_ascii=False, indent=2))
        if result["task_status"] in ("completed", "needs_confirmation"):
            return 0
        return 3 if result["task_status"] == "failed" else 2
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"task_status": "invalid_input_or_configuration", "message": str(exc), "published": False}, ensure_ascii=False), file=sys.stderr)
        return 4

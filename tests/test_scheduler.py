from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

from src.scheduler.agent import Agent
from src.scheduler.cli import ROOT, execute
from src.scheduler.domain import Request
from src.scheduler.providers import Action, LiveProvider, MockProvider
from src.scheduler.storage import DraftStore
from src.scheduler.tools import BusinessTools


class ScriptedProvider:
    """Adversarial double for boundary tests, not evidence of model decisions."""
    mode = "mock"
    model = "scripted-boundary-test-double"

    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, messages, context):
        return next(self.actions)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        shutil.copytree(ROOT / "data", self.data)
        self.store = DraftStore(Path(self.temp.name) / "drafts.sqlite3")
        self.addCleanup(self.store.close)
        self.raw = json.loads((ROOT / "examples/inputs/normal.json").read_text(encoding="utf-8"))

    def run_case(self, raw=None, **kwargs):
        return execute(raw or self.raw, MockProvider(), self.store, self.data, **kwargs)

    def tools(self, raw=None):
        return BusinessTools(Request.parse(raw or self.raw), self.store, self.data)

    def prepare(self, tools):
        tools.execute("M01", "read_material", {"include_supplement": False})
        tools.execute("M01", "check_rules", {})
        tools.execute("M01", "query_slots", {"start_at": self.raw["search_window"]["start"], "end_at": self.raw["search_window"]["end"]})

    def test_normal_draft_has_actual_saved_state(self):
        result = self.run_case()
        self.assertEqual(result["task_status"], "completed")
        item = result["items"][0]
        self.assertEqual(item["save_status"], "saved")
        self.assertEqual(item["draft"]["proposed_at"], self.raw["requested_at"])
        self.assertEqual(item["draft"]["confirmation_status"], "not_required")
        self.assertFalse(result["published"])
        self.assertEqual(len(self.store.rows()), 1)

    def test_missing_metadata_stays_missing_after_supplement(self):
        self.raw["material_ids"] = ["M02"]
        result = self.run_case()
        self.assertEqual(result["task_status"], "needs_information")
        self.assertIn("补充素材字段: rights_status", result["items"][0]["pending_items"])
        self.assertTrue(any(x["tool"] == "read_material" and x["arguments"]["include_supplement"] for x in result["trace"]))
        self.assertEqual(self.store.rows(), [])

    def test_missing_material_returns_information_gap(self):
        self.raw["material_ids"] = ["DOES-NOT-EXIST"]
        result = self.run_case()
        self.assertEqual(result["task_status"], "needs_information")
        self.assertEqual(result["items"][0]["review_status"], "not_found")

    def test_risk_blocks_before_slot_or_save(self):
        self.raw["material_ids"] = ["M03"]
        result = self.run_case()
        self.assertEqual(result["task_status"], "blocked")
        self.assertIn("未经证实", result["items"][0]["risk_reasons"][0])
        self.assertFalse(any(x["tool"] == "save_draft" for x in result["trace"]))
        self.assertEqual(self.store.rows(), [])

    def test_supplement_changes_action_and_allows_save(self):
        self.raw["material_ids"] = ["M04"]
        result = self.run_case()
        self.assertEqual(result["task_status"], "completed")
        reviews = [x["result"]["status"] for x in result["trace"] if x["tool"] == "check_rules"]
        self.assertEqual(reviews, ["missing", "passed"])

    def test_hard_time_conflict_is_pending_with_original_retained(self):
        self.raw["requested_at"] = "2026-11-01T18:00+08:00"
        result = self.run_case()
        item = result["items"][0]
        self.assertEqual(result["task_status"], "needs_confirmation")
        self.assertEqual(item["suggested_at"], "2026-11-01T19:00+08:00")
        self.assertEqual(item["draft"]["requested_at"], self.raw["requested_at"])
        self.assertEqual(item["draft"]["confirmation_status"], "pending")

    def test_explicit_confirmation_updates_same_draft(self):
        self.raw["requested_at"] = "2026-11-01T18:00+08:00"
        first = self.run_case()
        self.raw["confirmed_slots"] = {"M01": "2026-11-01T19:00+08:00"}
        second = self.run_case()
        self.assertEqual(second["task_status"], "completed")
        self.assertEqual(second["items"][0]["save_status"], "updated")
        self.assertEqual(first["items"][0]["draft"]["draft_id"], second["items"][0]["draft"]["draft_id"])
        self.assertEqual(len(self.store.rows()), 1)

    def test_soft_time_may_adjust_within_user_window(self):
        self.raw.update(requested_at="2026-11-01T18:00+08:00", hard_time=False)
        result = self.run_case()
        self.assertEqual(result["task_status"], "completed")
        self.assertEqual(result["items"][0]["draft"]["confirmation_status"], "not_required")

    def test_duplicate_submission_keeps_one_draft_and_id(self):
        first, second = self.run_case(), self.run_case()
        self.assertEqual(second["items"][0]["save_status"], "duplicate")
        self.assertEqual(first["items"][0]["draft"]["draft_id"], second["items"][0]["draft"]["draft_id"])
        self.assertEqual(len(self.store.rows()), 1)

    def test_same_request_id_different_payload_rejected(self):
        self.run_case()
        self.raw["requested_at"] = "2026-11-01T20:00+08:00"
        result = self.run_case()
        self.assertEqual(result["task_status"], "failed")
        self.assertTrue(any(x["result"].get("error") == "idempotency_conflict" for x in result["trace"]))
        self.assertEqual(len(self.store.rows()), 1)

    def test_save_failure_is_explicit_and_retryable(self):
        failed = self.run_case(faults={"save_draft": 1})
        self.assertEqual(failed["task_status"], "failed")
        self.assertEqual(failed["items"][0]["save_status"], "failed")
        self.assertIsNone(failed["items"][0]["draft"])
        self.assertEqual(self.store.rows(), [])
        retried = self.run_case()
        self.assertEqual(retried["task_status"], "completed")
        self.assertEqual(len(self.store.rows()), 1)

    def test_real_sqlite_write_failure_is_not_reported_as_saved(self):
        # SQLite itself refuses the write; this does not use the fault injector.
        self.store.connection.execute("PRAGMA query_only = ON")
        result = self.run_case()
        self.assertEqual(result["task_status"], "failed")
        self.assertEqual(result["items"][0]["save_status"], "failed")
        self.assertEqual(result["items"][0]["suggested_at"], self.raw["requested_at"])
        self.assertEqual(self.store.rows(), [])

    def test_missing_channel_metadata_requests_information(self):
        materials = json.loads((self.data / "materials.json").read_text(encoding="utf-8"))
        materials["M01"].pop("allowed_channels")
        (self.data / "materials.json").write_text(json.dumps(materials), encoding="utf-8")
        result = self.run_case()
        self.assertEqual(result["task_status"], "needs_information")
        self.assertIn("补充素材字段: allowed_channels", result["items"][0]["pending_items"])

    def test_query_failure_retries_based_on_observed_error(self):
        result = self.run_case(faults={"query_slots": 1})
        self.assertEqual(result["task_status"], "completed")
        queries = [x for x in result["trace"] if x["tool"] == "query_slots"]
        self.assertEqual([x["result"]["ok"] for x in queries], [False, True])
        self.assertEqual(queries[0]["next_action"], "query_slots")

    def test_persistent_query_failure_is_not_success(self):
        result = self.run_case(faults={"query_slots": 5})
        self.assertEqual(result["task_status"], "failed")
        self.assertEqual(self.store.rows(), [])

    def test_no_available_slots_does_not_save(self):
        self.raw["requested_at"] = "2026-11-01T18:00+08:00"
        self.raw["search_window"] = {"start": self.raw["requested_at"], "end": self.raw["requested_at"]}
        result = self.run_case()
        self.assertEqual(result["task_status"], "no_feasible_slot")
        self.assertEqual(self.store.rows(), [])

    def test_confirmed_but_occupied_slot_cannot_be_replaced(self):
        self.raw["confirmed_slots"] = {"M01": "2026-11-01T18:00+08:00"}
        result = self.run_case()
        self.assertEqual(result["task_status"], "no_feasible_slot")
        self.assertEqual(self.store.rows(), [])

    def test_changed_occupancy_changes_proposal(self):
        self.raw["requested_at"] = "2026-11-01T18:00+08:00"
        first = self.run_case()
        changed = [{"channel": "douyin", "at": "2026-11-01T19:00+08:00"}]
        (self.data / "schedule.json").write_text(json.dumps(changed), encoding="utf-8")
        self.raw["request_id"] = "changed-occupancy"
        second = self.run_case()
        self.assertEqual(first["items"][0]["suggested_at"], "2026-11-01T19:00+08:00")
        self.assertEqual(second["items"][0]["suggested_at"], "2026-11-01T18:00+08:00")
        self.assertEqual(second["task_status"], "completed")

    def test_occupancy_change_on_same_request_does_not_mutate_saved_draft(self):
        first = self.run_case()
        changed = [{"channel": "douyin", "at": "2026-11-01T18:00+08:00"},
                   {"channel": "douyin", "at": self.raw["requested_at"]}]
        (self.data / "schedule.json").write_text(json.dumps(changed), encoding="utf-8")
        second = self.run_case()
        self.assertEqual(second["task_status"], "failed")
        self.assertTrue(any(x["result"].get("error") == "idempotency_conflict" for x in second["trace"]))
        self.assertEqual(len(self.store.rows()), 1)
        self.assertEqual(self.store.rows()[0]["draft_id"], first["items"][0]["draft"]["draft_id"])
        self.assertEqual(self.store.rows()[0]["proposed_at"], self.raw["requested_at"])

    def test_batch_reserves_distinct_slots(self):
        self.raw["material_ids"] = ["M01", "M04"]
        result = self.run_case()
        self.assertEqual(result["task_status"], "partial")
        self.assertEqual([x["task_status"] for x in result["items"]], ["completed", "needs_confirmation"])
        self.assertEqual(len({x["proposed_at"] for x in self.store.rows()}), 2)

    def test_step_budget_is_global_including_unstarted_items(self):
        self.raw["material_ids"] = ["M01", "M04"]
        result = self.run_case(max_steps=2)
        self.assertEqual(result["steps_used"], 2)
        self.assertEqual([x["termination"] for x in result["items"]], ["max_steps", "max_steps"])
        self.assertEqual(result["task_status"], "incomplete")
        self.assertEqual(self.store.rows(), [])

    def test_budget_after_save_preserves_draft_but_returns_incomplete(self):
        result = self.run_case(max_steps=4)
        self.assertEqual(result["task_status"], "incomplete")
        self.assertEqual(result["items"][0]["save_status"], "saved")
        self.assertEqual(len(self.store.rows()), 1)

    def test_fake_early_finish_cannot_claim_completion(self):
        provider = ScriptedProvider([Action("finish", {"suggested_at": None}, "已保存并已发布")])
        result = Agent(self.tools(), provider).run()
        self.assertEqual(result["task_status"], "incomplete")
        self.assertEqual(result["items"][0]["save_status"], "not_attempted")
        self.assertFalse(result["published"])

    def test_model_cannot_skip_review_or_forge_confirmation(self):
        tools = self.tools()
        result = tools.execute("M01", "save_draft", {"proposed_at": self.raw["requested_at"]})
        self.assertFalse(result["ok"])
        self.prepare(tools)
        forged = tools.execute("M01", "save_draft", {"proposed_at": self.raw["requested_at"], "confirmed": True})
        self.assertFalse(forged["ok"])
        self.assertEqual(self.store.rows(), [])

    def test_model_cannot_ignore_explicit_confirmed_slot(self):
        self.raw["confirmed_slots"] = {"M01": "2026-11-01T20:00+08:00"}
        tools = self.tools()
        self.prepare(tools)
        result = tools.execute("M01", "save_draft", {"proposed_at": self.raw["requested_at"]})
        self.assertFalse(result["ok"])
        self.assertEqual(self.store.rows(), [])

    def test_model_cannot_save_blocked_material_even_if_it_tries(self):
        self.raw["material_ids"] = ["M03"]
        tools = self.tools()
        tools.execute("M03", "read_material", {})
        tools.execute("M03", "check_rules", {})
        result = tools.execute("M03", "save_draft", {"proposed_at": self.raw["requested_at"]})
        self.assertFalse(result["ok"])

    def test_rereading_metadata_invalidates_previous_review(self):
        tools = self.tools()
        self.prepare(tools)
        tools.execute("M01", "read_material", {"include_supplement": True})
        result = tools.execute("M01", "save_draft", {"proposed_at": self.raw["requested_at"]})
        self.assertFalse(result["ok"])

    def test_save_requires_observed_availability_and_rechecks_conflict(self):
        tools = self.tools()
        tools.execute("M01", "read_material", {})
        tools.execute("M01", "check_rules", {})
        unseen = tools.execute("M01", "save_draft", {"proposed_at": self.raw["requested_at"]})
        self.assertFalse(unseen["ok"])
        self.prepare(tools)
        tools.schedule.append({"channel": "douyin", "at": self.raw["requested_at"]})
        conflict = tools.execute("M01", "save_draft", {"proposed_at": self.raw["requested_at"]})
        self.assertEqual(conflict["error"], "slot_conflict")
        self.assertEqual(self.store.rows(), [])

    def test_unknown_publish_tool_and_cross_material_access_are_rejected(self):
        tools = self.tools()
        self.assertFalse(tools.execute("M01", "publish", {})["ok"])
        self.assertFalse(tools.execute("M03", "read_material", {})["ok"])

    def test_out_of_window_cannot_query_or_save(self):
        tools = self.tools()
        result = tools.execute("M01", "query_slots", {"start_at": "2026-11-01T17:00+08:00", "end_at": self.raw["requested_at"]})
        self.assertFalse(result["ok"])
        self.prepare(tools)
        result = tools.execute("M01", "save_draft", {"proposed_at": "2026-11-01T22:00+08:00"})
        self.assertFalse(result["ok"])

    def test_rules_change_changes_review_and_blocks(self):
        rules = json.loads((self.data / "rules.json").read_text(encoding="utf-8"))
        rules["blocked_tags"].append({"id": "R-NEW", "tag": "new_risk", "reason": "新增风险"})
        (self.data / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
        materials = json.loads((self.data / "materials.json").read_text(encoding="utf-8"))
        materials["M01"]["content_tags"] = ["new_risk"]
        (self.data / "materials.json").write_text(json.dumps(materials), encoding="utf-8")
        self.assertEqual(self.run_case()["task_status"], "blocked")

    def test_invalid_inputs_fail_before_execution(self):
        variants = [
            {"requested_at": "2026-11-01T19:00"},
            {"requested_at": "2026-11-01T19:30+08:00"},
            {"hard_time": "false"}, {"material_ids": ["M01", "M01"]},
            {"confirmed_slots": {"M99": "2026-11-01T19:00+08:00"}},
            {"search_window": {"start": "2026-11-01T18:00+08:00", "end": "2026-11-05T21:00+08:00"}},
            {"publish": True}, {"request_id": ""},
        ]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Request.parse({**self.raw, **changes})

    def test_model_exception_is_redacted_and_never_falls_back(self):
        provider = MagicMock(mode="live", model="test")
        provider.decide.side_effect = RuntimeError("secret-test-value")
        result = Agent(self.tools(), provider).run()
        self.assertEqual(result["items"][0]["termination"], "model_error")
        self.assertNotIn("secret-test-value", json.dumps(result))
        self.assertEqual(result["provider"], "live")
        self.assertEqual(self.store.rows(), [])

    def test_concurrent_drafts_reserve_at_most_one_slot(self):
        db_path = Path(self.temp.name) / "concurrent.sqlite3"
        with closing(DraftStore(db_path)):
            pass
        barrier = threading.Barrier(2)

        def save(index):
            raw = {**self.raw, "request_id": f"concurrent-{index}"}
            with closing(DraftStore(db_path)) as store:
                barrier.wait(timeout=10)
                return store.save(Request.parse(raw), "M01", self.raw["requested_at"], "not_required")

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(save, (1, 2)))
        self.assertEqual(sum(x["ok"] for x in outcomes), 1)
        self.assertEqual([x["error"] for x in outcomes if not x["ok"]], ["slot_conflict"])
        with closing(DraftStore(db_path)) as store:
            self.assertEqual(len(store.rows()), 1)

    def test_cli_is_runnable_and_emits_artifacts(self):
        out = Path(self.temp.name) / "out"
        completed = subprocess.run([sys.executable, "-m", "src.scheduler", "run", "--input", "examples/inputs/normal.json",
                                    "--db", str(Path(self.temp.name) / "cli.sqlite3"), "--out", str(out)],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((out / "trace.jsonl").exists())
        self.assertEqual(json.loads((out / "output.json").read_text(encoding="utf-8"))["task_status"], "completed")


class LiveContractTests(unittest.TestCase):
    """Stubbed HTTP contract only. These tests do not call or evaluate a model."""

    def test_live_requires_explicit_configuration(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            LiveProvider()

    def test_live_sends_native_tools_and_parses_one_action(self):
        payload = {"choices": [{"message": {"tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": "read_material", "arguments": json.dumps({"include_supplement": False, "reason": "读取素材"})}}]}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
        with patch.dict(os.environ, {"LLM_API_KEY": "test-placeholder", "LLM_MODEL": "test-model"}), patch("urllib.request.urlopen", return_value=response) as send:
            action = LiveProvider().decide([{"role": "user", "content": "test"}], {})
        self.assertEqual(action.name, "read_material")
        self.assertEqual(action.arguments, {"include_supplement": False})
        body = json.loads(send.call_args.args[0].data)
        self.assertEqual(len(body["tools"]), 5)
        self.assertFalse(body["parallel_tool_calls"])
        self.assertEqual(body["tool_choice"], "required")

    def test_live_rejects_multiple_calls_and_insecure_urls(self):
        for calls in ([], [{}, {}]):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"tool_calls": calls}}]}).encode("utf-8")
            with self.subTest(calls=len(calls)), patch.dict(os.environ, {"LLM_API_KEY": "test-placeholder", "LLM_MODEL": "test-model"}), patch("urllib.request.urlopen", return_value=response), self.assertRaises(RuntimeError):
                LiveProvider().decide([], {})
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://example.invalid/v1"}), self.assertRaises(ValueError):
            LiveProvider()


if __name__ == "__main__":
    unittest.main()

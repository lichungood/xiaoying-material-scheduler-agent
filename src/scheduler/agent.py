"""Bounded select -> execute -> observe loop with evidence-derived output."""
from datetime import datetime, timezone
import json
import uuid
from .domain import slot
from .providers import SYSTEM_PROMPT, ModelCallError
from .tools import BusinessTools


class Agent:
    def __init__(self, tools: BusinessTools, provider, max_steps: int = 30):
        if type(max_steps) is not int or not 1 <= max_steps <= 100:
            raise ValueError("max_steps 必须是 1 到 100 的整数")
        self.tools, self.provider, self.max_steps = tools, provider, max_steps

    def run(self) -> dict:
        req = self.tools.request
        trace = []
        items = []
        for material_id in req.material_ids:
            context = {"request": req.as_dict(), "material_id": material_id}
            messages = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
            termination = "max_steps"
            suggested_at = None
            while len(trace) < self.max_steps:
                step = len(trace) + 1
                try:
                    action = self.provider.decide(messages, context)
                    if not isinstance(action.arguments, dict) or not isinstance(action.reason, str):
                        raise ValueError("非法动作")
                except Exception as exc:
                    # Do not serialize raw provider exceptions, which can contain secrets.
                    diagnostic = {"ok": False, "error": "model_error"}
                    if isinstance(exc, ModelCallError):
                        diagnostic["cause"] = exc.code
                        if exc.http_status is not None:
                            diagnostic["http_status"] = exc.http_status
                    trace.append({"step": step, "material_id": material_id, "tool": "model_error",
                                  "arguments": {}, "reason": "模型未能返回有效动作",
                                  "result": diagnostic})
                    termination = "model_error"
                    break
                call_id = action.call_id or f"call_{step}"
                if action.name == "finish":
                    result = {"ok": True, "status": "finished"}
                    try:
                        if set(action.arguments) != {"suggested_at"}:
                            raise ValueError("finish 参数不匹配")
                        proposed = action.arguments["suggested_at"]
                        if proposed is not None:
                            proposed = slot(proposed)
                            known = self.tools.queries.get(material_id, {}).get("slots", [])
                            if not any(x["at"] == proposed and x["available"] for x in known):
                                raise ValueError("建议必须来自已查询的可用时段")
                            suggested_at = proposed
                    except (ValueError, TypeError):
                        result = {"ok": False, "error": "invalid_suggestion"}
                    if result["ok"]:
                        termination = "finished"
                else:
                    result = self.tools.execute(material_id, action.name, action.arguments)
                trace.append({"step": step, "material_id": material_id, "tool": action.name,
                              "arguments": action.arguments, "reason": action.reason[:300],
                              "result": result})
                if action.receipt is not None:
                    trace[-1]["model_receipt"] = action.receipt
                messages.append({"role": "assistant", "content": None, "tool_calls": [{
                    "id": call_id, "type": "function", "function": {"name": action.name,
                        "arguments": json.dumps({**action.arguments, "reason": action.reason[:300]}, ensure_ascii=False)}}]})
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": json.dumps({"tool": action.name, "arguments": action.arguments, "result": result}, ensure_ascii=False)})
                if termination == "finished":
                    break
            items.append(self._item_result(material_id, termination, suggested_at, trace))
        for index, entry in enumerate(trace):
            following = trace[index + 1] if index + 1 < len(trace) else None
            entry["next_action"] = following["tool"] if following and following["material_id"] == entry["material_id"] else "end_item"
            entry["result_summary"] = self._summary(entry["result"])
        return {"schema_version": 1, "run_id": str(uuid.uuid4()),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "provider": self.provider.mode, "model": self.provider.model,
                "evidence_scope": "offline_workflow_only" if self.provider.mode == "mock" else "live_model_run",
                "request": req.as_dict(), "max_steps": self.max_steps,
                "steps_used": len(trace), "tool_calls_used": sum(x["tool"] not in ("finish", "model_error") for x in trace),
                "task_status": self._aggregate(items), "items": items, "trace": trace,
                "published": False}

    @staticmethod
    def _summary(result: dict) -> dict:
        return {key: result[key] for key in ("ok", "status", "error", "save_status", "missing_fields", "risks") if key in result}

    def _item_result(self, material_id, termination, suggested_at, trace):
        req = self.tools.request
        review = self.tools.reviews.get(material_id, {})
        save = self.tools.saves.get(material_id, {})
        draft = self.tools.store.existing(req.request_id, material_id)
        query = self.tools.queries.get(material_id, {})
        own_trace = [entry for entry in trace if entry["material_id"] == material_id]
        not_found = any(x["tool"] == "read_material" and x["result"].get("status") == "not_found" for x in own_trace)
        last_failures = [x for x in own_trace if not x["result"].get("ok")]
        pending = []
        reasons = [x["reason"] for x in review.get("risks", [])]
        if review.get("missing_fields"):
            pending += [f"补充素材字段: {key}" for key in review["missing_fields"]]
        if not_found:
            pending.append("提供存在的素材 ID")
        if suggested_at is None:
            known = {row["at"] for row in query.get("slots", []) if row["available"]}
            for entry in reversed(own_trace):
                candidate = entry["arguments"].get("proposed_at") if entry["tool"] == "save_draft" else None
                if isinstance(candidate, str) and candidate in known:
                    suggested_at = candidate
                    break
        if draft:
            suggested_at = draft["proposed_at"]
            if draft["confirmation_status"] == "pending":
                pending.append(f"确认改期: {req.requested_at} -> {suggested_at}")
        elif suggested_at and req.hard_time and suggested_at != req.requested_at:
            pending.append(f"确认改期: {req.requested_at} -> {suggested_at}")
        if termination != "finished":
            status = "incomplete"
            reasons.append("达到执行步数上限" if termination == "max_steps" else "模型调用或协议失败")
        elif review.get("status") == "blocked":
            status = "blocked"
        elif review.get("status") == "missing" or not_found:
            status = "needs_information"
        elif save and not save.get("ok"):
            status = "failed"
            reasons.append(save.get("message", save["error"]))
        elif draft and save.get("ok"):
            status = "needs_confirmation" if draft["confirmation_status"] == "pending" else "completed"
        elif review.get("status") == "passed" and query.get("ok") and (
            not any(x["available"] for x in query["slots"]) or
            (req.confirmed_slots.get(material_id) and not any(x["at"] == req.confirmed_slots[material_id] and x["available"] for x in query["slots"]))
        ):
            status = "no_feasible_slot"
            pending.append("扩大搜索窗口或重新确认可用时段")
        elif last_failures:
            status = "failed"
            reasons.append(last_failures[-1]["result"].get("message", "工具执行失败"))
        else:
            status = "incomplete"
            reasons.append("缺少完成所需的审核、查询或保存证据")
        save_status = save.get("save_status", "failed" if save and not save.get("ok") else "not_attempted")
        return {"material_id": material_id, "task_status": status,
                "review_status": review.get("status", "not_found" if not_found else "unchecked"),
                "risk_reasons": reasons, "requested_at": req.requested_at,
                "suggested_at": suggested_at, "pending_items": pending,
                "save_status": save_status, "draft": draft, "termination": termination,
                "published": False}

    @staticmethod
    def _aggregate(items):
        statuses = {item["task_status"] for item in items}
        if statuses == {"completed"}:
            return "completed"
        if len(statuses) == 1:
            return next(iter(statuses))
        return "partial"

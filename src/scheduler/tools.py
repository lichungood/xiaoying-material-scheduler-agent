"""Trusted business tools; no publish capability is exposed."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from .domain import Request, slot
from .storage import DraftStore


class ToolError(Exception):
    pass


class BusinessTools:
    def __init__(self, request: Request, store: DraftStore, data_dir: Path, faults: dict[str, int] | None = None):
        self.request, self.store = request, store
        self.assets = self._load(data_dir / "materials.json")
        self.supplements = self._load(data_dir / "metadata_registry.json")
        self.rules = self._load(data_dir / "rules.json")
        self.schedule = self._load(data_dir / "schedule.json")
        self.faults = dict(faults or {})
        self.read_cache: dict[str, dict] = {}
        self.reviews: dict[str, dict] = {}
        self.queries: dict[str, dict] = {}
        self.saves: dict[str, dict] = {}

    @staticmethod
    def _load(path: Path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def execute(self, material_id: str, name: str, arguments: dict) -> dict:
        try:
            if material_id not in self.request.material_ids:
                raise ToolError("素材不在本请求范围内")
            methods = {"read_material": self.read_material, "check_rules": self.check_rules,
                       "query_slots": self.query_slots, "save_draft": self.save_draft}
            if name not in methods:
                raise ToolError("未知工具")
            if self.faults.get(name, 0) > 0:
                self.faults[name] -= 1
                result = {"ok": False, "error": "storage_error" if name == "save_draft" else "tool_unavailable",
                          "message": f"模拟 {name} 失败（故障注入）"}
            else:
                result = methods[name](material_id, **arguments)
        except (ToolError, ValueError, TypeError, KeyError) as exc:
            result = {"ok": False, "error": "invalid_tool_call", "message": str(exc)[:300]}
        if name == "save_draft":
            self.saves[material_id] = result
        return result

    def read_material(self, material_id: str, include_supplement: bool = False) -> dict:
        if type(include_supplement) is not bool:
            raise ToolError("include_supplement 必须为布尔值")
        if material_id not in self.assets:
            return {"ok": True, "status": "not_found", "material_id": material_id}
        material = deepcopy(self.assets[material_id])
        used = False
        if include_supplement and material_id in self.supplements:
            material.update(deepcopy(self.supplements[material_id]))
            used = True
        self.read_cache[material_id] = material
        self.reviews.pop(material_id, None)  # Changed evidence requires a fresh review.
        return {"ok": True, "status": "found", "material_id": material_id,
                "metadata": material, "supplement_used": used,
                "source": "synthetic_catalog+registry" if used else "synthetic_catalog"}

    def _review(self, material_id: str) -> dict:
        material = self.read_cache[material_id]
        missing = [key for key in self.rules["required_fields"] if material.get(key) in (None, "", [])]
        risks = []
        if not missing and material["rights_status"] != "licensed":
            risks.append({"rule_id": "R-RIGHTS", "reason": "缺少可用版权授权"})
        for rule in self.rules["blocked_tags"]:
            if rule["tag"] in material.get("content_tags", []):
                risks.append({"rule_id": rule["id"], "reason": rule["reason"]})
        if "allowed_channels" not in missing and self.request.channel not in material.get("allowed_channels", []):
            risks.append({"rule_id": "R-CHANNEL", "reason": "素材未获该渠道使用授权"})
        return {"ok": True, "status": "blocked" if risks else "missing" if missing else "passed",
                "missing_fields": missing, "risks": risks, "rules_version": self.rules["version"]}

    def check_rules(self, material_id: str) -> dict:
        if material_id not in self.read_cache:
            raise ToolError("必须先读取素材，才能审核")
        result = self._review(material_id)
        self.reviews[material_id] = result
        return result

    def _occupied(self, material_id: str, at: str) -> bool:
        external = any(row["channel"] == self.request.channel and slot(row["at"]) == at for row in self.schedule)
        return external or self.store.occupied(self.request.channel, at, self.request.request_id, material_id)

    def query_slots(self, material_id: str, start_at: str, end_at: str) -> dict:
        start, end = slot(start_at), slot(end_at)
        if not self.request.window_start <= start <= end <= self.request.window_end:
            raise ToolError("查询必须位于用户给出的搜索窗口内")
        entries = []
        current = datetime.fromisoformat(start)
        while current <= datetime.fromisoformat(end):
            at = slot(current.isoformat())
            entries.append({"at": at, "available": not self._occupied(material_id, at)})
            current += timedelta(hours=1)
        result = {"ok": True, "channel": self.request.channel, "slots": entries,
                  "requested_at": self.request.requested_at,
                  "existing_draft": self.store.existing(self.request.request_id, material_id)}
        self.queries[material_id] = result
        return result

    def save_draft(self, material_id: str, proposed_at: str) -> dict:
        proposed_at = slot(proposed_at)
        if material_id not in self.reviews or self._review(material_id)["status"] != "passed":
            raise ToolError("必须读取素材且审核通过，才能保存排期草稿")
        if not self.request.window_start <= proposed_at <= self.request.window_end:
            raise ToolError("建议时段超出用户给出的窗口")
        query = self.queries.get(material_id, {})
        if not any(row["at"] == proposed_at and row["available"] for row in query.get("slots", [])):
            raise ToolError("必须先查询并观察到该时段可用")
        # Recheck at write time. The DB also enforces cross-process uniqueness.
        if self._occupied(material_id, proposed_at):
            return {"ok": False, "error": "slot_conflict", "message": "保存前发现冲突，请重新查询"}
        confirmed = self.request.confirmed_slots.get(material_id)
        if confirmed is not None and proposed_at != confirmed:
            raise ToolError("用户已明确确认其他时段，不能擅自替换")
        if confirmed == proposed_at:
            confirmation = "confirmed"
        elif self.request.hard_time and proposed_at != self.request.requested_at:
            confirmation = "pending"  # Proposal only; requested_at is never overwritten.
        else:
            confirmation = "not_required"
        return self.store.save(self.request, material_id, proposed_at, confirmation)

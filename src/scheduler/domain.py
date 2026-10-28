"""Input contract. All slots are one-hour slots, in Beijing time."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json

BEIJING = timezone(timedelta(hours=8))


def slot(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("时段必须是带 +08:00 的 ISO 8601 字符串")
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() != timedelta(hours=8):
        raise ValueError("时段必须显式使用北京时间 +08:00")
    if dt.minute or dt.second or dt.microsecond:
        raise ValueError("本项目按整点的一小时时段排期")
    return dt.isoformat(timespec="minutes")


def digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Request:
    request_id: str
    material_ids: tuple[str, ...]
    channel: str
    requested_at: str
    window_start: str
    window_end: str
    hard_time: bool = True
    confirmed_slots: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: dict) -> "Request":
        if not isinstance(raw, dict):
            raise ValueError("输入必须是 JSON 对象")
        allowed = {"request_id", "material_ids", "channel", "requested_at", "search_window", "hard_time", "confirmed_slots"}
        if set(raw) - allowed:
            raise ValueError("未知输入字段: " + ", ".join(sorted(set(raw) - allowed)))
        for name in ("request_id", "channel"):
            if not isinstance(raw.get(name), str) or not raw[name].strip() or len(raw[name]) > 100:
                raise ValueError(f"缺少或非法字段: {name}")
        ids = raw.get("material_ids")
        if not isinstance(ids, list) or not ids or len(ids) > 20:
            raise ValueError("material_ids 必须包含 1 到 20 项")
        if any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("素材 ID 必须是互不重复的非空字符串")
        requested = slot(raw.get("requested_at"))
        window = raw.get("search_window", {"start": requested, "end": requested})
        if not isinstance(window, dict) or set(window) != {"start", "end"}:
            raise ValueError("search_window 必须且只能包含 start 和 end")
        start, end = slot(window["start"]), slot(window["end"])
        if not start <= requested <= end or datetime.fromisoformat(end) - datetime.fromisoformat(start) > timedelta(hours=48):
            raise ValueError("请求时段须位于搜索窗口内，窗口不能超过 48 小时")
        hard = raw.get("hard_time", True)
        if type(hard) is not bool:
            raise ValueError("hard_time 必须为布尔值")
        confirmations = raw.get("confirmed_slots", {})
        if not isinstance(confirmations, dict) or set(confirmations) - set(ids):
            raise ValueError("confirmed_slots 只能引用本请求的素材")
        normalized = {key: slot(value) for key, value in confirmations.items()}
        if any(not start <= value <= end for value in normalized.values()):
            raise ValueError("确认时段必须位于搜索窗口内")
        return cls(raw["request_id"], tuple(ids), raw["channel"], requested, start, end, hard, normalized)

    def as_dict(self) -> dict:
        return {
            "request_id": self.request_id, "material_ids": list(self.material_ids),
            "channel": self.channel, "requested_at": self.requested_at,
            "search_window": {"start": self.window_start, "end": self.window_end},
            "hard_time": self.hard_time, "confirmed_slots": dict(self.confirmed_slots),
        }

    @property
    def fingerprint(self) -> str:
        value = self.as_dict()
        value.pop("confirmed_slots")  # Explicit confirmation may advance the same draft.
        return digest(value)

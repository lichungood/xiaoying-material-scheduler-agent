"""SQLite transactions reserve draft slots and enforce idempotency."""
import sqlite3
from pathlib import Path
from .domain import Request, digest


class DraftStore:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""CREATE TABLE IF NOT EXISTS drafts (
            draft_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
            material_id TEXT NOT NULL, request_hash TEXT NOT NULL,
            channel TEXT NOT NULL, proposed_at TEXT NOT NULL,
            confirmation_status TEXT NOT NULL CHECK(confirmation_status IN ('pending', 'confirmed', 'not_required')),
            requested_at TEXT NOT NULL, hard_time INTEGER NOT NULL,
            UNIQUE(request_id, material_id), UNIQUE(channel, proposed_at)
        )""")
        self.connection.commit()

    def close(self):
        self.connection.close()

    def rows(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM drafts ORDER BY draft_id")]

    def existing(self, request_id: str, material_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM drafts WHERE request_id=? AND material_id=?", (request_id, material_id)).fetchone()
        return dict(row) if row else None

    def occupied(self, channel: str, proposed_at: str, request_id: str, material_id: str) -> bool:
        row = self.connection.execute("""SELECT 1 FROM drafts WHERE channel=? AND proposed_at=?
            AND NOT(request_id=? AND material_id=?)""", (channel, proposed_at, request_id, material_id)).fetchone()
        return row is not None

    def save(self, request: Request, material_id: str, proposed_at: str, confirmation: str) -> dict:
        conn = self.connection
        try:
            conn.execute("BEGIN IMMEDIATE")
            old = self.existing(request.request_id, material_id)
            if old and old["request_hash"] != request.fingerprint:
                conn.rollback()
                return {"ok": False, "error": "idempotency_conflict", "message": "相同 request_id 对应不同请求，请使用新 ID"}
            if old:
                if old["proposed_at"] != proposed_at:
                    conn.rollback()
                    return {"ok": False, "error": "idempotency_conflict", "message": "已有草稿的建议时段不同，请使用新请求 ID", "existing_draft": old}
                if confirmation == "confirmed" and old["confirmation_status"] == "pending":
                    conn.execute("UPDATE drafts SET confirmation_status='confirmed' WHERE draft_id=?", (old["draft_id"],))
                    conn.commit()
                    return {"ok": True, "save_status": "updated", "draft": self.existing(request.request_id, material_id)}
                conn.commit()
                return {"ok": True, "save_status": "duplicate", "draft": old}
            draft_id = "draft_" + digest([request.request_id, material_id])[:24]
            conn.execute("INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                draft_id, request.request_id, material_id, request.fingerprint, request.channel,
                proposed_at, confirmation, request.requested_at, int(request.hard_time),
            ))
            conn.commit()
            return {"ok": True, "save_status": "saved", "draft": self.existing(request.request_id, material_id)}
        except sqlite3.IntegrityError:
            conn.rollback()
            return {"ok": False, "error": "slot_conflict", "message": "时段被其他草稿占用，请重新查询"}
        except sqlite3.Error:
            conn.rollback()
            return {"ok": False, "error": "storage_error", "message": "草稿保存失败，未宣称成功；可使用原 request_id 重试"}

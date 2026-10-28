"""Small persistent journal, request queue and session checkpoint using SQLite."""

import json
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS messages (
                seq INTEGER PRIMARY KEY, message_id INTEGER UNIQUE NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                seq INTEGER PRIMARY KEY REFERENCES messages(seq),
                status TEXT NOT NULL DEFAULT 'queued'
            );
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def add(self, payload: dict, requested: bool = False) -> int | None:
        with self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO messages(message_id,payload) VALUES (?,?)",
                                  (payload["message_id"], json.dumps(payload, ensure_ascii=False)))
            if not cur.rowcount:
                return None
            seq = cur.lastrowid
            if requested:
                self.db.execute("INSERT INTO requests(seq) VALUES (?)", (seq,))
            return seq

    def get(self, seq: int) -> dict:
        row = self.db.execute("SELECT payload FROM messages WHERE seq=?", (seq,)).fetchone()
        return json.loads(row[0])

    def update(self, seq: int, payload: dict) -> None:
        with self.db:
            self.db.execute("UPDATE messages SET payload=? WHERE seq=?",
                            (json.dumps(payload, ensure_ascii=False), seq))

    def set(self, key: str, value) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def state(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def status(self, seq: int, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE requests SET status=? WHERE seq=?", (status, seq))

    def queued(self) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT seq FROM requests WHERE status='queued' ORDER BY seq")]

    def interrupt_running(self) -> int:
        # Never automatically repeat an external write after an uncertain crash.
        with self.db:
            return self.db.execute("UPDATE requests SET status='interrupted' WHERE status='running'").rowcount

    def clear_queue(self) -> None:
        with self.db:
            self.db.execute("UPDATE requests SET status='stopped' WHERE status='queued'")

    def latest(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(seq),0) FROM messages").fetchone()[0]

    def context(self, before: int, byte_limit: int) -> tuple[list[dict], bool]:
        """Newest unseen background only; never load the entire journal into memory."""
        cursor = self.state("cursor", 0)
        rows = self.db.execute(
            "SELECT payload FROM messages WHERE seq>? AND seq<? ORDER BY seq DESC", (cursor, before))
        selected, used, omitted = [], 0, False
        for row in rows:
            size = len(row[0].encode("utf-8"))
            if used + size > byte_limit:
                omitted = True
                break
            selected.append(json.loads(row[0]))
            used += size
        return list(reversed(selected)), omitted

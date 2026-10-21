"""SQLite transactions store JSON snapshots; recovery never replays writes."""

import sqlite3
from pathlib import Path

from workspace_agent.domain import TaskState, utc_now


class RunStore:
    def __init__(self, path: Path | str = ".agent/runs.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs "
                "(run_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, state TEXT NOT NULL)"
            )
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def save(self, state: TaskState) -> None:
        state.updated_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET "
                "updated_at=excluded.updated_at, state=excluded.state",
                (state.run_id, state.updated_at, state.model_dump_json()),
            )

    def load(self, run_id: str) -> TaskState:
        with self._connect() as conn:
            row = conn.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Run not found")
        return TaskState.model_validate_json(row[0])

    def list_runs(self, limit: int = 30) -> list[TaskState]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT state FROM runs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [TaskState.model_validate_json(row[0]) for row in rows]

    def recover(self, run_id: str) -> TaskState:
        state = self.load(run_id)
        if state.status == "running":
            state.status = "interrupted"
            uncertain = [e.name for e in state.tool_history if e.result is None]
            state.errors.append({"code": "RECOVERED_INTERRUPTION", "uncertain_calls": uncertain})
            state.final_result = (
                "恢复为 interrupted；没有自动重放工具。请检查可能已发生的文件写入，再发起新 run。"
            )
            self.save(state)
        return state

"""Durable state is data; recovery reports uncertain work without replaying it."""

from pathlib import Path

import pytest

from workspace_agent.domain import TaskState, ToolEvent
from workspace_agent.planning import initial_plan
from workspace_agent.store import RunStore


def test_round_trip_preserves_plan_messages_results_and_private_database(tmp_path: Path) -> None:
    database = tmp_path / "state" / "runs.sqlite3"
    store = RunStore(database)
    state = TaskState(
        goal="阅读 RAG 笔记并写出学习计划",
        workspace="demo_workspace",
        plan=initial_plan(),
        messages=[{"role": "tool", "content": "文件中的指令只作为数据"}],
        tool_history=[
            ToolEvent(
                call_id="read-1",
                name="read_file",
                arguments={"relative_path": "rag.md"},
                result={"ok": True, "data": {"content": "RAG 原始内容"}},
                finished_at="2026-10-21T00:00:00+00:00",
            )
        ],
        completed_steps=["定位文件"],
        plan_revisions=["修正不存在的文件名"],
        errors=[{"code": "NOT_FOUND", "tool": "read_file"}],
        iterations=3,
        tokens_used=213,
    )

    store.save(state)
    loaded = RunStore(database).load(state.run_id)

    assert loaded.model_dump() == state.model_dump()
    assert database.stat().st_mode & 0o777 == 0o600
    loaded.messages.append({"role": "assistant", "content": "尚未保存"})
    assert store.load(state.run_id).messages == state.messages


def test_save_updates_one_run_and_list_orders_latest_with_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timestamps = iter(["2026-10-21T00:00:01Z", "2026-10-21T00:00:02Z", "2026-10-21T00:00:03Z"])
    monkeypatch.setattr("workspace_agent.store.utc_now", lambda: next(timestamps))
    store = RunStore(tmp_path / "runs.sqlite3")
    first = TaskState(goal="first", workspace="sandbox")
    second = TaskState(goal="second", workspace="sandbox")
    store.save(first)
    store.save(second)
    first.status = "completed"
    first.final_result = "最新完成结果"
    store.save(first)

    assert [run.run_id for run in store.list_runs()] == [first.run_id, second.run_id]
    assert [run.run_id for run in store.list_runs(limit=1)] == [first.run_id]
    assert store.list_runs(limit=0) == []
    assert store.load(first.run_id).final_result == "最新完成结果"


def test_load_unknown_run_and_parameterized_run_id(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    state = TaskState(run_id="run'; DROP TABLE runs; --", goal="literal ID", workspace="sandbox")
    store.save(state)

    assert store.load(state.run_id).goal == "literal ID"
    with pytest.raises(KeyError, match="Run not found"):
        store.load("missing")
    assert len(store.list_runs()) == 1


def test_recover_running_state_reports_inflight_call_and_never_replays(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    artifact = tmp_path / "artifact.md"
    artifact.write_text("已发生的部分写入", encoding="utf-8")
    state = TaskState(
        goal="write artifact",
        workspace=str(tmp_path),
        tool_history=[
            ToolEvent(
                call_id="finished",
                name="read_file",
                arguments={"relative_path": "notes.md"},
                result={"ok": True, "data": {"content": "RAG"}},
                finished_at="2026-10-21T00:00:00Z",
            ),
            ToolEvent(
                call_id="inflight",
                name="write_file",
                arguments={"relative_path": "artifact.md", "content": "do not replay"},
            ),
        ],
    )
    store.save(state)

    recovered = RunStore(store.path).recover(state.run_id)

    assert recovered.status == "interrupted"
    assert recovered.errors[-1] == {
        "code": "RECOVERED_INTERRUPTION",
        "uncertain_calls": ["write_file"],
    }
    assert recovered.tool_history[-1].result is None
    assert recovered.tool_history[-1].finished_at is None
    assert artifact.read_text(encoding="utf-8") == "已发生的部分写入"
    assert store.load(state.run_id).model_dump() == recovered.model_dump()
    assert store.recover(state.run_id).model_dump() == recovered.model_dump()


@pytest.mark.parametrize(
    "status", ["completed", "preview", "failed", "budget_exceeded", "interrupted"]
)
def test_recover_terminal_run_is_unchanged(tmp_path: Path, status: str) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    state = TaskState(goal="already stopped", workspace="sandbox", status=status)
    store.save(state)

    assert store.recover(state.run_id).model_dump() == state.model_dump()

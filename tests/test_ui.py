"""The terminal view displays persisted facts and never creates execution facts."""

import hashlib
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from workspace_agent import ui
from workspace_agent.domain import Step, TaskState, ToolEvent
from workspace_agent.models import ScriptedMockModel
from workspace_agent.runtime import AgentRuntime
from workspace_agent.store import RunStore
from workspace_agent.tools import ToolDispatcher


def rendered(state: TaskState) -> str:
    stream = StringIO()
    Console(file=stream, width=220, color_system=None, force_terminal=False).print(
        ui.render_state(state)
    )
    return stream.getvalue()


def artifact_section(output: str) -> str:
    return output.split("写入时已核验的产物", 1)[1].split("最终结果文本", 1)[0]


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "state" / "runs.sqlite3")


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    stream = StringIO()
    monkeypatch.setattr(
        ui, "console", Console(file=stream, width=220, color_system=None, force_terminal=False)
    )
    return stream


def test_snapshot_displays_actual_plan_timeline_revisions_and_errors() -> None:
    state = TaskState(
        goal="GOAL_SENTINEL_482",
        workspace="authorized_workspace",
        status="failed",
        plan=[Step(description="PLAN_SENTINEL_573", status="completed")],
        plan_revisions=["REVISION_SENTINEL_284"],
        tool_history=[
            ToolEvent(
                call_id="real-call-17",
                name="read_file",
                arguments={"relative_path": "notes/actual.md"},
                result={"ok": True, "data": {"content": "OBSERVATION_SENTINEL_731"}},
            ),
            ToolEvent(
                call_id="real-call-18",
                name="read_file",
                arguments={"relative_path": "notes/missing.md"},
                result={
                    "ok": False,
                    "error": {
                        "code": "FILE_NOT_FOUND",
                        "message": "ACTUAL_ERROR_SENTINEL_782",
                    },
                },
            ),
        ],
        errors=[{"code": "FILE_NOT_FOUND"}],
        messages=[{"role": "system", "content": "PRIVATE_SYSTEM_SENTINEL_945"}],
        final_result="FINAL_SENTINEL_491",
        iterations=3,
        tokens_used=127,
        elapsed_seconds=1.25,
    )

    result = rendered(state)

    for marker in [
        state.run_id,
        "failed",
        state.goal,
        state.workspace,
        "PLAN_SENTINEL_573",
        "REVISION_SENTINEL_284",
        "real-call-17",
        "read_file",
        "notes/actual.md",
        "OBSERVATION_SENTINEL_731",
        "FILE_NOT_FOUND",
        "ACTUAL_ERROR_SENTINEL_782",
        "FINAL_SENTINEL_491",
        "3/12",
        "2/30",
        "127/24000",
        "1.25/90s",
    ]:
        assert marker in result
    assert "PRIVATE_SYSTEM_SENTINEL_945" not in result
    assert "检查授权目录，定位与目标相关的材料" not in result


def test_markup_and_terminal_control_sequences_are_literal_data() -> None:
    state = TaskState(
        goal="[bold]GOAL[/bold]",
        workspace="[link=https://example.invalid]workspace[/link]",
        plan=[Step(description="[red]PLAN[/red]")],
        final_result="[bold]RESULT[/bold]\x1b]0;unsafe-title\x07",
    )

    result = rendered(state)

    assert "[bold]GOAL[/bold]" in result
    assert "[red]PLAN[/red]" in result
    assert "[link=https://example.invalid]workspace[/link]" in result
    assert "[bold]RESULT[/bold]" in result
    assert "\\x1b]0;unsafe-title\\x07" in result
    assert "\x1b" not in result


def verified_write() -> ToolEvent:
    digest = hashlib.sha256(b"actual artifact").hexdigest()
    return ToolEvent(
        call_id="verified-write",
        name="write_file",
        arguments={"relative_path": "artifact.md", "content": "actual artifact"},
        result={
            "ok": True,
            "data": {"written": True, "preview": False, "path": "artifact.md", "sha256": digest},
            "evidence": [
                {
                    "kind": "file_write",
                    "verified": True,
                    "exists": True,
                    "path": "artifact.md",
                    "sha256": digest,
                }
            ],
        },
    )


def test_only_matching_verified_write_evidence_is_listed_as_artifact() -> None:
    event = verified_write()
    state = TaskState(goal="test evidence", workspace="sandbox", tool_history=[event])

    section = artifact_section(rendered(state))

    assert "artifact.md" in section
    assert event.result["data"]["sha256"] in section
    assert "无已核验" not in section


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_evidence",
        "preview",
        "failed",
        "unverified",
        "missing_exists",
        "digest_mismatch",
        "path_mismatch",
        "wrong_kind",
        "invalid_digest",
        "not_written",
        "wrong_tool",
    ],
)
def test_unverified_preview_or_inconsistent_results_are_not_artifacts(invalid: str) -> None:
    event = verified_write()
    result = event.result
    data = result["data"]
    evidence = result["evidence"][0]
    if invalid == "missing_evidence":
        result["evidence"] = []
    elif invalid == "preview":
        data["preview"] = True
    elif invalid == "failed":
        result["ok"] = False
    elif invalid == "unverified":
        evidence["verified"] = False
    elif invalid == "missing_exists":
        evidence.pop("exists")
    elif invalid == "digest_mismatch":
        evidence["sha256"] = "0" * 64
    elif invalid == "path_mismatch":
        evidence["path"] = "different.md"
    elif invalid == "wrong_kind":
        evidence["kind"] = "model_claim"
    elif invalid == "invalid_digest":
        data["sha256"] = evidence["sha256"] = "not-a-hash"
    elif invalid == "not_written":
        data["written"] = False
    elif invalid == "wrong_tool":
        event.name = "read_file"
    state = TaskState(
        goal="artifact.md",
        workspace="sandbox",
        tool_history=[event],
        final_result="Model claims artifact.md exists; this text supplies no evidence.",
    )

    section = artifact_section(rendered(state))

    assert "无已核验的写入产物" in section
    assert "artifact.md" not in section


@pytest.mark.parametrize("approve_writes", [False, True])
async def test_real_mock_run_is_rendered_from_saved_state_and_actual_write_evidence(
    tmp_path: Path, store: RunStore, output: StringIO, approve_writes: bool
) -> None:
    workspace = tmp_path / "sandbox"
    (workspace / "notes").mkdir(parents=True)
    (workspace / "notes" / "rag.md").write_text(
        "RAG UI_EVIDENCE_SENTINEL_641：检索评估应记录实际来源。\n", encoding="utf-8"
    )
    state = await AgentRuntime(
        ScriptedMockModel(), ToolDispatcher(workspace, approve_writes=approve_writes), store
    ).run("根据 RAG 笔记生成学习计划", str(workspace))

    ui.view(RunStore(store.path), state.run_id)

    result = output.getvalue()
    assert state.run_id in result
    assert "read_file" in result and "write_file" in result
    assert "UI_EVIDENCE_SENTINEL_641" in result
    if approve_writes:
        artifact = workspace / "study_plan.md"
        assert artifact.exists()
        assert "study_plan.md" in artifact_section(result)
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() in artifact_section(result)
    else:
        assert not (workspace / "study_plan.md").exists()
        assert "PREVIEW · 未写入" in result
        assert "无已核验的写入产物" in artifact_section(result)


def test_view_selects_latest_run_by_default(store: RunStore, output: StringIO) -> None:
    first = TaskState(goal="OLDER_SENTINEL_218", workspace="sandbox", status="completed")
    latest = TaskState(goal="LATEST_SENTINEL_652", workspace="sandbox", status="preview")
    store.save(first)
    store.save(latest)

    ui.view(store)

    assert latest.run_id in output.getvalue()
    assert "LATEST_SENTINEL_652" in output.getvalue()
    assert "OLDER_SENTINEL_218" not in output.getvalue()


@pytest.mark.parametrize("run_id", [None, "unknown-run"])
def test_missing_run_has_value_error_boundary(store: RunStore, run_id: str | None) -> None:
    with pytest.raises(ValueError):
        ui.view(store, run_id)


@pytest.mark.parametrize("watch,status", [(False, "running"), (True, "completed")])
def test_snapshot_and_terminal_watch_do_not_poll_or_change_state(
    store: RunStore, output: StringIO, monkeypatch: pytest.MonkeyPatch, watch: bool, status: str
) -> None:
    state = TaskState(goal="SNAPSHOT_SENTINEL_491", workspace="sandbox", status=status)
    store.save(state)

    def unexpected_sleep(_seconds: float) -> None:
        raise AssertionError("A snapshot must not poll")

    monkeypatch.setattr(ui, "time", SimpleNamespace(sleep=unexpected_sleep))
    ui.view(store, state.run_id, watch=watch)

    assert "SNAPSHOT_SENTINEL_491" in output.getvalue()
    assert store.load(state.run_id).model_dump() == state.model_dump()


def test_watch_refreshes_pinned_run_and_exits_on_terminal_status(
    store: RunStore, output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = TaskState(goal="WATCHED_SENTINEL_142", workspace="sandbox")
    store.save(watched)
    sleeps: list[float] = []

    def advance(seconds: float) -> None:
        sleeps.append(seconds)
        watched.status = "completed"
        watched.final_result = "REAL_FINAL_SENTINEL_271"
        store.save(watched)
        store.save(TaskState(goal="UNRELATED_LATEST_982", workspace="sandbox", status="completed"))

    monkeypatch.setattr(ui, "time", SimpleNamespace(sleep=advance))
    ui.view(store, watch=True)

    assert sleeps == [0.25]
    assert "REAL_FINAL_SENTINEL_271" in output.getvalue()
    assert "UNRELATED_LATEST_982" not in output.getvalue()


def test_ctrl_c_stops_viewing_without_recovering_or_mutating_inflight_state(
    store: RunStore, output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = TaskState(
        goal="watch without replay",
        workspace="sandbox",
        tool_history=[
            ToolEvent(
                call_id="inflight",
                name="write_file",
                arguments={"relative_path": "possible.md", "content": "uncertain write"},
            )
        ],
    )
    store.save(state)

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(ui, "time", SimpleNamespace(sleep=interrupt))
    ui.view(store, state.run_id, watch=True)

    assert "INFLIGHT" in output.getvalue()
    assert "结果可能不确定" in output.getvalue()
    assert "已停止查看" in output.getvalue()
    assert store.load(state.run_id).model_dump() == state.model_dump()

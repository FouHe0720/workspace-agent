"""The campus filing scenario uses live sandbox reads and existing write policy."""

import hashlib
import json
from importlib.resources import files
from pathlib import Path

from typer.testing import CliRunner

from workspace_agent.campus import CampusDeskMockModel
from workspace_agent.cli import _init_demo, app
from workspace_agent.runtime import AgentRuntime
from workspace_agent.store import RunStore
from workspace_agent.tools import ToolDispatcher


async def test_campus_preview_then_write_is_grounded_in_actual_sources(tmp_path: Path) -> None:
    root = tmp_path / "campus"
    _init_demo(root, "campus")
    store = RunStore(tmp_path / "runs.sqlite3")
    preview = await AgentRuntime(CampusDeskMockModel(), ToolDispatcher(root), store).run(
        "整理迎新材料", str(root)
    )
    assert preview.status == "preview"
    assert not (root / "campus_desk.md").exists()
    written = await AgentRuntime(
        CampusDeskMockModel(), ToolDispatcher(root, approve_writes=True), store
    ).run("整理迎新材料", str(root))
    assert written.status == "completed"
    output = (root / "campus_desk.md").read_text()
    assert "2024 年历史材料" in output
    assert "不含翻译学院" in output
    assert "无需选择全校通选课程和通识核心课程" in output
    for event in written.tool_history:
        if event.name == "read_file" and event.result and event.result["ok"]:
            data = event.result["data"]
            assert data["path"] in output and data["sha256"] in output
            assert data["sha256"] == hashlib.sha256((root / data["path"]).read_bytes()).hexdigest()
    write = next(event for event in written.tool_history if event.name == "write_file")
    assert write.result["data"]["sha256"] == hashlib.sha256(output.encode()).hexdigest()
    denied = await AgentRuntime(
        CampusDeskMockModel(), ToolDispatcher(root, approve_writes=True), store
    ).run("整理迎新材料", str(root))
    assert any(error["code"] == "OVERWRITE_DENIED" for error in denied.errors)
    assert (root / "campus_desk.md").read_text() == output


async def test_modified_input_is_reflected_in_output_not_a_packaged_canned_answer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "campus"
    _init_demo(root, "campus")
    source = root / "materials/english-placement-2024.md"
    source.write_text(
        source.read_text() + "\n## 原文第 99 段\n\n考试时间：测试变更标记 CAMPUS_CHANGE\n"
    )
    state = await AgentRuntime(
        CampusDeskMockModel(),
        ToolDispatcher(root, approve_writes=True),
        RunStore(tmp_path / "runs.sqlite3"),
    ).run("整理迎新材料", str(root))
    assert state.status == "completed"
    assert "CAMPUS_CHANGE" in (root / "campus_desk.md").read_text()
    assert "原 DOCX 第 99 段" in (root / "campus_desk.md").read_text()


async def test_no_matching_material_produces_no_artifact(tmp_path: Path) -> None:
    root = tmp_path / "campus"
    (root / "materials").mkdir(parents=True)
    state = await AgentRuntime(
        CampusDeskMockModel(),
        ToolDispatcher(root, approve_writes=True),
        RunStore(tmp_path / "runs.sqlite3"),
    ).run("整理迎新材料", str(root))
    assert "未能全部读取" in state.final_result
    assert not (root / "campus_desk.md").exists()
    assert not any(event.name == "write_file" for event in state.tool_history)


def test_bundled_campus_manifest_hashes_and_original_paragraphs() -> None:
    fixtures = files("workspace_agent").joinpath("fixtures/campus")
    manifest = json.loads(fixtures.joinpath("manifest.json").read_text())
    for source in manifest["documents"]:
        content = fixtures.joinpath(source["file_name"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["excerpt_sha256"]
        for paragraph in source["paragraphs"]:
            assert paragraph["text"] in content.decode()
        assert "phone" not in source


def test_cli_campus_scenario_and_initializer_preserve_existing_material(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "campus"
    result = runner.invoke(app, ["init-demo", "--scenario", "campus", "--workspace", str(root)])
    assert result.exit_code == 0, result.output
    source = root / "materials/course-selection-2024.md"
    original = source.read_bytes()
    result = runner.invoke(app, ["init-demo", "--scenario", "campus", "--workspace", str(root)])
    assert result.exit_code == 0 and source.read_bytes() == original
    result = runner.invoke(
        app,
        [
            "run",
            "整理迎新材料",
            "--scenario",
            "campus",
            "--workspace",
            str(root),
            "--db",
            str(tmp_path / "runs.sqlite3"),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "尚未写入" in result.output
    assert not (root / "campus_desk.md").exists()


async def test_truncated_search_does_not_publish_partial_materials(tmp_path: Path) -> None:
    root = tmp_path / "campus"
    (root / "materials").mkdir(parents=True)
    (root / "materials/many-matches.md").write_text("2024\n" * 31)
    state = await AgentRuntime(
        CampusDeskMockModel(),
        ToolDispatcher(root, approve_writes=True),
        RunStore(tmp_path / "runs.sqlite3"),
    ).run("整理迎新材料", str(root))
    assert "搜索结果不完整" in state.final_result
    assert not any(event.name == "write_file" for event in state.tool_history)
    assert not (root / "campus_desk.md").exists()

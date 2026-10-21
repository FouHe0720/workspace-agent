"""Check real CLI configuration, repeatable initialization and write authorization."""

from pathlib import Path

from typer.testing import CliRunner

from workspace_agent.cli import app

runner = CliRunner()


def test_init_run_preview_write_and_explicit_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    db = tmp_path / "runs.sqlite3"
    init = runner.invoke(app, ["init-demo", "--workspace", str(root)])
    assert init.exit_code == 0, init.output
    note = root / "notes" / "rag.md"
    original = note.read_bytes()
    repeated = runner.invoke(app, ["init-demo", "--workspace", str(root)])
    assert repeated.exit_code == 0
    assert note.read_bytes() == original
    args = ["run", "整理 RAG 笔记", "--workspace", str(root), "--db", str(db)]
    preview = runner.invoke(app, args + ["--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert not (root / "study_plan.md").exists()
    written = runner.invoke(app, args + ["--approve-writes"])
    assert written.exit_code == 0, written.output
    assert (root / "study_plan.md").is_file()
    denied = runner.invoke(app, args + ["--approve-writes"])
    assert denied.exit_code == 1
    assert "OVERWRITE_DENIED" in denied.output
    overwrite = runner.invoke(app, args + ["--approve-writes", "--allow-overwrite"])
    assert overwrite.exit_code == 0, overwrite.output


def test_invalid_configuration_and_missing_workspace_have_no_traceback(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "read notes", "--workspace", str(tmp_path / "absent")])
    assert result.exit_code == 2
    assert "FILE_NOT_FOUND" in result.output
    assert "Traceback" not in result.output
    result = runner.invoke(app, ["run", "task", "--dry-run", "--approve-writes"])
    assert result.exit_code == 2


def test_initializer_rejects_symlink_without_touching_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(outside, target_is_directory=True)
    result = runner.invoke(app, ["init-demo", "--workspace", str(link)])
    assert result.exit_code == 2
    assert not list(outside.iterdir())

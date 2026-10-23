"""CLI: explicit workspace authorization and write policy, no hidden shell tools."""

import asyncio
import json
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from workspace_agent.campus import CampusDeskMockModel
from workspace_agent.domain import Budget
from workspace_agent.models import ModelError, OpenAICompatibleModel, ScriptedMockModel
from workspace_agent.runtime import AgentRuntime
from workspace_agent.sandbox import SandboxError
from workspace_agent.store import RunStore
from workspace_agent.tools import ToolDispatcher

app = typer.Typer(no_args_is_help=True, help="Workspace Task Agent：受限工作空间任务代理")
console = Console(markup=False)


@app.command("init-demo")
def init_demo(workspace: Path = Path("demo_workspace"), scenario: str = "notes") -> None:
    """Create a dedicated demo directory with notes or historical campus excerpts."""
    try:
        _init_demo(workspace, scenario)
    except (SandboxError, OSError) as exc:
        console.print(f"初始化失败：{getattr(exc, 'code', type(exc).__name__)}")
        raise typer.Exit(2) from None


def _init_demo(workspace: Path, scenario: str = "notes") -> None:
    if scenario not in {"notes", "campus"}:
        raise typer.BadParameter("--scenario 仅支持 notes 或 campus")
    folder = "materials" if scenario == "campus" else "notes"
    fixture = "campus" if scenario == "campus" else "notes"
    if workspace.is_symlink() or any(p.is_symlink() for p in workspace.absolute().parents):
        raise typer.BadParameter("workspace 不能通过符号链接访问")
    workspace.mkdir(parents=True, exist_ok=True)
    dispatcher = ToolDispatcher(workspace, approve_writes=True)
    if (workspace / folder).is_symlink():
        raise typer.BadParameter(f"{folder} 不能是符号链接")
    (workspace / folder).mkdir(exist_ok=True)
    for item in files("workspace_agent").joinpath(f"fixtures/{fixture}").iterdir():
        if item.name.endswith((".md", ".json")):
            result = dispatcher.dispatch(
                "write_file",
                {
                    "relative_path": f"{folder}/{item.name}",
                    "content": item.read_text(encoding="utf-8"),
                },
            )
            if not result.ok and (
                result.error is None
                or result.error.code not in {"ALREADY_EXISTS", "FILE_EXISTS", "OVERWRITE_DENIED"}
            ):
                console.print(result.model_dump_json())
                raise typer.Exit(1)
    console.print("示例材料已准备：" + str(workspace))


@app.command()
def run(
    goal: Annotated[str, typer.Argument(min=1, max=4000)],
    workspace: Path = Path("demo_workspace"),
    model: str = "mock",
    scenario: str = "notes",
    dry_run: bool = False,
    approve_writes: bool = False,
    allow_overwrite: bool = False,
    max_iterations: int = 12,
    max_tool_calls: int = 30,
    max_tokens: int = 24000,
    timeout: float = 90,
    db: Path = Path(".agent/runs.sqlite3"),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run Mock or compatible function calling. Writes default to preview."""
    if dry_run and approve_writes:
        raise typer.BadParameter("--dry-run 与 --approve-writes 不能同时使用")
    if allow_overwrite and not approve_writes:
        raise typer.BadParameter("--allow-overwrite 需要 --approve-writes")
    if model not in {"mock", "api"}:
        raise typer.BadParameter("--model 仅支持 mock 或 api")
    if scenario not in {"notes", "campus"}:
        raise typer.BadParameter("--scenario 仅支持 notes 或 campus")
    try:
        dispatcher = ToolDispatcher(
            workspace, approve_writes=approve_writes, allow_overwrite=allow_overwrite
        )
        if model == "api":
            backend = OpenAICompatibleModel.from_env()
        elif scenario == "campus":
            backend = CampusDeskMockModel(overwrite=allow_overwrite)
        else:
            backend = ScriptedMockModel(overwrite=allow_overwrite)
        budget = Budget(
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls,
            max_tokens=max_tokens,
            timeout_seconds=timeout,
        )
        seen: set[str] = set()

        def event(state):
            if json_output:
                return
            if "plan" not in seen:
                console.print("计划：")
                for i, step in enumerate(state.plan, 1):
                    console.print(f"  {i}. {step.description}")
                seen.add("plan")
            for item in state.tool_history:
                if item.result is not None and item.call_id not in seen:
                    seen.add(item.call_id)
                    summary = json.dumps(item.arguments, ensure_ascii=False)
                    if len(summary) > 180:
                        summary = summary[:180] + "…"
                    code = "OK" if item.result["ok"] else item.result["error"]["code"]
                    console.print(f"工具 {item.name} {summary} → {code}")
            for i, revision in enumerate(state.plan_revisions):
                key = f"revision:{i}"
                if key not in seen:
                    console.print("计划调整：" + revision)
                    seen.add(key)

        runtime = AgentRuntime(backend, dispatcher, RunStore(db), budget, event)
        state = asyncio.run(runtime.run(goal, str(workspace.resolve())))
    except (ValueError, ModelError, SandboxError, OSError) as exc:
        console.print(f"配置/权限错误：{getattr(exc, 'code', type(exc).__name__)}")
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        console.print("已中断，状态保存在本地 runs 数据库。")
        raise typer.Exit(130) from None
    if json_output:
        print(state.model_dump_json(indent=2))
    else:
        console.print(f"Run {state.run_id} | {state.status}")
        console.print(state.final_result)
        for item in state.tool_history:
            data = (item.result or {}).get("data", {})
            if item.name == "write_file" and data.get("written"):
                console.print("Artifact: " + str(workspace / data["path"]))
    if state.status not in {"completed", "preview"}:
        raise typer.Exit(1)


@app.command()
def runs(db: Path = Path(".agent/runs.sqlite3")) -> None:
    """List actual persisted runs."""
    table = Table("Run ID", "Status", "Goal")
    for state in RunStore(db).list_runs():
        table.add_row(state.run_id, state.status, state.goal[:70])
    console.print(table)


@app.command()
def inspect(run_id: str, db: Path = Path(".agent/runs.sqlite3")) -> None:
    """Print a JSON snapshot without replaying any tool."""
    try:
        console.print(RunStore(db).load(run_id).model_dump_json(indent=2))
    except KeyError:
        console.print("Run 不存在")
        raise typer.Exit(1) from None


@app.command()
def recover(run_id: str, db: Path = Path(".agent/runs.sqlite3")) -> None:
    """Mark a stale running snapshot interrupted; no automatic side effects."""
    try:
        console.print(RunStore(db).recover(run_id).model_dump_json(indent=2))
    except KeyError:
        raise typer.BadParameter("Run 不存在") from None


@app.command("mcp-demo")
def mcp_demo(workspace: Path = Path("demo_workspace"), timeout: float = 15) -> None:
    """Start the official MCP stdio subprocess and compare native/MCP results."""
    from workspace_agent.mcp_client import MCPClientError, run_mcp_demo

    try:
        result = asyncio.run(run_mcp_demo(workspace, timeout=timeout))
    except (MCPClientError, SandboxError) as exc:
        console.print(getattr(exc, "code", "MCP_ERROR"))
        raise typer.Exit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_match"]:
        raise typer.Exit(1)


@app.command()
def tui(
    run_id: Annotated[str | None, typer.Argument()] = None,
    watch: bool = False,
    db: Path = Path(".agent/runs.sqlite3"),
) -> None:
    """View actual plan progress, tool timeline and verified artifact evidence."""
    from workspace_agent.ui import view

    try:
        view(RunStore(db), run_id=run_id, watch=watch)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()

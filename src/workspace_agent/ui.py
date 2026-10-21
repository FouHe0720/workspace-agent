"""A read-only Rich view of persisted execution facts, never private reasoning."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from workspace_agent.domain import TaskState
from workspace_agent.store import RunStore

console = Console(markup=False)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _plain(value: Any, limit: int | None = None) -> Text:
    """Render markup literally and escape terminal control sequences from stored data."""
    content = str(value)
    content = "".join(
        f"\\x{ord(char):02x}"
        if (ord(char) < 32 and char not in "\n\t") or 127 <= ord(char) <= 159
        else char
        for char in content
    )
    if limit is not None and len(content) > limit:
        content = content[:limit] + "…（已截断，完整内容见 inspect）"
    return Text(content)


def _snippet(value: Any, limit: int = 240) -> Text:
    serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return _plain(serialized, limit)


def _verified_artifacts(state: TaskState) -> list[tuple[str, str]]:
    """Only consistent write evidence is an artifact; model text is never evidence."""
    artifacts: dict[str, str] = {}
    for event in state.tool_history:
        result = event.result or {}
        data = result.get("data", {})
        if event.name != "write_file" or result.get("ok") is not True:
            continue
        if data.get("written") is not True or data.get("preview") is True:
            continue
        for evidence in result.get("evidence", []):
            path, digest = evidence.get("path"), evidence.get("sha256")
            if (
                evidence.get("kind") == "file_write"
                and evidence.get("verified") is True
                and evidence.get("exists") is True
                and isinstance(path, str)
                and isinstance(digest, str)
                and _SHA256.fullmatch(digest)
                and path == data.get("path")
                and digest == data.get("sha256")
            ):
                artifacts[path] = digest
    return list(artifacts.items())


def render_state(state: TaskState) -> RenderableType:
    """Build a snapshot from real state fields; no tools or filesystem writes occur."""
    heading = Text()
    heading.append_text(_plain(f"Run: {state.run_id}\nStatus: {state.status}\n"))
    heading.append_text(_plain(f"目标: {state.goal}\nWorkspace: {state.workspace}", 5000))
    sections: list[RenderableType] = [Panel(heading, title="Workspace Task Agent · 只读视图")]

    budget = Table.grid(padding=(0, 3))
    budget.add_row(
        _plain(f"迭代 {state.iterations}/{state.budget.max_iterations}"),
        _plain(f"工具 {len(state.tool_history)}/{state.budget.max_tool_calls}"),
        _plain(f"Token 预算计数 {state.tokens_used}/{state.budget.max_tokens}"),
        _plain(f"已记录耗时 {state.elapsed_seconds:.2f}/{state.budget.timeout_seconds:g}s"),
    )
    if state.token_charges:
        sources = ", ".join(
            dict.fromkeys(str(item.get("source", "")) for item in state.token_charges)
        )
        budget.add_row(_plain("计数来源: " + sources, 300))
    sections.append(Panel(budget, title="预算与记录"))

    plan = Table("步骤", "状态", "已保存的计划", expand=True)
    for index, step in enumerate(state.plan, 1):
        plan.add_row(_plain(index), _plain(step.status), _plain(step.description, 1000))
    sections.append(Panel(plan if state.plan else Text("尚无已保存的计划"), title="计划进度"))
    if state.plan_revisions:
        sections.append(
            Panel(
                Group(*[_plain(f"• {revision}", 1000) for revision in state.plan_revisions]),
                title="根据观察调整计划",
            )
        )

    timeline = Table("#", "工具与参数", "实际观察", expand=True)
    for index, event in enumerate(state.tool_history, 1):
        proposal = Group(_plain(f"{event.name} · {event.call_id}"), _snippet(event.arguments))
        if event.result is None:
            observation: RenderableType = Text("INFLIGHT · 尚无完成记录，结果可能不确定")
        else:
            result = event.result
            if result.get("ok") is True:
                data = result.get("data", {})
                label = "PREVIEW · 未写入" if data.get("preview") is True else "OK"
                observation = Group(Text(label), _snippet(data, 360))
            else:
                error = result.get("error") or {}
                observation = Group(
                    _plain(f"ERROR · {error.get('code', 'UNKNOWN')}"),
                    _plain(error.get("message", ""), 360),
                )
        timeline.add_row(_plain(index), proposal, observation)
    sections.append(
        Panel(timeline if state.tool_history else Text("尚无工具调用记录"), title="工具调用时间线")
    )

    artifacts = Table("文件", "SHA-256", expand=True)
    verified = _verified_artifacts(state)
    for path, digest in verified:
        artifacts.add_row(_plain(path), _plain(digest))
    sections.append(
        Panel(
            artifacts if verified else Text("无已核验的写入产物；预览不代表文件已创建。"),
            title="写入时已核验的产物",
        )
    )
    if state.errors:
        sections.append(
            Panel(Group(*[_snippet(error, 500) for error in state.errors]), title="已记录的错误")
        )
    sections.append(
        Panel(
            _plain(state.final_result, 8000) if state.final_result else Text("尚无最终结果文本"),
            title="最终结果文本（产物以核验证据为准）",
        )
    )
    return Group(*sections)


def _load(store: RunStore, run_id: str | None) -> TaskState:
    if run_id is None:
        latest = store.list_runs(limit=1)
        if not latest:
            raise ValueError("没有已保存的运行；请先执行 agent run。")
        return latest[0]
    try:
        return store.load(run_id)
    except KeyError:
        raise ValueError("Run 不存在。") from None


def view(store: RunStore, run_id: str | None = None, watch: bool = False) -> None:
    """Show one persisted run; watching never resumes, recovers, or changes it."""
    state = _load(store, run_id)
    if not watch or state.status != "running":
        console.print(render_state(state))
        return
    try:
        with Live(render_state(state), console=console, refresh_per_second=4) as live:
            while state.status == "running":
                time.sleep(0.25)
                state = _load(store, state.run_id)
                live.update(render_state(state), refresh=True)
    except KeyboardInterrupt:
        console.print(Text("已停止查看；运行与保存状态未被修改。"))

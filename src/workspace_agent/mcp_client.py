"""Minimal MCP stdio client with fixed subprocess, bounded lifetime and parity demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, StdioServerParameters
from pydantic import ValidationError

from workspace_agent.sandbox import SandboxError
from workspace_agent.tools import ToolDispatcher, ToolResult


class MCPClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def server_parameters(
    workspace: Path | str,
    *,
    approve_writes: bool = False,
    allow_overwrite: bool = False,
) -> StdioServerParameters:
    """Never accept arbitrary executable strings or inherit provider credentials.

    MCP itself inherits only HOME/LOGNAME/PATH/SHELL/TERM/USER on POSIX. The
    explicit env adds no API key, proxy, PYTHONPATH, or other parent secret.
    Python isolated mode also prevents imports from an untrusted current directory.
    """
    if allow_overwrite and not approve_writes:
        raise MCPClientError(
            "MCP_CONFIGURATION_ERROR", "Overwrite permission requires write approval"
        )
    args = [
        "-I",
        "-m",
        "workspace_agent.mcp_server",
        "--workspace",
        str(Path(workspace).expanduser().absolute()),
    ]
    if approve_writes:
        args.append("--approve-writes")
    if allow_overwrite:
        args.append("--allow-overwrite")
    return StdioServerParameters(command=sys.executable, args=args, env={"PYTHONUNBUFFERED": "1"})


class WorkspaceMCPClient:
    """A connected client facade; construct through connect_workspace()."""

    def __init__(self, client: Client, timeout: float) -> None:
        self._client = client
        self._timeout = timeout

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._client.list_tools()
        return [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = await self._client.call_tool(name, arguments, read_timeout_seconds=self._timeout)
        try:
            parsed = ToolResult.model_validate(result.structured_content, strict=True)
        except ValidationError:
            raise MCPClientError(
                "MCP_PROTOCOL_ERROR", "MCP server returned an invalid structured tool result"
            ) from None
        if result.is_error == parsed.ok:
            raise MCPClientError(
                "MCP_PROTOCOL_ERROR", "MCP tool result status does not match its structured content"
            )
        return parsed


@asynccontextmanager
async def connect_workspace(
    workspace: Path | str,
    *,
    approve_writes: bool = False,
    allow_overwrite: bool = False,
    timeout: float = 15.0,  # noqa: ASYNC109 - enforced by fail_after around the entire lifecycle.
) -> AsyncIterator[WorkspaceMCPClient]:
    """Bound the complete connection/call lifecycle; SDK cleans up the subprocess."""
    if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise MCPClientError("MCP_CONFIGURATION_ERROR", "MCP timeout must be within 0..120 seconds")
    params = server_parameters(
        workspace, approve_writes=approve_writes, allow_overwrite=allow_overwrite
    )
    try:
        with anyio.fail_after(timeout):
            async with Client(params, read_timeout_seconds=timeout) as client:
                yield WorkspaceMCPClient(client, timeout)
    except MCPClientError:
        raise
    except TimeoutError:
        raise MCPClientError("MCP_TIMEOUT", "MCP connection or request timed out") from None
    except Exception:
        # SDK exceptions can carry subprocess details. Expose a stable safe boundary.
        raise MCPClientError("MCP_CONNECTION_ERROR", "MCP connection or request failed") from None


async def run_mcp_demo(
    workspace: Path | str,
    *,
    timeout: float = 15.0,  # noqa: ASYNC109 - forwarded to connect_workspace's fail_after scope.
) -> dict[str, Any]:
    """Compare actual stdio results against native dispatch, including rejected input."""
    try:
        dispatcher = ToolDispatcher(workspace)
    except SandboxError as exc:
        raise MCPClientError("MCP_CONFIGURATION_ERROR", f"Workspace rejected: {exc.code}") from None
    requests = [
        ("list_files", {"relative_path": "."}),
        ("read_file", {"relative_path": "notes/rag.md"}),
        ("search_files", {"query": "RAG", "glob": "*.md", "max_results": 5}),
        (
            "write_file",
            {"relative_path": "mcp_preview.md", "content": "# MCP preview\n", "overwrite": False},
        ),
        ("read_file", {"relative_path": "../outside.md"}),
        ("search_files", {"query": "RAG", "max_results": "5"}),
    ]
    comparisons = []
    try:
        async with connect_workspace(workspace, timeout=timeout) as client:
            schemas = await client.list_tools()
            for name, arguments in requests:
                native = dispatcher.dispatch(name, arguments).model_dump(mode="json")
                remote = (await client.call_tool(name, arguments)).model_dump(mode="json")
                comparisons.append(
                    {
                        "name": name,
                        "arguments": arguments,
                        "native": native,
                        "mcp": remote,
                        "match": native == remote,
                    }
                )
    finally:
        dispatcher.sandbox.close()
    return {
        "transport": "stdio",
        "tools": [tool["name"] for tool in schemas],
        "comparisons": comparisons,
        "all_match": all(item["match"] for item in comparisons),
        "writes_approved": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare native dispatch with real MCP stdio")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    options = parser.parse_args()
    try:
        result = asyncio.run(run_mcp_demo(options.workspace, timeout=options.timeout))
    except MCPClientError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

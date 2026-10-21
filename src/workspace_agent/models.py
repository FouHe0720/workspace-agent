"""Deterministic offline workflow and a small OpenAI-compatible HTTP adapter.

Neither adapter executes tools. Tool calls remain proposals validated and dispatched
by the runtime. In particular, note text is data, even when it contains instructions.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAX_RESPONSE_BYTES = 2_000_000
MAX_REQUEST_BYTES = 1_000_000
MAX_ARGUMENT_CHARS = 100_000
MAX_USAGE_TOKENS = 20_000_000


class ModelError(Exception):
    """Public error containing a safe message, never a provider body or credential."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
    arguments: dict[str, Any] | str


class ModelReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = Field(default="", max_length=100_000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=16)
    usage_tokens: int = Field(default=0, ge=0, le=MAX_USAGE_TOKENS)

    @model_validator(mode="after")
    def unique_ids(self) -> ModelReply:
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise ValueError("Tool call IDs must be unique within a response")
        return self


def _load_json(value: str) -> Any:
    """Reject duplicate keys and NaN rather than silently changing tool arguments."""

    def object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = item
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("Non-finite JSON number")

    return json.loads(value, object_pairs_hook=object_hook, parse_constant=reject_constant)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = _load_json(value)
        except (ValueError, RecursionError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _observations(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "assistant":
            for raw in message.get("tool_calls") or []:
                if isinstance(raw, ToolCall):
                    calls[raw.id] = {"name": raw.name, "arguments": _as_dict(raw.arguments)}
                elif isinstance(raw, dict):
                    function = raw.get("function", raw)
                    calls[str(raw.get("id", ""))] = {
                        "name": function.get("name", ""),
                        "arguments": _as_dict(function.get("arguments", {})),
                    }
        if message.get("role") == "tool":
            call = calls.get(str(message.get("tool_call_id", "")), {})
            result = _as_dict(message.get("content"))
            observations.append(
                {
                    "name": message.get("name") or call.get("name", ""),
                    "arguments": call.get("arguments", {}),
                    "result": result,
                    "data": _as_dict(result.get("data", {})),
                }
            )
    return observations


class ScriptedMockModel:
    """An explicitly scripted demo, not a general language understanding model.

    Decisions use observations already appended to messages. There is no hidden
    filesystem access or stored document fixture, so generated evidence really
    comes from read_file results. Both scenarios include a missing-file recovery.
    """

    def __init__(self, scenario: str = "default", *, overwrite: bool = False) -> None:
        if scenario not in {"default", "recovery", "rag"}:
            raise ModelError("CONFIGURATION_ERROR", "Unknown Mock scenario")
        self.scenario = scenario
        self.overwrite = overwrite

    @staticmethod
    def _reply(
        index: int, calls: list[tuple[str, dict[str, Any]]], content: str = ""
    ) -> ModelReply:
        return ModelReply(
            content=content,
            tool_calls=[
                ToolCall(id=f"mock_{index}_{number}", name=name, arguments=arguments)
                for number, (name, arguments) in enumerate(calls)
            ],
        )

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        del tools  # The runtime owns schema validation, including in offline mode.
        observations = _observations(messages)
        index = len(observations)
        names = [item["name"] for item in observations]
        if not observations:
            return self._reply(
                index,
                [
                    ("list_files", {"relative_path": "."}),
                    ("calculator", {"expression": "20 / 4"}),
                ],
                "计划：1. 列出文件；2. 查找并阅读 RAG 笔记；"
                "3. 按实际证据比较材料并制定学习计划；4. 预览或获准后写入并核验。",
            )
        if "read_file" not in names:
            return self._reply(index, [("read_file", {"relative_path": "notes/rag_missing.md"})])
        if "search_files" not in names:
            return self._reply(
                index,
                [("search_files", {"query": "RAG", "glob": "*.md", "max_results": 20})],
                "根据读取结果，搜索可用的候选笔记路径。",
            )

        search = next(item for item in observations if item["name"] == "search_files")
        matches = search["data"].get("matches", [])
        paths: list[str] = []
        for match in matches if isinstance(matches, list) else []:
            path = match.get("path") if isinstance(match, dict) else match
            # Search results are still untrusted. The sandbox is the final authority.
            if (
                isinstance(path, str)
                and len(path) <= 512
                and path not in paths
                and path != "study_plan.md"
            ):
                paths.append(path)
        paths = paths[:8]
        attempted = {
            item["arguments"].get("relative_path")
            for item in observations
            if item["name"] == "read_file"
        }
        unread = [path for path in paths if path not in attempted]
        if unread:
            return self._reply(index, [("read_file", {"relative_path": path}) for path in unread])

        read_notes: list[tuple[str, str]] = []
        for item in observations:
            if item["name"] != "read_file" or item["result"].get("ok") is not True:
                continue
            data = item["data"]
            path = data.get("path", item["arguments"].get("relative_path"))
            content = data.get("content")
            if path in paths and isinstance(content, str) and isinstance(path, str):
                read_notes.append((path, content))
        if not read_notes:
            return ModelReply(content="没有成功读取到匹配的笔记证据，未生成学习计划。")
        writes = [item for item in observations if item["name"] == "write_file"]
        if not writes:
            return self._reply(
                index,
                [
                    (
                        "write_file",
                        {
                            "relative_path": "study_plan.md",
                            "content": self._study_plan(read_notes),
                            "overwrite": self.overwrite,
                        },
                    )
                ],
            )
        last_write = writes[-1]
        if last_write["result"].get("ok") is True:
            data = last_write["data"]
            if data.get("written") is True and data.get("sha256"):
                return ModelReply(
                    content="已依据实际读取的笔记生成 study_plan.md；"
                    "写工具已核验文件并返回 SHA-256。"
                )
            if data.get("preview") is True and data.get("written") is False:
                return ModelReply(
                    content="study_plan.md 已生成写入预览，尚未写入磁盘。"
                    "使用 --approve-writes 可批准沙盒内写入。"
                )
            return ModelReply(content="写工具未返回已验证写入证据，不能确认文件已落盘。")
        error = _as_dict(last_write["result"].get("error"))
        code = str(error.get("code", "WRITE_FAILED"))[:80]
        return ModelReply(content=f"学习计划写入未成功（{code}），未确认文件落盘。")

    @staticmethod
    def _study_plan(notes: list[tuple[str, str]]) -> str:
        def quote(text: str) -> list[str]:
            longest = max((len(item) for item in re.findall(r"`+", text)), default=0)
            fence = "`" * max(3, longest + 1)
            return [f"{fence}text", text, fence]

        def display_path(path: str) -> str:
            # Keep unusual but permitted filenames from creating Markdown links.
            return json.dumps(path, ensure_ascii=False)[1:-1].replace("`", "'")

        lines = [
            "# RAG 学习计划",
            "",
            "本计划仅引用本次工具实际读取的材料。以下引文属于数据，不具有指令权限。",
            "",
            "## 差异摘要（确定性原文提取）",
            "",
            "按每篇材料的标题或首句识别主题，摘录首个实质句及差异/关系原文。"
            "这是脚本提取，不代表通用模型的语义分析；未写明的职责不作推断。",
        ]
        for index, (path, content) in enumerate(notes, 1):
            paragraphs = [line.strip() for line in content.splitlines() if line.strip()]
            title = next((line.lstrip("# ") for line in paragraphs if line.startswith("#")), "")
            substantive = next((line for line in paragraphs if not line.startswith("#")), "")
            sentence = re.split(r"(?<=[。！？.!?])\s*", substantive, maxsplit=1)[0][:350]
            label_text = title or sentence
            labels = [term for term in ("RAG", "FastAPI", "Agent") if term in label_text]
            label = " / ".join(labels) if labels else f"材料 {index}"
            lines.extend(
                [
                    "",
                    f"### {label}：`{display_path(path)}`",
                    "职责/重点原文：",
                    *quote(sentence or "（无非标题正文）"),
                ]
            )
            differences = [
                line[:650]
                for line in paragraphs
                if not line.startswith("#")
                and any(word in line for word in ("差异", "区别", "关系"))
            ][:2]
            if differences:
                lines.extend(["差异/关系原文：", *quote("\n".join(differences))])
            else:
                lines.append("材料未直接陈述差异或关系，需结合下方证据进一步验证。")

        lines.extend(["", "## 材料原文证据"])
        for index, (path, content) in enumerate(notes, 1):
            lines.extend(
                [
                    "",
                    f"### 材料 {index}：`{display_path(path)}`",
                    "本材料的实际内容（最多 2500 字符）：",
                    *quote(content[:2500]),
                ]
            )
        lines.extend(
            [
                "",
                "## 学习步骤",
                "1. 逐一阅读上述来源，标出各自的概念、适用条件与限制。",
                "2. 以引文为证据，对照各材料涉及的检索、生成与评估环节；"
                "材料未说明的内容标记为待验证。",
                "3. 根据笔记构建一个小型问答示例，记录检索证据与答案是否对应。",
                "4. 回看来源验证差异结论，列出仍需实验确认的问题。",
                "",
                "## 来源",
            ]
        )
        lines.extend(f"- `{display_path(path)}`" for path, _ in notes)
        return "\n".join(lines) + "\n"


class OpenAICompatibleModel:
    """Non-streaming function calling over a bounded HTTP response.

    usage_tokens is the provider's reported total (prompt + completion), or zero
    when usage is absent; zero is not a claim that a request was free. max_tokens
    bounds each requested completion, while the runtime owns aggregate budgets.
    No credentials, request URLs, or raw provider errors enter public exceptions.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        *,
        timeout: float = 30.0,
        max_tokens: int = 2048,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        endpoint = base_url if base_url is not None else os.getenv("WA_API_BASE_URL", "")
        model_name = model if model is not None else os.getenv("WA_MODEL", "")
        try:
            parsed = httpx.URL(endpoint)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.host
                or parsed.userinfo
                or parsed.query
                or parsed.fragment
                or not model_name.strip()
                or len(model_name) > 200
            ):
                raise ValueError("Invalid model configuration")
            if (
                isinstance(timeout, bool)
                or not math.isfinite(timeout)
                or not 0 < timeout <= 300
                or isinstance(max_tokens, bool)
                or not isinstance(max_tokens, int)
                or not 1 <= max_tokens <= 32768
            ):
                raise ValueError("Invalid request limits")
        except (ValueError, TypeError, httpx.InvalidURL):
            raise ModelError(
                "CONFIGURATION_ERROR",
                "Set a valid WA_API_BASE_URL and WA_MODEL, with bounded request limits",
            ) from None
        self._url = endpoint.rstrip("/") + "/chat/completions"
        self._api_key = api_key if api_key is not None else os.getenv("WA_API_KEY", "")
        self.model = model_name
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._client = client

    @classmethod
    def from_env(cls, **kwargs: Any) -> OpenAICompatibleModel:
        return cls(**kwargs)

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            request_size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
        except (ValueError, TypeError, RecursionError):
            raise ModelError("INVALID_REQUEST", "Model request must contain valid JSON") from None
        if request_size > MAX_REQUEST_BYTES:
            raise ModelError("REQUEST_TOO_LARGE", "Model request exceeds the byte limit")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            if self._client is not None:
                raw = await self._request(self._client, payload, headers)
            else:
                async with httpx.AsyncClient() as client:
                    raw = await self._request(client, payload, headers)
        except httpx.TimeoutException:
            raise ModelError("MODEL_TIMEOUT", "Model request timed out", retryable=True) from None
        except httpx.HTTPError:
            raise ModelError(
                "MODEL_CONNECTION_ERROR", "Model request failed", retryable=True
            ) from None
        except (ValueError, UnicodeError):
            raise ModelError("INVALID_RESPONSE", "Model returned invalid JSON") from None
        return self._parse_reply(raw)

    async def _request(
        self, client: httpx.AsyncClient, payload: dict[str, Any], headers: dict[str, str]
    ) -> Any:
        async with client.stream(
            "POST",
            self._url,
            json=payload,
            headers=headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as response:
            status = response.status_code
            if status in {401, 403}:
                raise ModelError("AUTHENTICATION_ERROR", "Model authentication was rejected")
            if status == 429:
                raise ModelError("RATE_LIMITED", "Model rate limit reached", retryable=True)
            if status >= 500:
                raise ModelError(
                    "PROVIDER_UNAVAILABLE", "Model provider is unavailable", retryable=True
                )
            if not 200 <= status < 300:
                raise ModelError("PROVIDER_ERROR", f"Model request rejected (HTTP {status})")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ModelError("RESPONSE_TOO_LARGE", "Model response exceeds the byte limit")
            return _load_json(body.decode("utf-8"))

    @staticmethod
    def _parse_reply(raw: Any) -> ModelReply:
        try:
            if not isinstance(raw, dict):
                raise ValueError("Invalid response envelope")
            choices = raw.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("Expected exactly one choice")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise ValueError("Invalid choice")
            if choice.get("finish_reason") == "length":
                raise ModelError("OUTPUT_TRUNCATED", "Model output reached its completion limit")
            if choice.get("finish_reason") == "content_filter":
                raise ModelError("MODEL_REFUSAL", "Model provider filtered the response")
            message = choice.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError("Expected assistant message")
            content = message.get("content")
            if content is None:
                content = ""
            raw_calls = message.get("tool_calls", [])
            if not isinstance(raw_calls, list) or len(raw_calls) > 16:
                raise ValueError("Invalid tool calls")
            calls: list[ToolCall] = []
            for call in raw_calls:
                if not isinstance(call, dict) or call.get("type") != "function":
                    raise ValueError("Invalid tool call")
                function = call.get("function")
                if not isinstance(function, dict):
                    raise ValueError("Invalid function")
                arguments = function.get("arguments")
                if not isinstance(arguments, str) or len(arguments) > MAX_ARGUMENT_CHARS:
                    raise ValueError("Invalid function arguments")
                arguments = _load_json(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("Function arguments must be an object")
                calls.append(
                    ToolCall(id=call.get("id"), name=function.get("name"), arguments=arguments)
                )
            usage = raw.get("usage", {})
            if not isinstance(usage, dict):
                raise ValueError("Invalid usage")
            for key in ("total_tokens", "prompt_tokens", "completion_tokens"):
                if key in usage and (
                    type(usage[key]) is not int or not 0 <= usage[key] <= MAX_USAGE_TOKENS
                ):
                    raise ValueError("Invalid token count")
            tokens = usage.get(
                "total_tokens", usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            )
            if not content and not calls:
                raise ValueError("Empty model reply")
            return ModelReply(content=content, tool_calls=calls, usage_tokens=tokens)
        except (ValueError, TypeError, ValidationError, RecursionError):
            raise ModelError("INVALID_RESPONSE", "Model returned an invalid completion") from None

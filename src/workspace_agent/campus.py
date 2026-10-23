"""Offline campus desk scenario built only from observed tool results."""

import hashlib
import json
import re
from typing import Any

from workspace_agent.models import ModelReply, ScriptedMockModel, _observations


def _fenced(value: str) -> list[str]:
    longest = max((len(item) for item in re.findall(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}text", value, fence]


def _display(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1].replace("`", "'")


def _literal(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~\-])", r"\\\1", value)


def desk_brief(reads: list[dict]) -> str:
    lines = [
        "# 迎新事项资料索引",
        "",
        "本次整理的是 2024 年历史材料。办理前请向学院核对当年的通知与附件。",
        "",
        "以下条目按原文关键词摘录，不判断个人是否符合条件，也不补填未写明的安排。",
    ]
    for data in reads:
        title = next(
            (line[2:].strip() for line in data["content"].splitlines() if line.startswith("# ")),
            data["path"],
        )
        lines.extend(["", f"## {_literal(title)}", "", f"来源：`{_display(data['path'])}`", ""])
        source_paragraph = None
        found = False
        for line in data["content"].splitlines():
            heading = re.fullmatch(r"## 原文第 (\d+) 段", line.strip())
            if heading:
                source_paragraph = heading.group(1)
            elif not line.startswith(("#", ">")) and re.search(
                r"选课时间|考试时间|参加对象|须凭|自带|课程号|无需选择|附件", line
            ):
                found = True
                lines.extend(
                    [
                        f"原 DOCX 第 {source_paragraph or '未知'} 段：",
                        "",
                        *_fenced(line.strip()),
                        "",
                    ]
                )
        if not found:
            lines.append("未找到现有关键词对应的事项，请人工阅读来源。")
        lines.extend(["本次读取的文件指纹：", f"`sha256:{data['sha256']}`"])
    lines.extend(
        [
            "",
            "## 交接前核对",
            "",
            "- 核对材料的年级、学院与适用年份。",
            "- 摘录提及的附件未随本索引提供，需要回到原通知获取。",
            "- 交接时确认索引没有夹带个人信息。",
            "",
            "## 本次读取的来源",
            "",
        ]
    )
    lines.extend(f"- `{_display(data['path'])}`" for data in reads)
    return "\n".join(lines) + "\n"


class CampusDeskMockModel(ScriptedMockModel):
    """Fixed campus filing task, with no filesystem access inside the model."""

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict]) -> ModelReply:
        del tools
        observations = _observations(messages)
        index = len(observations)
        if not observations:
            return self._reply(index, [("list_files", {"relative_path": "materials"})])
        searches = [item for item in observations if item["name"] == "search_files"]
        if not searches:
            return self._reply(
                index,
                [
                    (
                        "search_files",
                        {
                            "query": "2024",
                            "glob": "materials/*.md",
                            "max_results": 30,
                        },
                    )
                ],
            )
        search_data = searches[-1]["data"]
        if search_data.get("truncated") or search_data.get("skipped", 0):
            return ModelReply(
                content="搜索结果不完整，未生成资料索引。请缩小目录或检查不可读文件。"
            )
        paths = list(
            dict.fromkeys(
                item.get("path")
                for item in searches[-1]["data"].get("matches", [])
                if isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and item["path"].startswith("materials/")
                and item["path"].endswith(".md")
            )
        )
        if len(paths) > 8:
            return ModelReply(content="命中材料超过离线场景的 8 份上限，请缩小目录后再整理。")
        attempted = {
            item["arguments"].get("relative_path")
            for item in observations
            if item["name"] == "read_file"
        }
        unread = [path for path in paths if path not in attempted]
        if unread:
            return self._reply(index, [("read_file", {"relative_path": path}) for path in unread])
        reads = [
            item["data"]
            for item in observations
            if item["name"] == "read_file"
            and item["result"].get("ok") is True
            and item["data"].get("path") in paths
        ]
        if not reads or len(reads) != len(paths):
            return ModelReply(content="材料未能全部读取，未生成资料索引。请检查工具记录。")
        for data in reads:
            if hashlib.sha256(data["content"].encode()).hexdigest() != data.get("sha256"):
                return ModelReply(content="读取内容与指纹不一致，未生成资料索引。")
        writes = [item for item in observations if item["name"] == "write_file"]
        if not writes:
            return self._reply(
                index,
                [
                    (
                        "write_file",
                        {
                            "relative_path": "campus_desk.md",
                            "content": desk_brief(reads),
                            "overwrite": self.overwrite,
                        },
                    )
                ],
            )
        result = writes[-1]["result"]
        data = writes[-1]["data"]
        if result.get("ok") and data.get("written") and data.get("sha256"):
            return ModelReply(content="已生成 campus_desk.md，写入结果已核验并记录 SHA-256。")
        if result.get("ok") and data.get("preview") and not data.get("written"):
            return ModelReply(content="campus_desk.md 已生成预览，尚未写入。")
        return ModelReply(content="资料索引写入未成功，请查看工具记录。")

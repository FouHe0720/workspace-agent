"""A small explicit workflow scaffold, revised by concrete observations."""

from workspace_agent.domain import Step, TaskState


def initial_plan() -> list[Step]:
    return [
        Step(description="检查授权目录，定位与目标相关的材料"),
        Step(description="读取材料，引用证据并比较差异"),
        Step(description="形成结果，按授权预览或写入文件"),
        Step(description="核验工具结果，汇总已完成事项与限制"),
    ]


def observe(state: TaskState, name: str, result: dict) -> None:
    data = result.get("data", {})
    if result.get("ok"):
        index = {"list_files": 0, "search_files": 0, "read_file": 1, "write_file": 2}.get(name)
        if index is not None and state.plan[index].status != "completed":
            state.plan[index].status = "completed"
            state.completed_steps.append(state.plan[index].description)
        if name == "write_file" and data.get("preview"):
            state.plan_revisions.append("写入尚未批准：仅生成预览，未声称文件已创建。")
    else:
        code = (result.get("error") or {}).get("code", "UNKNOWN")
        if code in {"NOT_FOUND", "FILE_NOT_FOUND"}:
            state.plan_revisions.append("路径不存在：先搜索候选路径，再读取实际命中的文件。")
        elif code == "VALIDATION_ERROR":
            state.plan_revisions.append("参数校验失败：依据工具 Schema 修正参数后继续。")

# 实施计划

只在本项目目录开发；默认离线 Mock、CPU、无 API Key。每阶段先验证，再提交。

| 阶段 | 交付 | 完成条件 |
| --- | --- | --- |
| V0 | Python 包、沙盒与六个工具、手写循环、原创笔记、最小 CLI | Mock 实际读材料并写学习计划，基础测试与 Ruff 通过，独立提交 |
| V1 | 计划/恢复/预算、持久化、真实兼容 API、官方 MCP Server/Client | 安全及异常测试、stdio 多工具调用通过，独立提交 |
| V2 | 日志 TUI、完整 CLI、工程脚本、CI、Docker | 安装/运行/质量检查通过；如 Docker 可用则实测，独立提交 |
| V3 | 中文展示文档、面试资料、隐私审查、公开发布 | 重新执行 Quick Start、全测试、验收记录；核对账户后普通推送并复核 |

## 文件职责

- `src/workspace_agent/domain.py`：消息、状态、工具结果和预算。
- `sandbox.py` / `tools.py`：沙盒路径和权限，六个工具及 Schema。
- `models.py` / `runtime.py` / `store.py`：模型适配、手写 Loop、SQLite 状态。
- `cli.py` / `ui.py`：命令和真实事件展示。
- `mcp_server.py` / `mcp_client.py`：共享工具的 stdio Server 与 Client。
- `tests/`：隔离临时目录的单元/集成/失败恢复与安全测试。
- `demo_workspace/notes/`：原创公开示例；`docs/`：架构、演示、技术决策、求职与验证记录。

## 验收边界

无任意 shell/network 工具；拒绝越界、敏感文件、符号链接和未授权覆盖。
写入默认预览；显式批准仍受沙盒限制。真实模型调用与 Docker、CI 结果单独记录，不用 Mock 冒充。

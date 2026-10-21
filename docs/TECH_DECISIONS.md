# 技术决策

1. **Python + 项目 .venv**：本机系统 Python 3.12 缺少 ensurepip，使用已安装的 uv 给项目创建环境；无 sudo、无全局 pip、无 Conda 改动。支持 Linux/WSL Python 3.10+。
2. **手写 Loop**：模型只建议调用；运行时负责 Schema、派发、预算、observation 和最终状态。四步规划是可读工作流骨架，不声称是通用自主规划器。根据缺失文件、参数失败和预览更新计划。
3. **官方 MCP v2**：2026-10-21 查询 PyPI 稳定版并实际安装 2.3.0。检查安装包签名后选择公开的底层 `mcp.server.Server` hooks 与 `mcp.Client`；工具 Schema 与原生派发直接共用，避免函数包装层先做类型转换。依赖限制 `>=2.3,<3`。stdio 实际验证列举四工具与六组原生/MCP 对比。
4. **进程隔离工具超时**：Linux fork 保留已固定的 sandbox dir_fd，超时可终止子进程；写超时视为结果不确定、停止且不自动重放。不是事务回滚，也不保证 exactly-once；恢复需人工核对产物。Windows 原生环境不在支持范围。
5. **SQLite JSON 快照**：工具前保存 intent，工具后保存 outcome。读取历史不执行任何动作；恢复 stale running 只标记 interrupted。无 pickle，不将数据库提交 Git。
6. **无框架依赖的兼容 HTTP 适配**：httpx 实现非流式 Chat Completions Function Calling，显式超时、响应尺寸上限、结构校验、重定向禁用、错误脱敏。未配真实服务时仅运行协议 fixture 测试。
7. **终端界面**：CLI/TUI 直接展示已持久化计划与工具事件，不引入 Web 服务攻击面，也不显示或伪造模型私有推理。
8. **用量有来源**：请求前将消息、工具 Schema 等 JSON 字节数与 completion allowance 作为保守预算预留；有 provider usage 时记录其报告值，缺少 usage 或请求超时时扣估算预留，Mock 明确零外部用量。`token_charges` 标注来源。兼容服务 tokenizer 不统一，字节估计不是通用精确 token/费用保证；硬上限还包括调用次数、HTTP 字节、每次 completion 与墙钟时间。
9. **应用沙盒边界**：固定目录描述符、O_NOFOLLOW、realpath/inode 前后校验、硬链接拒绝；不能对抗同 UID 的恶意本机进程在校验与 syscall 之间重命名。此威胁需容器/不同 OS 用户/文件权限隔离。写操作 fsync 后回读核验，但中断不提供事务回滚。

依据：[MCP 官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[PyPI MCP](https://pypi.org/project/mcp/)、[OpenAI Chat Completions 官方参数文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。实际锁定版本见 `uv.lock`，实际执行情况见 `VALIDATION.md`。

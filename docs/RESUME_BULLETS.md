# 简历描述

以下描述只对应仓库中已实现的能力，不包含虚构的用户量、性能、费用节省或模型效果指标。面试时建议同时说明：离线演示使用确定性 Mock，真实模型适配器通过环境变量配置；实时 API、CI 与 Docker 的实测状态见 [VALIDATION.md](VALIDATION.md)。

## 中文

- 独立实现受限工作空间任务代理，手写 Function Calling 循环，接入六个严格 Pydantic 工具，支持固定四步计划及观察驱动调整、SQLite 运行快照、预算控制、错误观察与中断恢复标记。
- 实现默认写入预览、双重覆盖授权与文件 SHA-256 证据校验；使用目录描述符和 `O_NOFOLLOW` 限制路径访问，覆盖路径穿越、符号链接、硬链接、非法算术及 Prompt Injection 等安全测试。
- 基于官方 MCP Python SDK v2 实现独立 stdio Server/Client，复用原生工具 Schema 和沙盒，通过真实子进程比较成功、预览与拒绝结果；提供无密钥 Mock 演示、OpenAI-compatible HTTP 适配器及可查看真实日志的 CLI。

## English

- Built a handwritten function-calling loop with six validated tools, observation-based workflow updates, SQLite run snapshots, bounded execution, and interruption recovery without replaying writes.
- Implemented preview-first writes, explicit overwrite authorization, descriptor-based filesystem checks, and SHA-256 artifact verification, with tests for traversal, symlinks, hard links, unsafe arithmetic, and injected document instructions.
- Built an official MCP v2 stdio server and client sharing native validation and sandbox rules, alongside an offline scripted demo and an OpenAI-compatible HTTP adapter.

## 展示时应主动说明

离线 Mock 是展示与测试工具，不是通用自然语言规划器。当前计划骨架固定为四步，恢复会标记中断而不会自动续跑。沙盒是应用层权限控制，不能代替 OS 隔离；原地写入被强制中断时可能留下部分文件。不要把这些能力描述成通用自治 Agent、exactly-once 执行、绝对无竞态沙盒或已验证的模型质量提升。

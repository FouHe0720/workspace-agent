# 校园资料工作台 · Workspace Agent

在授权目录里查找迎新材料，生成带来源的交接索引；写入前可预览，写入后核验文件与哈希。
示例使用山东大学（威海）2024 年选课、英语分级通知的真实摘录。

Python 3.10+ · 手写工具调用循环 · SQLite · Pydantic · MCP stdio。
默认离线运行，不需要模型服务或 API Key。

## 一个能当场核对的任务

迎新材料散在多个文件里，整理时容易漏掉“翻译学院除外”“无需选择通选课”这类限制。
校园演示通过真实文件工具搜索、读取两份材料，保留时间、对象、证件和选课要求的完整原文，
生成 `campus_desk.md`。每条摘录沿用来源段落标记，每份文件记录本次读取的 SHA-256。

```text
授权目录 → 列目录 / 搜索 → 读取材料与指纹 → 生成索引
                                                ↓
                                  预览 / 批准写入 → 重新读取核验
                                                ↓
                                      SQLite 状态与工具记录
```

## 运行

支持 Linux / WSL。在仓库根目录执行：

```bash
make install
make campus-demo
make check
```

`campus-demo` 每次创建新的临时工作区，依次运行预览、批准写入与独立哈希核验，不删除已有文件。
想逐步查看，可以选择一个专用目录：

```bash
.venv/bin/agent init-demo --scenario campus --workspace campus_workspace
.venv/bin/agent run '整理迎新材料，生成交接索引' \
  --scenario campus --workspace campus_workspace --dry-run
.venv/bin/agent run '整理迎新材料，生成交接索引' \
  --scenario campus --workspace campus_workspace --approve-writes
cat campus_workspace/campus_desk.md
.venv/bin/agent tui
```

默认不落盘。重复写入已有产物会被拒绝；覆盖还需要 `--allow-overwrite`。
[样例索引](docs/samples/campus-desk.md)可以直接阅读。

## 行动与证据

| 关注点 | 处理方式 |
|---|---|
| 模型说写完了 | 只认可工具返回的 `written=true` 与重新读取的验证证据 |
| 文件越界 | 固定授权根目录、`dir_fd` / `O_NOFOLLOW`、路径与 inode 检查 |
| 写入失控 | 默认预览；覆盖需要操作者与工具参数双方授权 |
| 任务中断 | SQLite 先保存调用意图，再保存工具结果；恢复不自动重放副作用 |
| 无效调用 | 严格参数 Schema、时间与调用数预算、重复调用限制 |
| 多入口不一致 | 原生派发与 MCP stdio 共用 Schema、沙盒和写入策略 |

工具包括列目录、读文件、字面量搜索、写文件、安全算术与持久 todo，没有 shell、任意网络或删除工具。
校园场景是固定的离线脚本，按关键词摘录已读取的材料，不理解任意自然语言目标。
段落编号来自摘录内的标记，运行时不重新解析原始 DOCX；原文真实性与当前适用性仍需人工核对。

## 其他入口

```bash
make demo                         # 原有 RAG 笔记比较与学习计划
make mcp-demo                     # 独立 MCP 进程与原生工具对照
.venv/bin/agent runs
.venv/bin/agent inspect <run_id>
.venv/bin/agent recover <run_id>
```

`recover` 将遗留运行标记为中断，展示未保存结果的调用；它不会自动继续执行。
`inspect` 展示本地原始消息与工具数据，运行数据库保存在忽略的 `.agent/` 中。

真实模型通过 `--model api` 接入支持 function calling 的兼容 `/chat/completions` 服务。
配置见 [.env.example](.env.example)和[演示说明](docs/DEMO.md)，程序默认不读取 `.env`。
接口模式会把获准读取的正文发送到操作者配置的服务；token 控制使用保守字节估算与 provider usage。
本次未调用真实外部模型，HTTP fixture 只验证协议路径。

## 资料与验证

两份历史通知共 13 个原文段落，来自本地 RAG 知识库。
[来源清单](src/workspace_agent/fixtures/campus/manifest.json)保存原文件相对路径、原始 DOCX 与摘录哈希、资料年份和校区。
没有收录个人名单、学号、电话或邮箱。学校材料权利归原作者，代码 MIT 许可不覆盖原文；这些通知不作为当前办事安排。

2026-10-23 本地 **209 项测试通过**，Ruff check / format 检查通过，校园预览、写入与哈希核验通过。
新增测试验证材料变化会进入产物、空目录不生成文件、预览无副作用、重复写入被拒绝和来源哈希一致。
Docker 与托管 CI 的历史结果单独保留在[验证记录](docs/VALIDATION.md)，本次未重新构建镜像。

应用沙盒运行在当前用户权限内，不能替代 OS 隔离；文件与 SQLite 之间没有跨资源事务，
强制终止写操作仍可能留下部分文件。边界见 [SECURITY](SECURITY.md)。

- [架构](docs/ARCHITECTURE.md) · [演示](docs/DEMO.md) · [校园资料说明](docs/CAMPUS_DATA.md)
- [技术决策](docs/TECH_DECISIONS.md) · [代码导览](docs/CODE_WALKTHROUGH.md)
- [MIT 代码许可证](LICENSE)

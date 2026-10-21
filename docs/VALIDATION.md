# 实际验证记录

日期：2026-10-21（Asia/Shanghai）。这里仅记录实际命令输出；Mock、HTTP Fixture、MCP 进程与真实远程模型分别标注。

## 环境预检

在父工作目录实际执行过 `pwd`、`realpath .`、`uname -s`、`python3 --version`、`git --version`、`gh --version`、`gh auth status`、`docker --version`，另检查 Node 与 Docker daemon。

| 项目 | 实际情况 |
| --- | --- |
| OS / Python | Linux；系统 Python 3.12.3 |
| Git / GitHub CLI | Git 2.43.0；gh 2.45.0；操作账户 FouHe0720，经 user API 再次核对 |
| Docker | CLI / daemon 29.8.2，可连接 |
| Node | v24.21.0；项目不需要 Node |
| 项目环境 | uv 0.12.24 创建项目 `.venv`；系统 ensurepip 缺失，未执行 sudo 或全局安装 |
| MCP | 实际查询 PyPI 并安装官方稳定版 2.3.0，核对公开 API 后采用 v2 底层 Server |
| Git 边界 | 父目录不是 Git 仓库；仅在新建的 workspace-agent 中初始化 Git |

完整本机绝对路径与详细原始日志仅保存在忽略的 `.local/` 中，不进入公共仓库。

## 分阶段验收

| 阶段 | 已执行的验收 |
| --- | --- |
| V0 | 实际 Mock 创建学习计划；126 项 pytest 通过；Ruff 通过；提交 edb81ec |
| V1 | 状态/预算/恢复与沙盒复审；真实 MCP stdio；158 项 pytest 通过；Ruff 通过；提交 ade2fe6 |
| V2 | TUI、CLI、安装/演示、锁定依赖与隐私脚本；202 项 pytest 通过；Ruff 通过；Docker 无网络运行通过；提交 1a66853 |
| V3 | 展示文档、可复制 Quick Start、历史与暂存区隐私审查、GitHub 发布；发布和 CI 状态见下表 |

## 本地命令及结果

| 命令 / 检查 | 实际结果 |
| --- | --- |
| `make install` | 通过；uv frozen 同步与 CLI 入口检查成功 |
| `make check` | 通过；202 passed，Ruff 静态与格式检查通过 |
| `make demo` | 通过；新建专用目录，预览不落盘、批准后写入、回读核验、MCP 与 TUI 均成功 |
| `agent mcp-demo` | 真正独立 stdio Server/Client；发现四工具，六组结果全部与原生派发匹配 |
| MCP 测试 | 真实进程成功/连接失败/无响应超时、严格 Schema、越权/符号链接与覆盖保护通过 |
| 安装包检查 | 从临时源码副本离线构建 wheel；模块、三份笔记与入口存在；提取后的隔离 CLI 全流程通过 |
| 隐私脚本 | tracked、完整 index、未忽略待发布文件、可达历史均已扫描通过；最终暂存清单另行核对 |
| Docker 最终构建与运行 | 通过；带哈希生产依赖与最新源码构建成功，非 root / 无网络 / 移除 capabilities / no-new-privileges 下 Mock 实际写入成功，容器内 MCP 六组对比全匹配 |
| GitHub 公共发布 | 尚未执行；本地验收后使用账户 FouHe0720 普通创建/推送 |
| 托管 CI | 尚未执行；已配置 Python 3.10 / 3.12 与 Docker jobs |

测试耗时受环境影响，不作为性能评测。未报告吞吐、准确率、成本降低或覆盖率指标。

本地镜像 `workspace-agent:local` 验证时 ID：`sha256:2dd2d2e9c5ced9ec1590d885d479c7ae2362618fc47419a565ef78abc1521a3b`；配置用户 `10001:10001`。镜像构建访问公开依赖索引，运行时通过 `--network none` 验证离线闭环。没有向镜像传递模型密钥。

## 实际产物证据

最终本地 Mock 示例运行 `d95b2d336a8c4de59863c3d088b49893`：6 次模型迭代、8 次工具调用，状态 completed。读取三份已公开笔记后写入 `demo_workspace/study_plan.md`，工具返回 `exists=true, verified=true`，另从磁盘重新计算哈希一致：

```text
265ee66854ab7e7119dc7f32afb30f693408d59aa4dc58f28ab22f0f130ea2b8
```

产物包含实际笔记原文、确定性提取的职责与差异及来源路径。该 hash 仅对应此版示例材料和 Mock 生成逻辑；文件后续变化应重新核验。原始 run 数据库、完整日志和生成文件均不提交 Git。

## 真实模型与边界

`WA_API_BASE_URL`、`WA_MODEL`、`WA_API_KEY` 在当前环境均未配置。真实模型 **未调用、未实测**。适配器通过 httpx MockTransport 的协议、认证错误、超时、响应大小、JSON/tool_calls 与 usage 校验；这些不是实时 API 或模型效果评测。

已实测的网络相关能力是公开依赖安装、GitHub 账户读取和本机进程间 MCP；MCP stdio 不依赖网络。预算中的字节估计不是任意供应商 tokenizer/账单精确值。应用沙盒不提供 OS 级隔离，原地写入中断后不保证回滚，恢复不自动重放。

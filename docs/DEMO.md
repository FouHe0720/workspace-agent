# 校园资料整理演示

```bash
make install
make campus-demo
```

脚本打印本次专用临时工作区。第一次 run 状态应为 `preview`，没有 `campus_desk.md`；
第二次批准写入后状态为 `completed`，脚本从磁盘重新计算指纹，并确认两份材料的读取哈希均写入索引。
产物包含“翻译学院除外”“无需选择全校通选课程和通识核心课程”等完整限制。

分步命令见仓库 README；`--scenario campus` 只选择固定离线脚本，不改变权限策略。
终端视图按目录、搜索、读取、写入分别显示摘要，长正文不在参数列重复展开。
预算按两列排列，预览、错误与执行状态使用不同颜色；正文与控制字符仍按不可信数据处理。

下方保留原 RAG 笔记演示与真实模型配置。

# 可复制演示

在项目根目录使用 Linux/WSL bash 执行。所有模型演示默认 Mock。安装依赖后，核心演示不需要网络。

## 1. 安装与全新沙盒

```bash
make install
demo_root=$(mktemp -d /tmp/workspace-agent-demo.XXXXXXXX)
.venv/bin/agent init-demo --workspace "$demo_root"
```

`init-demo` 复制原创 RAG、FastAPI、Agent 笔记，已有文件不会被覆盖。`demo_root` 是本次明确授权的新目录，不指向 home 或其他项目。

## 2. 默认预览

```bash
.venv/bin/agent run '查找 RAG 笔记，整理差异并生成 study_plan.md' --workspace "$demo_root" --dry-run
test ! -e "$demo_root/study_plan.md"
```

真实日志应显示四步计划、多次工具调用、一次 `FILE_NOT_FOUND` 与候选搜索、读取命中材料、写预览，最终状态 `preview`。`test` 成功退出才表明预览未创建文件。

## 3. 批准写入并核对来源

```bash
.venv/bin/agent run '查找 RAG 笔记，整理差异并生成 study_plan.md' --workspace "$demo_root" --approve-writes
cat "$demo_root/study_plan.md"
sha256sum "$demo_root/study_plan.md"
.venv/bin/agent runs
.venv/bin/agent tui
```

终端显示当次真实 run ID 和 `completed`。产物包含 `notes/rag.md`、`notes/fastapi.md`、`notes/agent.md` 的实际引文与职责/差异原文提取。TUI 的产物 hash 来自写工具回读验证，可与 `sha256sum` 对照；它表示写入时的证据，不保证其他进程之后没有改动文件。

## 4. 覆盖拒绝与显式授权

```bash
# 此命令应退出 1，显示 OVERWRITE_DENIED；不会覆盖已有产物。
.venv/bin/agent run '生成学习计划' --workspace "$demo_root" --approve-writes
# 双方授权后才允许覆盖：操作者选项 + Mock 的 overwrite=true 工具参数。
.venv/bin/agent run '生成学习计划' --workspace "$demo_root" --approve-writes --allow-overwrite
```

## 5. 真实 MCP stdio 与原生对照

```bash
.venv/bin/agent mcp-demo --workspace "$demo_root"
```

返回 `transport: stdio`、四个工具名称、六组完整结果和 `all_match: true`。Server 由 Client 使用固定 Python 模块启动，不需要手工开另一个终端。

| 调用 | 原生与 MCP 预期的共用结果 |
| --- | --- |
| list_files | 成功，有限目录 entries |
| read_file notes/rag.md | 成功，正文作为不可信数据与 SHA-256 |
| search_files RAG | 成功，实际 matches 与来源 evidence |
| write_file mcp_preview.md | 成功预览，written=false，无文件副作用 |
| read_file ../outside.md | SANDBOX_VIOLATION |
| search_files max_results="5" | VALIDATION_ERROR；不接受字符串转整数 |

单独给其他 MCP Host 配置 Server 时使用本项目环境的 Python：

```bash
.venv/bin/python -m workspace_agent.mcp_server --workspace "$demo_root"
```

它等待 stdio 协议，普通终端没有对话输出；Ctrl+C 退出。默认仍为写入预览，批准需 Server 自身显式启动选项。

## 6. 查看、预算与中断恢复

```bash
.venv/bin/agent runs
# 将下面的 RUN_ID 替换为 runs 输出的真实 ID。
.venv/bin/agent inspect RUN_ID
.venv/bin/agent tui RUN_ID --watch
# 明确演示迭代预算：应退出 1，状态 budget_exceeded。
.venv/bin/agent run '整理笔记' --workspace "$demo_root" --max-iterations 1
```

本地 Mock 很快；运行中断、文件已写但结果未保存等竞态由测试中的受控慢工具重现，不声称手工 Ctrl+C 已稳定覆盖所有窗口。

```bash
.venv/bin/python -m pytest -q tests/test_runtime.py tests/test_store.py
# 对确已停止但遗留 running 的运行，使用真实 run_id：
.venv/bin/agent recover RUN_ID
```

恢复只更新明确状态，不重放工具；检查不确定写入的磁盘内容后再决定是否新建任务。

## 7. 安全失败与完整验收

```bash
.venv/bin/python -m pytest -q tests/test_tools.py tests/test_mcp.py
make check
make demo
make docker
```

测试使用临时目录，覆盖 `../`、绝对/编码路径、符号链接、硬链接、私有文件、注入文本、禁止覆盖、未知 shell 工具、安全算术、MCP 连接失败与超时。所有“通过”状态以 [VALIDATION.md](VALIDATION.md) 的实际执行记录为准。

## 8. 可选真实模型

先在 shell 中设置 `.env.example` 指定的三个变量，再使用 `--model api --dry-run`。未提供服务与凭证时不执行真实请求；接口 Fixture 测试不等于外部服务实测。详见 [README](../README.md#真实-llmopenai-compatible-function-calling)。

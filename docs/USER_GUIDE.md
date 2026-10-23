# 使用手册

本手册覆盖离线任务、全部 CLI、六个原生工具、MCP stdio、真实模型与实现结构。
命令默认从仓库根目录执行，使用 Bash 和项目 `.venv`。

## 1. 本项目能做什么

Agent 在一个明确授权的目录内读取资料，生成预览或写入产物，并把调用过程保存到 SQLite。
模型只能提出工具调用，实际权限与执行由程序控制。

| 功能 | 实现范围 |
|---|---|
| 离线 RAG 笔记整理 | 搜索、读取材料，生成带来源的学习计划 |
| 离线校园资料整理 | 整理选课、英语分级历史通知，保留完整限制与文件指纹 |
| 兼容真实模型 | 非流式 Chat Completions function calling |
| 六个原生工具 | 列目录、读取、字面量搜索、写文件、算术、持久 todo |
| 写入批准 | 默认预览，批准后写入；覆盖需要额外授权 |
| 预算与失败处理 | 轮数、调用数、时间、token 计数、重复检测 |
| 持久化与恢复 | SQLite 快照、调用意图、结果；恢复不自动重放工具 |
| 终端视图 | 计划、预算、时间线、错误和已核验产物 |
| MCP stdio | 独立进程提供四个文件工具，与原生边界一致 |

项目面向 Linux / WSL，运行工具使用 `fork`。
没有 HTTP 服务、浏览器界面、shell、任意网络、删除或移动文件工具。
`calculator` 不是 Python eval，搜索不是向量数据库，离线脚本不理解任意自然语言任务。

六项目同时运行时，Web 服务分别使用 gateway 8101、structured 8102、RAG 8103、eval 8105、research 8106。
本项目使用 CLI 与 stdio，不需要启动 HTTP 服务或分配端口。

## 2. 环境与安装

需要 Python 3.10+。首次安装依赖需要网络，离线 Mock 与本机 MCP 不需要模型服务。
Docker 可选，不是本地 CLI 的前置条件。

```bash
python3 --version
make install
.venv/bin/agent --help
```

安装脚本优先执行 `uv sync --frozen --extra dev`，使用 `uv.lock`。
没有 uv 时，使用系统 venv 与 pip：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

若缺少 `ensurepip`，先安装对应系统的 venv 支持，或使用已有 uv。
依赖只安装到 `.venv`；生产带哈希依赖位于 `requirements.lock`。
不需要 GPU、模型权重、API Key 或外部数据库服务。

## 3. 第一次运行：预览、写入与检查

下面使用全新的临时目录和 SQLite，不覆盖已有工作区或运行记录。
该目录是唯一授权范围，不能把整个 home、仓库根或 `/tmp` 当作工作区。

```bash
agent_demo_root=$(mktemp -d)
.venv/bin/agent init-demo --workspace "$agent_demo_root/notes"
.venv/bin/agent run '查找 RAG 笔记，整理差异并生成 study_plan.md' \
  --workspace "$agent_demo_root/notes" --db "$agent_demo_root/runs.sqlite3" \
  --dry-run
```

初始化把三篇原创笔记复制到工作区内的 `notes/`。
预览完成后状态为 `preview`，`study_plan.md` 尚未创建。
接着显式批准写入：

```bash
.venv/bin/agent run '查找 RAG 笔记，整理差异并生成 study_plan.md' \
  --workspace "$agent_demo_root/notes" --db "$agent_demo_root/runs.sqlite3" \
  --approve-writes
cat "$agent_demo_root/notes/study_plan.md"
sha256sum "$agent_demo_root/notes/study_plan.md"
.venv/bin/agent runs --db "$agent_demo_root/runs.sqlite3"
.venv/bin/agent tui --db "$agent_demo_root/runs.sqlite3"
```

成功写入后状态通常为 `completed`，工具返回重新读取后核验的 SHA-256。
原笔记流程故意读取一次不存在的路径，再通过搜索恢复；历史错误仍会出现在日志中。
有错误记录不一定表示整个任务失败，应结合最终状态和写入证据判断。

`make demo` 会创建自己的新临时工作区，依次预览、写入、核验、比较 MCP 并打开 TUI。
它仍使用默认 `.agent/runs.sqlite3` 保存运行记录；需要完全隔离数据库时用本节命令。

## 4. 校园资料整理

校园场景使用山东大学（威海）2024 年选课、英语分级两份材料，共 13 个原文段落。
它们是历史快照，不用于安排当前考试或判断个人资格。

```bash
.venv/bin/agent init-demo --scenario campus --workspace "$agent_demo_root/campus"
.venv/bin/agent run '整理迎新选课和英语分级材料，生成交接索引' \
  --scenario campus --workspace "$agent_demo_root/campus" \
  --db "$agent_demo_root/campus.sqlite3" --dry-run
.venv/bin/agent run '整理迎新选课和英语分级材料，生成交接索引' \
  --scenario campus --workspace "$agent_demo_root/campus" \
  --db "$agent_demo_root/campus.sqlite3" --approve-writes
cat "$agent_demo_root/campus/campus_desk.md"
```

`materials/` 包含两份 Markdown 与来源 manifest。
模型实际搜索和读取文件后，按关键词摘录时间、对象、证件、课程号、附件等内容。
产物保留“翻译学院除外”“无需选择通选课”等完整条件，以及本次读取指纹。
原 DOCX 的段落编号沿用摘录标记，运行时不重新打开原 DOCX 验证。

工作区材料变化会反映到新结果，不会继续声称与打包快照相同。
初始化不会覆盖已有文件，也不负责把用户修改的材料恢复到原版。
来源清单中的原文件与摘录哈希用于说明打包快照，读取工具另记录当前文件哈希。

校园脚本只搜索 `materials/*.md` 中的 `2024`，最多处理 8 份匹配来源。
搜索截断、跳过文件、来源超量、读取失败或内容与读取指纹不符时，不提议写入。
没有资料时可能正常结束循环，但不会出现已核验产物；不能只看 `completed` 就认定文件已创建。
`make campus-demo` 自动创建临时目录，运行预览、批准写入和独立哈希核验。

## 5. 全部 CLI 命令

可使用 `.venv/bin/agent`，或 `.venv/bin/python -m workspace_agent`。
顶层提供 `--help`、`--show-completion`、`--install-completion`，后两项由 Typer 管理 shell 补全。

### 5.1 init-demo

```text
agent init-demo [--workspace PATH] [--scenario notes|campus]
```

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--workspace` | `demo_workspace` | 创建或复用专用目录 |
| `--scenario` | `notes` | `notes` 复制原创笔记；`campus` 复制历史通知 |
| `--help` | — | 命令帮助 |

目标及祖先不能通过符号链接访问，内部 `notes` / `materials` 也不能是符号链接。
已经存在的文件不会被覆盖；错误会以稳定代码显示。

### 5.2 run

```text
agent run GOAL [OPTIONS]
```

| 参数 | 默认值 / 范围 | 含义 |
|---|---|---|
| `GOAL` | 必填，1–4000 字符 | 任务描述 |
| `--workspace` | `demo_workspace` | 已存在、明确授权的工作区 |
| `--model` | `mock` | `mock` / `api` |
| `--scenario` | `notes` | `notes` / `campus`；选择 Mock 脚本，不替真实模型规划 |
| `--dry-run` | false | 显式预览意图，与批准写入互斥 |
| `--approve-writes` | false | 允许工作区内的写操作 |
| `--allow-overwrite` | false | 允许覆盖，还需工具参数 `overwrite=true` |
| `--max-iterations` | 12；1–100 | 模型循环轮数上限 |
| `--max-tool-calls` | 30；1–200 | 总工具调用上限 |
| `--max-tokens` | 24000；100–1000000 | 预算计数上限，不是精确账单额度 |
| `--timeout` | 90；大于 0、至多 1800 秒 | 整个运行的时间预算 |
| `--db` | `.agent/runs.sqlite3` | SQLite 路径 |
| `--json` | 关闭 | stdout 输出完整 TaskState JSON，省略逐事件终端日志 |
| `--help` | — | 命令帮助 |

三个布尔策略参数还接受对应的 `--no-dry-run`、`--no-approve-writes`、`--no-allow-overwrite`。
默认没有批准写入，即使不写 `--dry-run` 也只预览。
`--allow-overwrite` 必须与 `--approve-writes` 一起使用。

已有产物再生成需要：

```bash
.venv/bin/agent run '整理迎新材料' --scenario campus \
  --workspace "$agent_demo_root/campus" --db "$agent_demo_root/campus.sqlite3" \
  --approve-writes --allow-overwrite
```

Mock 会同时提出 `overwrite=true`；真实模型也必须显式提出该参数。
命令退出码：`completed` / `preview` 为 0，运行失败或预算终止通常为 1，配置/权限错误为 2，键盘中断为 130。

### 5.3 runs、inspect、recover

```bash
.venv/bin/agent runs --db "$agent_demo_root/campus.sqlite3"
.venv/bin/agent inspect RUN_ID --db "$agent_demo_root/campus.sqlite3"
.venv/bin/agent recover RUN_ID --db "$agent_demo_root/campus.sqlite3"
```

把 `RUN_ID` 替换为 run 命令实际打印的 ID，不要照抄占位字符串。
三个命令都只有 `--db` 与帮助选项；`inspect`、`recover` 需要位置参数 run_id。
`runs` 默认列出最近 30 条记录，没有 CLI 的 `--limit` 参数。

`inspect` 显示保存的 JSON 快照，包含本地消息、材料正文和工具参数。
需要机器读取本次完整 JSON 时优先使用 `run --json` 保存 stdout。
`recover` 只在状态为 `running` 时标记为 `interrupted`，列出尚无结果的调用。
它不会杀死正在执行的进程，不会继续任务，也不自动重放写操作。
只对确定已退出的遗留运行执行恢复，再核对磁盘是否存在不确定产物。

### 5.4 tui

```bash
.venv/bin/agent tui --db "$agent_demo_root/campus.sqlite3"
.venv/bin/agent tui RUN_ID --watch --db "$agent_demo_root/campus.sqlite3"
```

| 参数 | 默认值 | 含义 |
|---|---|---|
| `run_id` | 可省略 | 省略时选择最近更新的运行 |
| `--watch` / `--no-watch` | false | 对正在运行的指定记录持续刷新 |
| `--db` | `.agent/runs.sqlite3` | 读取的运行库 |
| `--help` | — | 命令帮助 |

界面包括目标/状态、两列预算、计划、调整、工具观察、已核验产物、错误与最终结果。
读取显示长度和指纹摘要，写参数显示正文字符数，完整内容可用 inspect 查看。
预览、错误和状态使用不同颜色；控制字符被转义，正文中的 Rich 标记按文字处理。
产物区保留完整 SHA-256，窄终端会换行，不用省略号截掉摘要。

watch 每 0.25 秒刷新同一 run，进入终态就退出刷新；其他新 run 不会抢走当前视图。
按 `Ctrl+C` 只停止查看，不恢复、不执行任务，也不改变保存状态。
数据库尚不存在时会初始化空库，然后提示没有运行记录。

### 5.5 mcp-demo

```bash
.venv/bin/agent mcp-demo --workspace "$agent_demo_root/notes" --timeout 15
```

只有 `--workspace`、`--timeout` 和帮助选项。
默认工作区 `demo_workspace`，timeout 默认 15 秒，须为大于 0、至多 120 的有限数。
它启动独立 stdio Server，比较原生与 MCP 的列目录、读取、搜索、写预览、越界路径、非法类型六组结果。
写入始终不批准，`mcp_preview.md` 不应落盘；结果中的 `all_match=true` 表示六组一致。
演示读取的是 `notes/rag.md`；对校园目录运行仍能比较拒绝结果，要看成功读取请使用 notes 场景。

## 6. 原生工具的契约与使用

CLI 没有单独的 `agent tool` 子命令；工具由运行循环调用，或通过 Python 的 `ToolDispatcher` 直接调用。
所有工具参数都禁止额外字段，采用严格类型；`"5"` 不会自动变成数字，`"true"` 不会变成布尔值。

| 工具 | 参数 | 主要输出 |
|---|---|---|
| `list_files` | relative_path 默认 `.`，最多 1024 字符 | entries、扫描与跳过数量、截断标记 |
| `read_file` | relative_path 必填，最多 1024 字符 | content、path、sha256、untrusted |
| `search_files` | query 1–200；glob 默认 `*.md`、1–128；max_results 默认 20、1–100 | 字面量命中、行号、路径、截断与扫描信息 |
| `write_file` | relative_path；content 最多 65536 字符；overwrite 默认 false | 预览，或写入后的字节数、哈希、验证证据 |
| `calculator` | expression 1–256 字符 | 有限数值结果 |
| `todo_manager` | action=`list/add/complete`；text 可选 1–1000；item_id 可选 1–32 | items、持久化与预览状态、来源证据 |

直接调用 ToolDispatcher 不建立 AgentRuntime 运行记录，也不自动启用其 fork 工具超时和总预算。
MCP Server 同样共享参数、路径与写入边界，但没有 AgentRuntime 的 SQLite 检查点与循环预算。
内置 MCP 客户端的连接超时用于限制协议生命周期，不能等同于写操作从未发生。

ToolResult 的统一字段为 `ok`、`data`、`error`、`evidence`。
失败时 error 提供 `code`、安全消息与 `retryable`；它不是自动重试指令。

下面直接调用六个工具，写文件仍预览，todo 的新增/完成明确批准保存：

```bash
.venv/bin/python - "$agent_demo_root/campus" <<'PY'
import sys
from pathlib import Path
from workspace_agent.tools import ToolDispatcher

root = Path(sys.argv[1])
preview = ToolDispatcher(root)
writer = ToolDispatcher(root, approve_writes=True)
try:
    print(preview.dispatch("list_files", {"relative_path": "materials"}).model_dump_json())
    print(preview.dispatch("read_file", {
        "relative_path": "materials/course-selection-2024.md"
    }).model_dump_json())
    print(preview.dispatch("search_files", {
        "query": "选课", "glob": "materials/*.md", "max_results": 10
    }).model_dump_json())
    print(preview.dispatch("write_file", {
        "relative_path": "review.md", "content": "# 待核对材料\n"
    }).model_dump_json())
    print(preview.dispatch("calculator", {"expression": "20 / 4"}).model_dump_json())
    added = writer.dispatch("todo_manager", {"action": "add", "text": "核对资料年份"})
    assert added.ok
    item_id = added.data["items"][-1]["id"]
    print(writer.dispatch("todo_manager", {"action": "complete", "item_id": item_id}).model_dump_json())
    print(writer.dispatch("todo_manager", {"action": "list"}).model_dump_json())
finally:
    preview.sandbox.close()
    writer.sandbox.close()
PY
```

搜索按字面量忽略大小写，不执行正则表达式，也不提供语义排序。
算术只允许数值常量、括号和加减乘除、整除、取模、幂及正负号。
数值须有限且绝对值不超过 1e12；AST 最多 48 节点、深度 12，幂指数绝对值最多 12。
不允许变量、函数调用、属性访问、导入或布尔值。

todo 写入 `workspace_todos.json`，格式标记为 `workspace-agent-todos-v1`，最多 100 项。
修改前校验原文件格式与旧哈希；未知原有内容不会被覆盖。
普通 `write_file` 不能写这一保留路径；todo 的受控修改不要求普通文件覆盖授权。

## 7. MCP stdio 服务与客户端

MCP 使用 stdin/stdout 协议，没有 HTTP URL 或监听端口。
Server 只发布 `list_files`、`read_file`、`search_files`、`write_file`；算术与 todo 不发布。

```bash
.venv/bin/workspace-mcp --workspace "$agent_demo_root/campus"
# 同一入口：
.venv/bin/python -m workspace_agent.mcp_server --workspace "$agent_demo_root/campus"
```

服务参数是必填 `--workspace`，以及可选 `--approve-writes`、`--allow-overwrite`、帮助选项。
覆盖选项仍要求同时批准写入。stdout 只能用于协议，诊断写 stderr。
直接在终端启动后等待协议输入是正常行为；通常让 MCP 客户端负责启动与关闭子进程。

第三方 MCP 客户端的配置可参考以下结构，两个 `/path/to/...` 必须替换成实际绝对路径：

```json
{
  "command": "/path/to/project/.venv/bin/python",
  "args": ["-I", "-m", "workspace_agent.mcp_server", "--workspace", "/path/to/campus_workspace"]
}
```

内置客户端固定使用当前 Python 解释器与隔离模式，不接受任意可执行命令，也不向 Server 传递模型密钥。
通过真实连接读取校园材料：

```bash
.venv/bin/python - "$agent_demo_root/campus" <<'PY'
import asyncio
import sys
from workspace_agent.mcp_client import connect_workspace

async def main():
    async with connect_workspace(sys.argv[1], timeout=15) as client:
        tools = await client.list_tools()
        assert len(tools) == 4
        result = await client.call_tool("read_file", {
            "relative_path": "materials/english-placement-2024.md"
        })
        assert result.ok
        print(result.model_dump_json(indent=2))

asyncio.run(main())
PY
```

同样可运行模块化比较入口：

```bash
.venv/bin/python -m workspace_agent.mcp_client --workspace "$agent_demo_root/notes" --timeout 15
```

它只接受必填 `--workspace`、可选 `--timeout` 与帮助。
服务端结果同时提供结构化 ToolResult 与文本 JSON，`is_error` 必须与 `ok` 一致。
stdio 生命周期有超时，连接退出时由 SDK 清理子进程；这不是远程 MCP 托管实现。

## 8. 真实模型配置与全部限制

程序默认不读取 `.env`。只有 `--model api` 会创建 HTTP 模型适配器。
先复制模板，编辑自己的可信配置，然后显式导出：

```bash
cp .env.example .env
# 编辑 .env；不要提交私人文件。
set -a
source .env
set +a
.venv/bin/agent run '比较授权目录里的材料，写一份带来源的摘要' \
  --model api --workspace "$agent_demo_root/campus" \
  --db "$agent_demo_root/api.sqlite3" --dry-run
```

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `WA_API_BASE_URL` | 空 | HTTP(S) base URL，程序追加 `/chat/completions` |
| `WA_MODEL` | 空 | 非空模型名，最多 200 字符 |
| `WA_API_KEY` | 空 | 可选 Bearer 凭据，自建无认证服务可以为空 |

URL 不能包含内嵌账号密码、query 或 fragment；版本前缀如 `/v1` 应写在 base URL 中。
服务须支持非流式 `tools` / `tool_calls`；没有 Responses、流式、图片或供应商专有接口适配。
模型会接收授权读取的正文，但 Agent 工具不能选择网络目标。
本手册验证不调用外部真实模型。

### 8.1 CLI 没有暴露的程序级配置

| 配置 | 默认 / 范围 | 设置位置 |
|---|---|---|
| 模型 HTTP timeout | 30 秒；大于 0、至多 300 | `OpenAICompatibleModel(timeout=...)` |
| 单次 completion max_tokens | 2048；1–32768 | `OpenAICompatibleModel(max_tokens=...)` |
| 模型异步超时 | 20 秒；大于 0、至多 120 | `Budget(model_timeout=...)` |
| 单工具进程超时 | 3 秒；大于 0、至多 30 | `Budget(tool_timeout=...)` |
| 每次模型工具调用数 | 最多 16 | ModelReply 契约 |
| HTTP 请求体 | 最多 1000000 字节 | 模型适配器常量 |
| HTTP 响应体 | 最多 2000000 字节 | 模型适配器常量 |
| 工具参数字符串 | 最多 100000 字符 | 模型适配器常量 |
| 单次报告 token usage | 至多 20000000 | 模型回复校验 |

这些参数没有 `WA_TIMEOUT` 等环境变量，也没有同名 CLI 选项。
默认运行循环的 20 秒模型超时可能早于适配器的 30 秒 HTTP 超时生效。
程序接入时可同时设置适配器和 Budget；其余可配置预算见 run 参数表。

### 8.2 沙盒与资源常量

| 限制 | 数值 |
|---|---|
| 单文件读取 / 写入字节数 | 128 KiB；写入还受 65536 字符限制 |
| 单目录枚举条目 | 200 |
| 递归扫描条目 | 500 |
| 递归扫描文件 | 200 |
| 递归扫描深度 | 8 |
| 一次搜索累计读取字节数 | 2 MiB |
| 文件路径 | 最多 1024 字符；单个组件最多 255 UTF-8 字节 |

拒绝绝对路径、父目录、编码路径、隐藏/敏感名称、符号链接、硬链接和特殊文件。
正文按 UTF-8 读取，拒绝二进制及不允许的控制字符。
中文字符的字节数通常多于一个字节，字符上限与字节上限同时生效。

## 9. 持久化、状态与恢复语义

默认数据库是 `.agent/runs.sqlite3`，目录以 0700 创建，数据库文件设为 0600。
SQLite 的 runs 表按 run_id 保存整个 TaskState JSON，包含计划、消息、调用、错误与结果。
产物写入授权工作区，数据库不代替产物文件存储。

状态包括 `running`、`completed`、`preview`、`failed`、`budget_exceeded`、`interrupted`。
写入前先持久化调用意图，工具结束后再保存结果；因此 `result=null` 可能代表副作用已经发生但回执未保存。
SQLite 事务只保护快照，不提供文件与数据库之间的跨资源事务或 exactly-once。
强制终止仍可能留下空文件或部分内容，恢复后需要核对实际文件。

重复工具与相同参数最多执行两次，第三次触发循环检测。
模型可重试错误最多额外重试一次，工具没有通用自动重试。
写工具超时、覆盖拒绝和安全拒绝会终止运行；只读失败可作为 observation 交给下一轮。
API token 缺失或请求结果不确定时记估算消耗；离线 Mock 的计数来源明确为 `offline_mock`。
请求前仍检查完整消息字节预算，所以 Mock 计数为 0 不代表可以无限扩展上下文。

## 10. Docker、检查与离线验证

```bash
make lint
make test
make check
.venv/bin/python scripts/privacy_check.py --history --include-untracked
```

隐私脚本是维护工具，不在 Agent 工具白名单中，支持以下参数：

| 参数 | 含义 |
|---|---|
| `--repo` | 待扫描 Git 仓库，默认当前目录 |
| `--tracked` | 检查已跟踪工作树文件 |
| `--staged` | 检查完整暂存区内容 |
| `--include-untracked` | 加入未被忽略的新文件 |
| `--history` | 检查可达提交历史 |

未选 tracked/staged 时默认两者都检查；扫描通过只表示现有规则未发现问题。
`make docker` 组合镜像构建与默认无网络 Mock 运行。
没有独立的模型准确率评测器；测试验证权限、协议、状态与固定场景，不应当作真实模型质量分数。
`make mcp-demo` 使用默认 `demo_workspace`，需先初始化对应目录。

```bash
docker build -t workspace-agent:local .
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  workspace-agent:local
```

镜像默认 UID 10001，已经初始化 notes；默认 CMD 显式批准写入容器临时工作区。
它没有端口映射需求。要只预览，可覆盖默认 CMD：

```bash
docker run --rm --network none workspace-agent:local \
  run '整理 RAG 笔记' --workspace demo_workspace --dry-run
```

镜像 ENTRYPOINT 已是 `agent`，不要在镜像名后再重复写 `agent`。
运行容器内 MCP 比较可用 `mcp-demo --workspace demo_workspace`。
`--rm` 退出后容器内数据库与产物消失；保留时需挂载专用目录，并保证容器 UID 有写权限。
私人模型配置不写进镜像，离线演示不需要网络。

## 11. 目录与模块职责

```text
workspace-agent/
├── src/workspace_agent/
│   ├── __main__.py / cli.py             # 模块入口、Typer 命令、显式授权
│   ├── domain.py                       # Budget、Step、ToolEvent、TaskState
│   ├── models.py                       # 固定笔记脚本与兼容 HTTP 模型
│   ├── campus.py                       # 校园检索脚本、引用与交接索引
│   ├── runtime.py                      # 工具调用循环、进程超时、预算、检查点
│   ├── planning.py                     # 固定四步计划与 observation 调整
│   ├── tools.py                        # 六工具 Schema、派发、算术与 todo
│   ├── sandbox.py                      # 目录描述符、路径与 inode 检查、文件读写
│   ├── store.py                        # SQLite JSON 快照及中断恢复
│   ├── ui.py                           # 只读终端视图与产物证据过滤
│   ├── mcp_server.py                   # 四文件工具的 MCP stdio Server
│   ├── mcp_client.py                   # 固定子进程客户端与六组一致性比较
│   └── fixtures/
│       ├── notes/                      # RAG、FastAPI、Agent 原创材料
│       └── campus/                     # 校园摘录与来源 manifest
├── demo_workspace/notes/                # 仓库内可读演示笔记
├── scripts/
│   ├── install.sh                      # uv / venv 安装
│   ├── demo.sh                         # 笔记预览、写入、MCP、TUI
│   ├── campus_demo.sh                  # 校园预览、写入、哈希核验
│   └── privacy_check.py                # 工作树、暂存区、历史内容扫描
├── tests/                              # CLI、运行时、沙盒、协议、视图与来源测试
├── docs/                               # 手册、架构、来源、验证与样例
├── .env.example                        # 三个真实模型环境变量的空模板
├── pyproject.toml / uv.lock             # 项目声明与开发环境锁
└── Dockerfile / requirements.lock       # 非 root 镜像与带哈希依赖
```

`.agent/`、`.local/`、`.venv/`、私人 `.env`、数据库和生成的演示产物不提交 Git。
工作区不是数据库的隐式父目录；每次都应确认 `--workspace` 和 `--db` 分别指向什么。

## 12. 一次任务的调用流程

1. CLI 校验场景、模型和授权参数，创建 Sandbox、模型、Budget 与 RunStore。
2. Runtime 建立四步初始计划与消息历史，保存 running 状态。
3. 模型返回工具建议；运行时检查预算、调用 ID、参数与重复次数。
4. 保存工具意图，再在 Linux 工具进程中通过 Dispatcher 执行。
5. Sandbox 在固定根描述符下检查路径、资源、文件身份和写权限。
6. ToolResult 回到消息历史；保存结果、调整计划，再向模型请求下一轮。
7. 模型停止提出工具后，记录终态与最终文本；TUI 只渲染已有事实。

原文指纹证明工具读写的字节一致，不证明摘要正确、来源可信或文件后来没变。
应用沙盒不能抵御同 UID 恶意原生进程的所有竞态；需要更强隔离时应使用 OS 级边界。
固定离线脚本适合验证这条执行链，真实模型的规划与语义能力需要单独评估。

## 13. 故障排查

| 现象 | 处理方式 |
|---|---|
| workspace 不存在 | 先 init-demo，或创建专用目录再授权 |
| `SANDBOX_VIOLATION` | 检查路径、祖先链接、敏感目录；不要授权 home/仓库/系统根 |
| `OVERWRITE_DENIED` | 先检查已有产物，再按需要同时授权覆盖并提供 overwrite=true |
| `VALIDATION_ERROR` | 对照严格 Schema，不使用字符串形式的数字/布尔值或额外字段 |
| `RESOURCE_LIMIT` | 减小文件、目录或搜索范围；字符与字节限制分别生效 |
| `TODO_STATE_INVALID` | 保留原文件，人工核对；不要让写工具覆盖保留状态 |
| `STATE_CONFLICT` | 文件状态在操作前发生变化，重新读取并核对，不盲目覆盖 |
| `TOKEN_BUDGET` / `TOOL_CALL_BUDGET` | 缩小任务和历史；确有需要时调整对应 run 参数 |
| `LOOP_DETECTED` | 同一工具参数重复过多，检查目标或模型是否缺少有效观察 |
| `MODEL_TIMEOUT` / `MODEL_CONNECTION_ERROR` | 检查模型地址、网络与异步超时，不等同于没有产生上游调用 |
| `CONFIGURATION_ERROR` | 核对 WA_API_BASE_URL、WA_MODEL；仅复制 .env 不会自动生效 |
| `MCP_CONNECTION_ERROR` | 确认使用安装本项目的解释器、工作区有效、stdout 未混入日志 |
| `MCP_TIMEOUT` | 检查进程和请求范围，必要时调整客户端 timeout |
| TUI 没有运行记录 | 确认 --db 与 run 一致；查看命令不会自动执行任务 |
| 索引未生成但循环已结束 | 检查来源范围、搜索截断与最终文本，确认是否存在已核验产物 |

更多实现细节见 [代码导览](CODE_WALKTHROUGH.md)，边界说明见 [SECURITY](../SECURITY.md)。

## 14. 手册核对记录

本次使用独立临时工作区和 SQLite，实际执行全部七个主命令。
已核对 notes 预览、校园预览/写入/覆盖拒绝/批准覆盖、JSON 状态、
TUI 快照与终态 watch、遗留 running 的恢复且不重放写入。
六个原生工具、todo 持久化、六组 MCP 一致性比较和 stdio 校园读取均已运行。
临时 MCP 子进程已随连接退出；没有调用真实模型，没有覆盖已有运行库或报告。
Docker 配方由 Dockerfile 与入口核对，本次未重新构建运行。

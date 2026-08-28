# Coding Agent From Scratch

一个从零实现的轻量级编程智能体。

它通过大语言模型原生 Tool Calling，自主完成：

**理解任务 → 检索代码 → 读取文件 → 修改代码 → 编译 / 测试 → 根据错误继续修复 → 完成任务**

项目不依赖 LangChain、LlamaIndex、OpenAI Agents SDK、AutoGen、CrewAI 等 Agent 框架。  
Agent Loop、上下文管理、工具执行、模型输出解析、终止策略、错误恢复和会话持久化均自行实现。

## Features

- 文件浏览：`list_files`
- 代码搜索：`search_text`
- 文件读取：`read_file`
- 文件创建 / 重写：`write_file`
- 局部代码修改：`edit_file`
- 本地编译 / 运行 / 测试：`run_command`
- 对话历史与上下文管理
- Structured Working Memory：Runtime 自动维护任务状态摘要
- 错误恢复与模型重试
- Workspace Revision：SHA-256 文件状态指纹
- Validation Evidence：验证命令与代码状态绑定
- 最新代码验证保护
- Session 持久化与恢复
- JSONL Runtime Trace
- SensitiveDataPolicy：敏感路径拦截与凭据脱敏

典型工作流：

```text
search
  ↓
read
  ↓
edit
  ↓
run / test
  ↓
fix
  ↓
finish
```

Agent 修改代码后不能直接结束。Runtime 会为 Workspace 计算确定性的 SHA-256 revision，并把成功的运行 / 测试记录为 Validation Evidence。只有当前 revision 与最近一次成功验证的 revision 完全一致时才允许完成任务；如果验证后文件被再次修改，即使修改来自 Agent 外部，也必须重新验证。

上下文管理同时维护三个不同层次：Conversation History 保存完整事件历史；Structured Working Memory 根据真实 Tool Result 自动记录已检查/修改文件、最近命令、错误与验证状态；ContextManager 则把 System Prompt、原始任务、Working Memory 和最近消息组合成下一次实际发送给模型的上下文。Working Memory 不由 LLM 自行总结，因此不会把模型的自述当作运行时事实。

## Quick Start

安装依赖：

```bash
pip install -r requirements.txt
```

复制环境变量模板：

```bash
cp .env.example .env
```

填写模型 API 配置后运行：

```bash
python main.py
```

也可以直接提供任务：

```bash
python main.py "Please implement and test merge sort in Python."
```

指定工作目录：

```bash
python main.py \
  "Fix the failing tests." \
  --workspace ./my_project
```

查看历史 Session：

```bash
python main.py --list-sessions
```

恢复未完成任务：

```bash
python main.py --resume <SESSION_ID> --max-steps 20
```

运行测试：

```bash
python -m pytest -q
```

当前测试集：

```text
150 passed
```

## Project Structure

```text
coding-agent-from-scratch/
├── agent/       # Agent Loop、上下文、状态、验证证据、终止策略
├── tools/       # 文件工具与命令执行工具
├── storage/     # Session 与 Trace 持久化
├── security/    # 敏感路径策略与凭据脱敏
├── prompts/     # System Prompt
├── tests/       # 单元测试与集成测试
├── workspace/   # 默认工作目录
└── main.py      # CLI 入口
```

核心设计原则：

> **LLM 负责决策，本地 Runtime 负责执行和约束。**

## Safety

Agent 默认只能操作指定 Workspace，并提供：

- 路径越界检查
- symlink 越界保护
- `shell=False`
- 命令白名单
- 执行超时
- stdout / stderr 捕获
- 敏感环境变量清理
- `.env` / 私钥 / 云凭据等敏感路径拦截
- Tool Result、Session、Trace 中的敏感文本脱敏

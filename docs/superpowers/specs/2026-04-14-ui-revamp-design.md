# UI Revamp Design for GlassCrewAgent

*Design date: 2026-04-14*

## Overview

GlassCrewAgent的Web UI需要更新以适配后端接口变化，提供更好的用户体验。主要改进包括：

1. **实时工具级日志** - 完整显示CrewAI执行过程中：哪些子代理在运行、调用了哪些工具、工具输入输出是什么，类似命令行实时滚动输出
2. **Markdown结果渲染** - 最终报告以完整Markdown格式渲染，像专业阅读器一样展示
3. **标签页切换** - 右侧区域提供「运行日志」和「结果查看」两个标签页可切换查看

## Layout Design

保持现有的左右布局不变：

```
┌─────────────────────────┬─────────────────────────┐
│  Left: Chat Section     │  Right: Process/Result  │
│                         │  [日志] [结果]  ← 标签  │
│  • User input           │                         │
│  • Question history     │  • Content (log或result)│
│                         │                         │
└─────────────────────────┴─────────────────────────┘
```

**布局说明：**
- 左侧保持原样：用户输入框 + 聊天消息历史
- 右侧顶部添加标签切换栏：「智能体运行日志」和「结果查看」
- 用户可自由切换查看日志或结果
- 下载按钮始终保持可见

## Backend Architecture Changes

### 1. Step Callback Integration

CrewAI 0.11+ 支持`step_callback`参数，我们在创建Crew时注册回调：

```python
def step_callback(step_func):
    # Extract information from step
    # agent = step_func.agent
    # action = step_func.action
    # tool_name = ...
    # tool_input = ...
    # tool_output = ...
    
    # Send event through SSE queue
    event = {
        'type': 'agent_step',
        'agent': agent.role,
        'action': action,
        'tool': tool_name,
        'input': tool_input,
        'output': tool_output,
    }
    task_info['stream_queue'].put(json.dumps(event))
```

### 2. New Event Types for SSE

| 事件类型 | 说明 | 字段 |
|---------|------|------|
| `task_start` | 任务开始 | `task`: 任务描述 |
| `task_complete` | 任务完成 | `task`: 任务描述, `result`: 结果摘要 |
| `agent_step` | Agent执行一步 | `agent`: agent名称, `action`: 动作描述, `tool`: 工具名(如果调用工具), `input`: 工具输入, `output`: 工具输出 |
| `tool_start` | 工具开始调用 | `agent`: agent名称, `tool`: 工具名, `input`: 输入参数 |
| `tool_end` | 工具调用完成 | `agent`: agent名称, `tool`: 工具名, `output`: 输出结果, `success`: bool |
| `complete` | 全部完成 | `result`: 最终Markdown结果, `output_file`: 文件路径 |
| `error` | 出错 | `error`: 错误信息 |
| `end` | 流结束 | - |

### 3. Modified app.py Flow

1. `POST /api/ask` 接收问题，创建task_id
2. 启动后台线程 `run_crew_task`
3. 在 `run_crew_task` 中创建Crew时注册 `step_callback`
4. 每一步执行时，callback将事件放入SSE队列
5. 前端通过 `GET /api/stream/<task_id>` SSE连接接收实时事件
6. 完成后发送 `complete` 事件携带最终结果

## Frontend Changes

### 1. Tabs Component

右侧顶部添加标签切换：
```css
.tabs {
  display: flex;
  gap: 0;
  margin-bottom: 15px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.tab-btn {
  padding: 10px 20px;
  background: transparent;
  border: none;
  color: #888;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.tab-btn.active {
  color: #00d4ff;
  border-bottom-color: #00d4ff;
}
.tab-content {
  display: none;
  flex: 1;
  overflow-y: auto;
}
.tab-content.active {
  display: block;
}
```

### 2. Log Display (Terminal-like)

保持现有`log-item`样式基础上，增加工具调用的特殊样式：
- `tool_start` - 黄色边框，显示"工具: xxx 输入: yyy"
- `tool_end` - 绿色边框，显示"输出: zzz"

### 3. Markdown Rendering

引入 **marked.js** CDN来渲染Markdown：
- 支持所有标准Markdown语法：标题、列表、代码块、引用、表格、链接
- 添加相应CSS样式适配深色主题

CSS for rendered Markdown:
```css
.markdown-body h1, .markdown-body h2, .markdown-body h3 {
  color: #00d4ff;
  margin: 15px 0 10px 0;
}
.markdown-body code {
  background: rgba(255,255,255,0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}
.markdown-body pre {
  background: rgba(0,0,0,0.3);
  padding: 15px;
  border-radius: 8px;
  overflow-x: auto;
}
.markdown-body table {
  border-collapse: collapse;
  width: 100%;
}
.markdown-body td, .markdown-body th {
  border: 1px solid rgba(255,255,255,0.1);
  padding: 8px 12px;
}
```

### 4. Download Button

保持原有下载功能不变，始终显示在结果标签页底部。

## Files to Modify

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app.py` | 修改 | 添加step_callback，注册到Crew，新增事件类型支持 |
| `templates/index.html` | 大幅修改 | 添加标签切换、引入marked.js、添加Markdown样式、更新日志处理 |

## Verification

测试步骤：

1. 启动Web: `python app.py`
2. 打开浏览器 `http://localhost:5000`
3. 输入问题，提交
4. 验证：日志区域是否实时滚动显示各个步骤、各个agent、各个工具调用的输入输出
5. 验证：切换到结果标签，是否正确渲染Markdown格式（标题、列表、代码块都正确显示）
6. 验证：点击下载按钮，是否能正确下载Markdown文件
7. 验证：滚动是否正常，新日志自动滚动到底部

## Risk Assessment

- **Risk**: step_callback的数据结构可能因CrewAI版本变化而变化 → 我们做了防御性编程，如果某些字段不存在显示占位符
- **Risk**: 过快的事件推送可能导致前端渲染压力 → 实际每个工具调用只有2-3个事件，不会有问题

## Success Criteria

- [ ] 用户能在输入框输入问题并提交
- [ ] 运行过程中，日志区域实时显示：哪个agent在工作，调用了哪个工具，工具输入是什么，输出是什么
- [ ] 日志一条条动态添加，自动滚动到底部，支持向上滚动翻看历史
- [ ] 完成后可切换到结果标签页，看到完整渲染的Markdown报告，格式正确
- [ ] 可点击下载按钮下载完整Markdown文件

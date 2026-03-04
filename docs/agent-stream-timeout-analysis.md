# Agent 流式响应超时问题分析报告

> **文档创建时间**：2026-03-04  
> **问题类型**：框架限制导致的流式响应中断  
> **影响范围**：长时间运行的工具调用（如视频生成）

---

## 📋 目录

1. [问题描述](#1-问题描述)
2. [问题现象](#2-问题现象)
3. [问题分析](#3-问题分析)
4. [解决方案](#4-解决方案)
5. [附录：关键代码对比](#5-附录关键代码对比)

---

## 1. 问题描述

### 1.1 背景

在使用 Agent 生成视频时，工具执行时间较长（约 11 分钟），虽然工具内部日志显示"视频生成成功"，但用户界面始终显示"请耐心等待"，最终用户看不到生成结果。

### 1.2 问题截图

**用户界面状态**：

![用户界面截图](https://code.coze.cn/api/sandbox/coze_coding/file/proxy?expire_time=-1&file_path=assets%2Fimage.png&nonce=4c0324f5-eb14-44e4-ac13-0299a2523c77&project_id=7611753037392199723&sign=f7bc9848e6440dbd09503ed5fc91d48ce790ec323e22cbb56e1a494a879cce52)

界面显示：
- 提示文字："请耐心等待..."
- 工具状态：`⚒️ generate_long_video_v3`

**输出日志显示**：

```
✅ 长视频生成完成!
总场景数: 3 个
总视频时长: 15 秒
实际耗时: 661 秒
视频片段: 3 个
自动拼接: ✅ 已完成
最终画质: 1080p
```

### 1.3 核心矛盾

| 指标 | 工具执行 | 用户界面 |
|------|---------|---------|
| 状态 | ✅ 成功完成 | ⏳ 仍在等待 |
| 结果 | ✅ 已返回视频URL | ❌ 未显示结果 |
| 耗时 | 661秒（约11分钟） | 界面无响应 |

---

## 2. 问题现象

### 2.1 关键日志

从 `/app/work/logs/bypass/app.log` 提取的关键日志：

```log
# 工具执行成功
2026-03-04 12:55:58 info: {
  "message": "✅ 长视频生成完成！",
  "总场景数": "3 个",
  "总视频时长": "15 秒", 
  "实际耗时": "661 秒",
  "自动拼接": "✅ 已完成",
  "最终画质": "1080p"
}

# 关键错误：Producer 被取消
2026-03-04 12:55:58 info: {
  "message": "Producer cancelled during iteration for run_id: f36272c4-6059-4588-aa0d-e255b7b2471f",
  "level": "INFO"
}
```

### 2.2 执行时间线

```
12:44:01  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          │ 开始执行视频生成任务
          │
12:44:xx  │ 场景1生成中...（约5分钟）
          │
12:49:xx  │ 场景2生成中...（约3分钟）
          │
12:51:45  │ 场景3开始生成
          │
12:55:51  │ 场景3生成完成，开始自动拼接
          │
12:55:58  │ ✅ 工具返回成功结果
          │ ❌ Producer cancelled - 前端断开连接
          │ ❌ LLM 最终回复未发送
12:55:58  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 2.3 问题流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户请求生成视频                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LLM 决定调用 generate_long_video_v3               │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         工具开始执行                                  │
│                     (预计需要 10+ 分钟)                               │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
            ┌───────────┐   ┌───────────┐   ┌───────────┐
            │ 前端等待   │   │ 后端执行   │   │ 无心跳包   │
            │           │   │ 工具调用   │   │ 发送中...  │
            └───────────┘   └───────────┘   └───────────┘
                    │               │               │
                    │               │               │
                    ▼               │               │
            ┌───────────────────┐   │               │
            │ 超过前端超时阈值   │   │               │
            │ (默认约5-10分钟)  │   │               │
            └───────────────────┘   │               │
                    │               │               │
                    ▼               │               │
            ┌───────────────────┐   │               │
            │ 前端主动断开 SSE  │   │               │
            │ 连接              │   │               │
            └───────────────────┘   │               │
                    │               │               │
                    │       ┌───────┘               │
                    │       │                       │
                    │       ▼                       │
                    │   ┌───────────────────┐       │
                    │   │ 工具执行完成      │       │
                    │   │ 返回成功结果      │       │
                    │   └───────────────────┘       │
                    │               │               │
                    ▼               ▼               │
            ┌─────────────────────────────────────────────────────────┐
            │                    检测到连接已断开                        │
            │              Producer cancelled during iteration          │
            │                                                           │
            │    ❌ LLM 无法发送最终回复给用户                           │
            │    ❌ 用户看不到生成结果                                   │
            └─────────────────────────────────────────────────────────┘
```

---

## 3. 问题分析

### 3.1 根因定位

通过分析 `coze_coding_utils` 框架源码，发现问题根源：

**`AgentStreamRunner` 缺少心跳机制**

```python
# 位置：/usr/local/lib/python3.12/dist-packages/coze_coding_utils/helper/stream_runner.py

class AgentStreamRunner(BaseStreamRunner):
    async def astream(self, ...):
        # ...
        def producer():
            # 问题：没有心跳发送逻辑
            for sm in server_msgs_iter:
                if cancelled.is_set():
                    logger.info(f"Producer cancelled during iteration for run_id: {ctx.run_id}")
                    # ...
                loop.call_soon_threadsafe(q.put_nowait, sm.dict())
            # ...
        
        # 问题：没有启动 ping_sender 任务
        threading.Thread(target=lambda: context.run(producer), daemon=True).start()
        # 缺少：ping_task = asyncio.create_task(ping_sender())
```

### 3.2 对比分析

| 特性 | AgentStreamRunner | WorkflowStreamRunner |
|------|-------------------|---------------------|
| 心跳机制 | ❌ 无 | ✅ 有（30秒间隔） |
| 长任务支持 | ❌ 会超时 | ✅ 正常 |
| 超时处理 | 仅超时检测 | 心跳 + 超时检测 |
| 适用场景 | 快速响应 | 长时间工作流 |

### 3.3 WorkflowStreamRunner 的正确实现

```python
class WorkflowStreamRunner(BaseStreamRunner):
    async def astream(self, ...):
        # ...
        
        async def ping_sender():
            while True:
                await asyncio.sleep(PING_INTERVAL_SECONDS)  # 30秒
                current_time = time.time()
                if current_time - last_ping_time[0] >= PING_INTERVAL_SECONDS:
                    ping_msg = self._build_event(WorkflowEventType.PING, ctx)
                    await q.put((seq[0], ping_msg))
                    last_ping_time[0] = current_time

        ping_task = asyncio.create_task(ping_sender())  # 启动心跳任务
        
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield item
        finally:
            ping_task.cancel()  # 清理心跳任务
```

### 3.4 问题链条

```
1. 用户请求生成视频（需要10+分钟）
        │
        ▼
2. AgentStreamRunner 开始流式响应
        │
        ▼
3. 工具执行期间，没有任何消息发送给前端
   (AgentStreamRunner 没有心跳机制)
        │
        ▼
4. 前端 SSE 连接超时（默认超时时间）
        │
        ▼
5. 前端主动断开连接
        │
        ▼
6. 后端检测到 cancelled.is_set() = True
        │
        ▼
7. Producer 记录 "cancelled during iteration" 并退出
        │
        ▼
8. LLM 的最终回复无法发送
        │
        ▼
9. 用户界面永远显示"请耐心等待"
```

---

## 4. 解决方案

### 4.1 框架层面（需要 Coze 平台支持）

**方案 A：为 AgentStreamRunner 添加心跳机制**

```python
# 建议的修改方案
class AgentStreamRunner(BaseStreamRunner):
    async def astream(self, ...):
        # ...
        last_heartbeat = [time.time()]
        
        async def heartbeat_sender():
            while True:
                await asyncio.sleep(30)  # 30秒心跳间隔
                if time.time() - last_heartbeat[0] >= 30:
                    # 发送心跳消息
                    ping_msg = create_ping_message(...)
                    await q.put(ping_msg)
                    last_heartbeat[0] = time.time()
        
        heartbeat_task = asyncio.create_task(heartbeat_sender())
        
        try:
            # ... 原有逻辑
        finally:
            heartbeat_task.cancel()
```

**方案 B：前端增加 SSE 超时时间**

- 针对视频生成等长时间任务，前端可以增加超时阈值
- 例如：从默认的 5 分钟增加到 20 分钟

### 4.2 应用层面（可临时缓解）

**方案 A：工具内发送中间进度**

```python
# 在工具执行过程中，定期发送进度消息
@tool
def generate_long_video_v3(...):
    # 场景生成循环
    for i, scene in enumerate(scenes):
        # 生成前发送进度
        yield {"type": "progress", "message": f"正在生成场景 {i+1}/{len(scenes)}"}
        
        # 执行生成
        result = generate_scene(scene)
        
        # 生成后发送结果
        yield {"type": "scene_complete", "scene_index": i+1}
```

**注意**：当前 LangChain `@tool` 装饰器不支持 yield，需要使用其他机制。

**方案 B：拆分长任务**

```python
# 将长时间任务拆分为多个短任务
# 例如：每个场景单独调用，前端显示进度条

场景1 → 场景2 → 场景3 → 自动拼接
  │        │        │        │
  ▼        ▼        ▼        ▼
用户可以看到每个场景的进度
```

### 4.3 用户层面（临时措施）

| 措施 | 说明 |
|------|------|
| 保持页面活跃 | 不要切换标签页或刷新页面 |
| 查看输出日志 | 工具结果会在"输出"标签页显示 |
| 延长等待 | 视频生成需要 10-15 分钟 |

---

## 5. 附录：关键代码对比

### 5.1 AgentStreamRunner（问题代码）

```python
async def astream(self, payload, graph, run_config, ctx, run_opt=None):
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()
    cancelled = threading.Event()

    def producer():
        # 问题：长时间执行无心跳
        items = graph.stream(stream_input, stream_mode="messages", config=run_config)
        for sm in server_msgs_iter:
            if cancelled.is_set():  # 前端断开后才会触发
                logger.info(f"Producer cancelled during iteration")
                return
            loop.call_soon_threadsafe(q.put_nowait, sm.dict())

    # 问题：没有启动心跳任务
    threading.Thread(target=lambda: context.run(producer), daemon=True).start()
    
    while True:
        item = await q.get()
        if item is None:
            break
        yield item
```

### 5.2 WorkflowStreamRunner（正确实现）

```python
async def astream(self, payload, graph, run_config, ctx, run_opt=None):
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()
    last_ping_time = [time.time()]

    async def ping_sender():
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)  # 30秒
            if time.time() - last_ping_time[0] >= PING_INTERVAL_SECONDS:
                ping_msg = self._build_event(WorkflowEventType.PING, ctx)
                await q.put(ping_msg)
                last_ping_time[0] = time.time()

    ping_task = asyncio.create_task(ping_sender())  # 启动心跳
    
    try:
        while True:
            item = await q.get()
            if item is None:
                break
            yield item
    finally:
        ping_task.cancel()  # 清理
```

### 5.3 关键差异对比

| 代码位置 | AgentStreamRunner | WorkflowStreamRunner |
|---------|-------------------|---------------------|
| 心跳任务 | ❌ 未创建 | ✅ `asyncio.create_task(ping_sender())` |
| 心跳发送 | ❌ 无 | ✅ 每30秒发送一次 PING |
| 长任务 | ❌ 会因无消息而超时 | ✅ 保持连接活跃 |
| 连接保活 | ❌ 无机制 | ✅ 心跳机制 |

---

## 📝 总结

| 项目 | 内容 |
|------|------|
| **问题** | 长时间工具执行导致前端 SSE 连接超时断开 |
| **根因** | `AgentStreamRunner` 缺少心跳机制 |
| **影响** | 工具执行成功但用户看不到结果 |
| **解决方案** | 框架层面添加心跳 / 前端增加超时 / 拆分长任务 |
| **优先级** | 高（影响用户体验） |
| **责任方** | 需要框架支持（coze_coding_utils） |

---

## 📚 相关文档

- [coze_coding_utils 源码](file:///usr/local/lib/python3.12/dist-packages/coze_coding_utils/helper/stream_runner.py)
- [SSE (Server-Sent Events) 规范](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [LangChain Tool 文档](https://python.langchain.com/docs/modules/tools/)

---

> **文档版本**：v1.0  
> **最后更新**：2026-03-04  
> **作者**：AI Assistant

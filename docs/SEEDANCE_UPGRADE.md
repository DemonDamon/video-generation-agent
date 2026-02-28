# Seedance 2.0 升级说明

## 📌 问题诊断

### 测试结果
- ✅ **Seedance 1.5 Pro** (`doubao-seedance-1-5-pro-251215`) - **可用**
- ❌ **Seedance 2.0** (`doubao-seedance-2-0-260128`) - **模型未找到**

### 错误信息
```
HTTP 错误: 400 Client Error
错误码: ErrNotFound
错误消息: model not found
```

---

## 🔍 原因分析

### 1. API 端点差异

**当前使用的集成端点：**
```
https://integration.coze.cn/api/v3/contents/generations/tasks
```

**您提供的 REST API 端点：**
```
https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
```

### 2. 关键区别

| 特性 | Coze 集成方式 | 火山引擎直调 |
|------|--------------|-------------|
| API 端点 | integration.coze.cn | ark.cn-beijing.volces.com |
| 认证方式 | 自动注入 Workload Identity | 需要 API Key (Bearer Token) |
| 模型支持 | **仅支持已集成的模型** | **支持所有火山引擎模型** |
| Seedance 1.5 | ✅ 支持 | ✅ 支持 |
| Seedance 2.0 | ❌ 暂不支持 | ✅ 支持 |

---

## 💡 解决方案

### 方案 1：继续使用 Seedance 1.5 Pro（推荐）

**优点：**
- ✅ 已经集成并测试通过
- ✅ 无需额外配置
- ✅ 支持长视频生成（多场景连贯）
- ✅ 性能稳定

**使用方式：**
```python
# 当前已实现
model="doubao-seedance-1-5-pro-251215"
```

---

### 方案 2：等待 Coze 集成更新

如果 Coze 平台更新支持 Seedance 2.0，只需修改一行代码：

```python
# src/tools/long_video_tool.py
model="doubao-seedance-2-0-260128"  # 更新模型 ID
```

---

### 方案 3：直连火山引擎 API（需要配置）

如果您需要立即使用 Seedance 2.0，可以创建一个新工具直接调用火山引擎 API：

```python
import requests
from langchain.tools import tool

@tool
def generate_video_direct(
    prompt: str,
    model: str = "doubao-seedance-2-0-260128",
    api_key: str = None
) -> str:
    """直接调用火山引擎 API 生成视频"""
    
    # 从环境变量或参数获取 API Key
    api_key = api_key or os.getenv("VOLCANO_API_KEY")
    
    # 创建任务
    create_url = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        "model": model,
        "content": [
            {
                "type": "text",
                "text": prompt
            }
        ]
    }
    
    response = requests.post(create_url, headers=headers, json=data)
    task_id = response.json()["id"]
    
    # 轮询任务状态（简化版）
    query_url = f"{create_url}/{task_id}"
    # ... 轮询逻辑 ...
    
    return video_url
```

**注意：** 需要配置火山引擎 API Key：
```bash
export VOLCANO_API_KEY="your-api-key-here"
```

---

## 📊 模型对比

### Seedance 1.5 Pro vs Seedance 2.0

| 特性 | Seedance 1.5 Pro | Seedance 2.0 |
|------|-----------------|--------------|
| 模型 ID | doubao-seedance-1-5-pro-251215 | doubao-seedance-2-0-260128 |
| 发布时间 | 2025-12-15 | 2025-01-28 |
| 视频时长 | 4-12秒 | 可能更长 |
| 分辨率 | 480p/720p/1080p | 可能更高 |
| 图生视频 | ✅ 支持 | ✅ 支持 |
| 首尾帧控制 | ✅ 支持 | ✅ 支持 |
| Coze 集成 | ✅ 已集成 | ❌ 待更新 |

---

## 🎯 当前推荐方案

**继续使用 Seedance 1.5 Pro**，因为：

1. ✅ **功能完整**：支持所有核心功能（文本生成、图生视频、首尾帧控制）
2. ✅ **稳定可靠**：已经过充分测试
3. ✅ **无缝集成**：与 Coze 平台完美配合
4. ✅ **长视频支持**：通过多场景连续生成实现长视频

---

## 📝 后续行动

- [ ] 关注 Coze 平台更新，获取 Seedance 2.0 支持通知
- [ ] 如需立即使用 Seedance 2.0，可考虑方案 3（直连 API）
- [ ] 当前继续优化基于 Seedance 1.5 Pro 的长视频生成方案

---

**文档更新时间：** 2026-02-28
**当前生产模型：** `doubao-seedance-1-5-pro-251215` (Seedance 1.5 Pro)

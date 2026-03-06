# 🎬 Video Generation Agent

<div align="center">

[![LangChain](https://img.shields.io/badge/LangChain-1.0-green.svg)](https://github.com/langchain-ai/langchain)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0-blue.svg)](https://github.com/langchain-ai/langgraph)
[![Python](https://img.shields.io/badge/Python-3.10+-yellow.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-red.svg)](LICENSE)

**基于 LangChain 的长视频生成智能体，支持场景规划和连贯生成**

[English](./README_EN.md) | 简体中文

</div>

---

## 📖 目录

- [✨ 特性](#-特性)
- [🏗️ 架构](#️-架构)
- [🚀 快速开始](#-快速开始)
- [💡 使用示例](#-使用示例)
- [🔧 配置说明](#-配置说明)
- [📁 项目结构](#-项目结构)
- [🤝 贡献指南](#-贡献指南)
- [📄 许可证](#-许可证)

---

## ✨ 特性

### 🎥 智能视频生成
- **场景自动规划**：AI 自动分析用户需求，拆分为多个连贯场景
- **首尾帧连续技术**：确保场景之间的视觉连贯性，无跳帧
- **多场景拼接**：自动将多个视频片段拼接为完整长视频
- **高清画质**：支持 1080p 分辨率输出

### 🧠 智能交互
- **多轮对话**：支持上下文记忆，理解"再生成一个类似的"等指令
- **方案确认**：执行前展示场景规划，用户确认后再执行
- **实时进度**：四阶段透明化流程，实时反馈生成状态

### 🛠️ 技术亮点
- **心跳保活**：30秒心跳机制，防止长时间任务连接超时
- **链接管理**：支持重新生成有效签名 URL，解决链接过期问题
- **滑动窗口记忆**：保留最近 20 轮对话，避免上下文过长

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Video Generation Agent                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────┐ │
│  │   用户输入   │───▶│   Agent    │───▶│       工具调用层             │ │
│  └─────────────┘    │  (doubao)   │    ├─────────────────────────────┤ │
│                     └─────────────┘    │ • generate_long_video_v3    │ │
│                           │            │ • get_video_url             │ │
│                           │            │ • merge_videos              │ │
│                           ▼            └─────────────────────────────┘ │
│                    ┌─────────────┐                                      │
│                    │  记忆管理    │                                      │
│                    │ (滑动窗口)   │                                      │
│                    └─────────────┘                                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
              ┌──────────────────────────────────────────┐
              │          Seedance 视频生成服务            │
              │       (doubao-seedance-1-5-pro-251215)    │
              └──────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- FFmpeg (用于视频拼接)

### 安装依赖

```bash
# 克隆仓库
git clone https://github.com/DemonDamon/video-generation-agent.git
cd video-generation-agent

# 安装依赖
pip install -r requirements.txt

# 安装 FFmpeg (如果未安装)
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Windows
# 下载 https://ffmpeg.org/download.html 并添加到 PATH
```

### 本地运行

```bash
# 启动 HTTP 服务
bash scripts/http_run.sh -m http -p 5000

# 服务将在 http://localhost:5000 启动
```

### 使用客户端

```bash
# 交互模式
python scripts/video_agent_client.py --token "YOUR_TOKEN"

# 单次消息
python scripts/video_agent_client.py \
  --token "YOUR_TOKEN" \
  --message "帮我生成一个小猫玩球的视频"
```

---

## 💡 使用示例

### 基础视频生成

```bash
# 交互模式对话示例
👤 你: 帮我生成一个哥斯拉和钢铁侠对战的视频

🤖 Agent: 好的！我来为您规划场景：

1. 场景一：城市天际线，哥斯拉从海中浮现
2. 场景二：钢铁侠飞来迎战
3. 场景三：双方激烈对战
4. 场景四：战斗高潮，能量爆炸

确认生成吗？

👤 你: 确认

🤖 Agent: 开始生成...

🔧 调用工具: generate_long_video_v3

📋 场景详情:
   场景 0: ✅ (耗时: 180秒)
   场景 1: ✅ (耗时: 195秒)
   场景 2: ✅ (耗时: 188秒)
   场景 3: ✅ (耗时: 202秒)

🎬 视频链接: https://tos-cn-beijing.ivolces.com/...

📊 生成统计:
   总场景数: 4
   视频时长: 20秒
   执行耗时: 765秒
   自动拼接: ✅
```

### 多轮对话

```bash
# 继续之前的对话
👤 你: 再生成一个续集，他们联手对抗外星人

🤖 Agent: 好的！基于之前的视频，我来生成续集...

# 查看历史视频
👤 你: history

📹 历史视频:
   1. https://tos-cn-beijing.ivolces.com/xxx
      时间: 2024-01-15T10:30:00
   2. https://tos-cn-beijing.ivolces.com/yyy
      时间: 2024-01-15T10:45:00
```

### API 调用

```python
import json
import requests

url = "https://your-domain.com/stream_run"
headers = {
    "Authorization": "Bearer YOUR_TOKEN",
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}

payload = {
    "content": {
        "query": {
            "prompt": [{"type": "text", "content": {"text": "生成一个日落海滩的视频"}}]
        }
    },
    "type": "query",
    "session_id": "my-session-001",  # 相同 session_id 实现多轮对话
    "project_id": "7611753037392199723"
}

response = requests.post(url, headers=headers, json=payload, stream=True)
for line in response.iter_lines(decode_unicode=True):
    if line and line.startswith("data:"):
        data = json.loads(line[5:].strip())
        print(json.dumps(data, ensure_ascii=False, indent=2))
```

---

## 🔧 配置说明

### Agent 配置

配置文件位于 `config/agent_llm_config.json`：

```json
{
  "config": {
    "model": "doubao-seed-1-8-251228",
    "temperature": 0.7,
    "top_p": 0.9,
    "max_completion_tokens": 10000,
    "timeout": 1800,
    "thinking": "disabled"
  },
  "sp": "你是一个专业的视频生成 Agent...",
  "tools": ["generate_long_video_v3", "get_video_url", "merge_videos"]
}
```

### 关键参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `model` | Agent 使用的大模型 | `doubao-seed-1-8-251228` |
| `temperature` | 生成温度 | `0.7` |
| `timeout` | 请求超时时间（秒） | `1800` (30分钟) |
| `max_completion_tokens` | 最大生成 token 数 | `10000` |

### 视频生成参数

```python
# 支持的分辨率
resolution = "1080p"  # 或 "720p", "480p"

# 单场景时长范围
duration_range = (4, 12)  # 4-12 秒

# 记忆窗口
max_messages = 40  # 保留最近 40 条消息（约 20 轮对话）
```

---

## 📁 项目结构

```
.
├── config/                       # 配置目录
│   └── agent_llm_config.json    # Agent 模型配置
├── docs/                         # 文档目录
│   ├── agent-stream-timeout-analysis.md
│   └── video-agent-client-guide.md
├── scripts/                      # 脚本目录
│   ├── video_agent_client.py    # 客户端脚本
│   ├── local_run.sh             # 本地运行脚本
│   └── http_run.sh              # HTTP 服务脚本
├── src/                          # 源码目录
│   ├── agents/                   # Agent 代码
│   │   └── agent.py             # 主 Agent 实现
│   ├── tools/                    # 工具定义
│   │   ├── long_video_tool_v3.py    # 长视频生成工具
│   │   ├── video_merge_tool.py      # 视频拼接工具
│   │   └── video_url_tool.py        # URL 管理工具
│   ├── utils/                    # 工具函数
│   │   └── heartbeat_stream_runner.py  # 心跳流式响应
│   ├── storage/                  # 存储层
│   │   └── memory/              # 记忆管理
│   └── main.py                   # 应用入口
├── tests/                        # 测试目录
├── assets/                       # 资源文件
├── requirements.txt              # Python 依赖
├── README.md                     # 项目说明
└── AGENT.md                      # Agent 规范文档
```

---

## 🔌 核心工具

### generate_long_video_v3

智能长视频生成工具，支持：
- 自动场景规划
- 首尾帧连续
- 自动拼接
- 1080p 高清输出

### merge_videos

视频拼接工具：
- FFmpeg 无损拼接
- 自动上传对象存储
- 返回完整视频链接

### get_video_url

链接管理工具：
- 根据任务 ID 重新生成签名 URL
- 解决链接过期问题

---

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 单场景生成时间 | 3-5 分钟 |
| 4 场景视频总耗时 | 约 15 分钟 |
| 支持视频时长 | 4-48 秒 |
| 支持分辨率 | 480p / 720p / 1080p |
| 记忆保留 | 最近 20 轮对话 |

---

## 🛠️ 开发指南

### 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_agent.py -v
```

### 本地开发

```bash
# 运行流程
bash scripts/local_run.sh -m flow

# 运行单个节点
bash scripts/local_run.sh -m node -n node_name
```

### 添加新工具

1. 在 `src/tools/` 下创建新工具文件
2. 使用 `@tool` 装饰器定义工具
3. 在 `agent.py` 中注册工具
4. 更新 `config/agent_llm_config.json` 的 tools 列表

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出新功能建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

### 代码规范

- 遵循 PEP 8 Python 代码规范
- 添加必要的注释和文档字符串
- 为新功能编写单元测试

---

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

---

## 🙏 致谢

- [LangChain](https://github.com/langchain-ai/langchain) - 强大的 LLM 应用框架
- [LangGraph](https://github.com/langchain-ai/langgraph) - 状态图工作流引擎
- [Seedance](https://www.volcengine.com/) - 火山引擎视频生成模型

---

## 📮 联系方式

- 项目地址: [https://github.com/DemonDamon/video-generation-agent](https://github.com/DemonDamon/video-generation-agent)
- 问题反馈: [Issues](https://github.com/DemonDamon/video-generation-agent/issues)

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个 Star ⭐**

</div>

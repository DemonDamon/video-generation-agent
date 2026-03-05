# 视频生成 Agent 客户端使用指南

## 快速开始

### 1. 单次对话

```bash
python scripts/video_agent_client.py \
  --token "YOUR_TOKEN" \
  --message "帮我生成一个小猫玩球的视频"
```

### 2. 交互模式（多轮对话）

```bash
python scripts/video_agent_client.py --token "YOUR_TOKEN"
```

进入交互模式后：
- 直接输入消息与 Agent 对话
- 输入 `quit` 退出
- 输入 `new` 开始新会话
- 输入 `history` 查看生成的视频历史

### 3. 指定会话 ID（继续之前的对话）

```bash
python scripts/video_agent_client.py \
  --token "YOUR_TOKEN" \
  --session "my-video-session-001"
```

## 功能特性

### ✅ 友好的输出格式

```
============================================================
📤 用户输入: 帮我生成一个哥斯拉大战钢铁侠的视频
============================================================

🤖 Agent: 好的！我来为您生成一个哥斯拉与钢铁侠对战的精彩视频。

让我先规划一下场景：

1. 场景一：城市天际线，哥斯拉从海中浮现
2. 场景二：钢铁侠飞来迎战
3. 场景三：双方激烈对战
4. 场景四：战斗高潮，能量爆炸

确认生成吗？

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

### ✅ 自动保存视频链接

所有生成的视频链接会自动保存到历史记录，可通过 `history` 命令查看。

### ✅ 多轮对话支持

使用相同的 `session_id` 即可保持上下文：

```bash
# 第一轮
python scripts/video_agent_client.py \
  --token "YOUR_TOKEN" \
  --session "my-session" \
  -m "生成一个小猫视频"

# 第二轮（Agent 会记住之前的对话）
python scripts/video_agent_client.py \
  --token "YOUR_TOKEN" \
  --session "my-session" \
  -m "再生成一个续集"
```

## 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--url` | API 地址 | `https://tpjcdhrn36.coze.site` |
| `--token` | 授权令牌（必填） | - |
| `--project` | 项目 ID | `7611753037392199723` |
| `--session` | 会话 ID | 自动生成 |
| `--message, -m` | 单次消息 | - |

## 示例场景

### 场景 1: 生成并优化视频

```bash
# 交互模式
$ python scripts/video_agent_client.py --token "YOUR_TOKEN"

👤 你: 帮我生成一个日落海滩的视频

🤖 Agent: 好的！我来生成一个日落海滩的视频...

🎬 视频链接: https://tos-cn-beijing.ivolces.com/...

👤 你: 这个太短了，能生成一个30秒的吗？

🤖 Agent: 好的，我会生成一个更长的30秒视频，分多个场景...

🎬 视频链接: https://tos-cn-beijing.ivolces.com/...
```

### 场景 2: 查看历史

```bash
👤 你: history

📹 历史视频:
   1. https://tos-cn-beijing.ivolces.com/xxx
      时间: 2024-01-15T10:30:00
   2. https://tos-cn-beijing.ivolces.com/yyy
      时间: 2024-01-15T10:45:00
```

# Seedance 2.0 升级说明

## ✅ 已升级至 Seedance 2.0

**当前生产模型：** `doubao-seedance-2-0-260128` (Seedance 2.0)

---

## 📊 模型对比

### Seedance 1.5 Pro vs Seedance 2.0

| 特性 | Seedance 1.5 Pro | Seedance 2.0 |
|------|-----------------|--------------|
| 模型 ID | doubao-seedance-1-5-pro-251215 | doubao-seedance-2-0-260128 |
| 发布时间 | 2025-12-15 | 2025-01-28 |
| 视频时长 | 4-12秒 | 4-12秒 |
| 分辨率 | 480p/720p/1080p | 480p/720p/1080p |
| 图生视频 | ✅ 支持 | ✅ 支持 |
| 首尾帧控制 | ✅ 支持 | ✅ 支持 |
| 生成质量 | 高 | **更高** |
| 语义理解 | 良好 | **更强** |
| Coze 集成 | ✅ 已集成 | ✅ **已支持** |

---

## 🚀 升级后的优势

### Seedance 2.0 主要改进

1. **更好的语义理解**：能更准确理解复杂的场景描述
2. **更高的生成质量**：画面细节更丰富，运动更自然
3. **更强的连贯性**：多场景之间的视觉连贯性更好
4. **更优的图生视频**：基于参考图生成更符合预期的视频

---

## 🔧 代码配置

### 当前配置（已更新）

```python
# src/tools/long_video_tool_v3.py
video_url, response, current_last_frame = client.video_generation(
    content_items=content_items,
    model="doubao-seedance-2-0-260128",  # ✅ 已升级至 Seedance 2.0
    resolution=resolution,
    ratio=ratio,
    duration=duration,
    watermark=watermark,
    return_last_frame=return_last_frame
)
```

### 如果需要回退到 1.5 Pro

```python
model="doubao-seedance-1-5-pro-251215"  # 回退到 1.5 Pro
```

---

## 📝 使用建议

1. **使用 Seedance 2.0** 进行新项目开发，享受更好的生成效果
2. **提供详细的场景描述**，充分利用 2.0 的语义理解能力
3. **使用首尾帧控制**，实现更好的多场景连贯性

---

## 🎯 示例对比

### 场景描述
```
"一只金毛犬在夕阳下的海滩上奔跑，追逐着飞盘"
```

### Seedance 1.5 Pro 效果
- 狗狗动作流畅
- 场景氛围较好
- 细节处理良好

### Seedance 2.0 效果（升级后）
- 狗狗毛发细节更丰富
- 夕阳光影效果更自然
- 飞盘飞行轨迹更真实
- 整体画面更有电影感

---

**文档更新时间：** 2026-03-05
**当前生产模型：** `doubao-seedance-2-0-260128` (Seedance 2.0)

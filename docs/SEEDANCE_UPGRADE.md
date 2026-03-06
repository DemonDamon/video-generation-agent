# Seedance 模型说明

## ✅ 当前使用模型

**生产模型：** `doubao-seedance-1-5-pro-251215` (Seedance 1.5 Pro)

---

## 📊 模型对比

### Seedance 1.5 Pro vs Seedance 2.0

| 特性 | Seedance 1.5 Pro | Seedance 2.0 |
|------|-----------------|--------------|
| 模型 ID | doubao-seedance-1-5-pro-251215 | doubao-seedance-2-0-260128 |
| 发布时间 | 2025-12-15 | 2026-01-28 |
| 视频时长 | 4-12秒 | 4-12秒 |
| 分辨率 | 480p/720p/1080p | 480p/720p/1080p |
| 图生视频 | ✅ 支持 | ✅ 支持 |
| 首尾帧控制 | ✅ 支持 | ✅ 支持 |
| 生成质量 | 高 | 更高 |
| Coze 集成 | ✅ **已支持** | ❌ 暂不支持 |

---

## ⚠️ 关于 Seedance 2.0

**当前状态：** Coze 集成环境暂不支持 Seedance 2.0

```
错误信息: model not found
模型 ID: doubao-seedance-2-0-260128
```

---

## 🔧 配置方式

模型配置位于 `config/agent_llm_config.json`:

```json
{
    "video_model": {
        "model": "doubao-seedance-1-5-pro-251215",
        "name": "Seedance 1.5 Pro"
    }
}
```

### 切换模型

如需切换模型，修改配置文件中的 `video_model.model` 字段即可：

```json
{
    "video_model": {
        "model": "doubao-seedance-2-0-260128",  // 待 Coze 集成支持后使用
        "name": "Seedance 2.0"
    }
}
```

---

## 📝 更新计划

- [ ] 关注 Coze 平台更新，获取 Seedance 2.0 支持通知
- [ ] Seedance 2.0 可用后，更新配置即可使用

---

**文档更新时间：** 2026-03-06
**当前生产模型：** `doubao-seedance-1-5-pro-251215` (Seedance 1.5 Pro)

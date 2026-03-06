# 本地运行指南

当 Coze 平台积分不足时，可以在本地启动服务，使用自己的 API 密钥，不消耗平台积分。

## 一、环境要求

- Python 3.10+
- FFmpeg（用于视频拼接）
- 豆包/火山引擎 API 密钥（LLM + 视频生成）
- 对象存储（S3 兼容，用于视频存储）

## 二、环境变量配置

本地运行时，`load_env.sh` 无法从 Coze 平台拉取变量，需要**手动配置**以下环境变量。

### 2.1 创建 `.env.local` 并导出

复制 `.env.example` 为 `.env.local`，填入你的配置后执行：

```bash
# Windows (PowerShell)
Get-Content .env.local | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process') } }

# Windows (Git Bash / WSL)
export $(grep -v '^#' .env.local | xargs)

# Linux / macOS
source .env.local   # 或: export $(grep -v '^#' .env.local | xargs)
```

### 2.2 必需变量

| 变量名 | 说明 | 获取方式 |
|--------|------|----------|
| `COZE_WORKLOAD_IDENTITY_API_KEY` | 豆包 API Key | [火山引擎控制台](https://console.volcengine.com/) → 访问控制 → API 密钥 |
| `COZE_INTEGRATION_MODEL_BASE_URL` | 豆包 API 基础 URL | 如 `https://ark.cn-beijing.volces.com/api/v3` |

### 2.3 视频存储（二选一）

**方式一：本地文件（推荐，零配置）**  
不配置对象存储时，视频自动保存到 `output/videos/` 目录，可通过 `file://` 路径或 HTTP 访问。

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LOCAL_VIDEO_OUTPUT_DIR` | 本地输出目录 | `output/videos` |
| `LOCAL_VIDEO_BASE_URL` | 服务地址（用于生成可点击链接） | 如 `http://localhost:5000` |

**方式二：对象存储（S3 兼容）**  
适用于生产环境或需要公网分享的场景。

| 变量名 | 说明 |
|--------|------|
| `COZE_BUCKET_ENDPOINT_URL` | 对象存储端点 |
| `COZE_BUCKET_NAME` | 存储桶名称 |

### 2.4 其他可选变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `COZE_WORKSPACE_PATH` | 项目根目录 | 当前目录 |
| `PGDATABASE_URL` | 数据库连接（若使用记忆） | 可选 |

## 三、启动本地服务

### 方式一：直接启动（推荐）

```bash
# 1. 先导出环境变量（见上文）
# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 HTTP 服务（默认端口 5000）
python src/main.py -m http -p 5000
```

### 方式二：使用脚本

```bash
# Windows
bash scripts/local_http_run.sh -p 5000

# 或直接
python src/main.py -m http -p 5000
```

服务启动后访问：`http://localhost:5000`

- 健康检查：`GET http://localhost:5000/health`
- 流式对话：`POST http://localhost:5000/stream_run`
- 任务提交：`POST http://localhost:5000/task/submit`

## 四、客户端连接本地服务

```bash
# 指定本地地址，token 本地可传任意非空字符串（若后端未校验）
python scripts/video_agent_client.py --url http://localhost:5000 --token local

# 或使用 .token 文件（内容填 local 即可）
echo "local" > .token
python scripts/video_agent_client.py --url http://localhost:5000
```

## 五、注意事项

1. **视频生成模型**：`doubao-seedance-1-5-pro-251215` 需在火山引擎开通对应模型权限。
2. **视频存储**：未配置 `COZE_BUCKET_*` 时，视频自动保存到 `output/videos/`，可通过 `file://` 路径打开；设置 `LOCAL_VIDEO_BASE_URL=http://localhost:5000` 可生成可点击的 HTTP 链接（`http://localhost:5000/videos/xxx.mp4`）。
3. **本地无 Coze 网关**：请求无需 Coze 平台 token，客户端传 `local` 或任意字符串即可。
4. **积分消耗**：本地运行时，LLM 和视频生成调用的是你自己的 API Key，消耗的是火山引擎/豆包账户的配额，与 Coze 平台积分无关。

## 六、常见问题

**Q: 启动报错 `COZE_WORKLOAD_IDENTITY_API_KEY` 未设置？**  
A: 确保已导出环境变量，或在 `.env.local` 中正确配置。

**Q: 视频生成失败？**  
A: 检查 `COZE_BUCKET_*` 配置，以及火山引擎是否开通 Seedance 视频模型权限。

**Q: 客户端连不上？**  
A: 确认服务已启动、端口正确，且客户端 `--url` 指向 `http://localhost:5000`。

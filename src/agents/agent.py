"""
Long Video Generation Agent - Enhanced V3
基于 Seedance 1.5 Pro 的长视频生成智能体
支持：自动拼接 + 1080p高清 + 专业镜头语言
"""

import os
import json
from typing import Annotated
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from coze_coding_utils.runtime_ctx.context import default_headers
from storage.memory.memory_saver import get_memory_saver

# 导入所有工具
from tools.long_video_tool import generate_long_video, generate_single_video
from tools.long_video_tool_v2 import generate_long_video_with_progress
from tools.long_video_tool_v3 import (
    generate_long_video_v3,
    optimize_scene_description,
    get_video_url as get_video_url_v3
)
from tools.video_merge_tool import merge_videos, get_video_info
from tools.video_url_helper import get_video_url, list_recent_videos

# 配置文件路径
LLM_CONFIG = "config/agent_llm_config.json"

# 默认保留最近 20 轮对话 (40 条消息)
MAX_MESSAGES = 40


def _windowed_messages(old, new):
    """滑动窗口: 只保留最近 MAX_MESSAGES 条消息"""
    return add_messages(old, new)[-MAX_MESSAGES:]  # type: ignore


class AgentState(MessagesState):
    """Agent 状态，包含消息历史和滑动窗口"""
    messages: Annotated[list[AnyMessage], _windowed_messages]


def build_agent(ctx=None):
    """
    构建并返回视频生成 Agent 实例（增强版 V3）
    
    功能特点：
    - 自动拼接完整长视频
    - 默认1080p高清画质
    - 支持专业镜头语言优化
    - 实时进度反馈
    
    Args:
        ctx: 运行时上下文（可选）
    
    Returns:
        Agent 实例
    """
    # 获取工作目录
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
    config_path = os.path.join(workspace_path, LLM_CONFIG)
    
    # 读取配置文件
    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    # 获取 API 密钥和基础 URL
    api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY")
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL")
    
    # 初始化 LLM
    llm = ChatOpenAI(
        model=cfg['config'].get("model"),
        api_key=api_key,
        base_url=base_url,
        temperature=cfg['config'].get('temperature', 0.7),
        streaming=True,
        timeout=cfg['config'].get('timeout', 1800),
        extra_body={
            "thinking": {
                "type": cfg['config'].get('thinking', 'disabled')
            }
        },
        default_headers=default_headers(ctx) if ctx else {}
    )
    
    # 工具列表（按优先级排序）
    tools = [
        # V3 增强工具（推荐）
        generate_long_video_v3,  # 自动拼接 + 1080p
        optimize_scene_description,  # 场景描述优化
        
        # V2 工具（保留兼容）
        generate_long_video_with_progress,
        
        # 基础工具
        generate_single_video,
        generate_long_video,
        
        # 视频处理工具
        merge_videos,
        get_video_info,
        
        # 链接管理工具
        get_video_url,
        get_video_url_v3,
        list_recent_videos
    ]
    
    # 创建 Agent
    agent = create_agent(
        model=llm,
        system_prompt=cfg.get("sp"),
        tools=tools,
        checkpointer=get_memory_saver(),
        state_schema=AgentState,
    )
    
    return agent

"""
Long Video Generation Tool
基于 Seedance 的长视频生成工具，支持基于场景序列的长视频生成，保持视觉连贯性
模型名称从配置文件 config/agent_llm_config.json 中的 video_model.model 字段读取
"""

import json
import logging
import os
from typing import Optional, List
from langchain.tools import tool, ToolRuntime
from coze_coding_dev_sdk.video import (
    VideoGenerationClient,
    TextContent,
    ImageURLContent,
    ImageURL
)
from coze_coding_utils.runtime_ctx.context import new_context

logger = logging.getLogger(__name__)


def _get_video_model() -> str:
    """从配置文件读取视频生成模型名称"""
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
    config_path = os.path.join(workspace_path, "config/agent_llm_config.json")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            video_model = config.get("video_model", {})
            return video_model.get("model", "doubao-seedance-1-5-pro-251215")
    except Exception as e:
        logger.warning(f"读取配置文件失败，使用默认模型: {e}")
        return "doubao-seedance-1-5-pro-251215"


@tool
def generate_long_video(
    scenes: List[str],
    initial_image_url: Optional[str] = None,
    resolution: str = "720p",
    ratio: str = "16:9",
    duration: int = 5,
    watermark: bool = False,
    runtime: ToolRuntime = None
) -> str:
    """
    生成连贯的长视频，支持多个场景序列。
    
    使用方法：
    1. 传入场景描述列表（scenes），每个元素是一个场景的详细描述
    2. 可选：传入初始首帧图片URL（initial_image_url）
    3. 工具会依次生成每个场景，并使用前一个视频的最后一帧作为下一个视频的第一帧
    4. 返回所有视频片段的URL列表和元数据
    
    Args:
        scenes: 场景描述列表，每个元素是一个场景的详细文本描述
        initial_image_url: 初始首帧图片URL（可选）
        resolution: 视频分辨率（480p, 720p, 1080p），默认720p
        ratio: 视频宽高比（16:9, 9:16, 1:1, 4:3, 3:4, 21:9, adaptive），默认16:9
        duration: 每个片段的时长（4-12秒），默认5秒
        watermark: 是否添加水印，默认False
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        JSON字符串，包含：
        - video_urls: 生成的视频片段URL列表
        - total_duration: 总时长（秒）
        - scene_count: 场景数量
        - status: 生成状态
        - error: 错误信息（如果失败）
    """
    try:
        # 参数验证
        if not scenes or len(scenes) == 0:
            return json.dumps({
                "error": "场景描述不能为空",
                "status": "failed"
            }, ensure_ascii=False)
        
        if duration < 4 or duration > 12:
            return json.dumps({
                "error": "视频时长必须在4-12秒之间",
                "status": "failed"
            }, ensure_ascii=False)
        
        logger.info(f"开始生成长视频，共{len(scenes)}个场景")
        
        # 获取上下文
        ctx = runtime.context if runtime else new_context(method="video.generate_long")
        
        # 初始化视频生成客户端
        client = VideoGenerationClient(ctx=ctx)
        
        # 存储生成的视频URL
        video_urls = []
        last_frame_url = initial_image_url
        
        # 逐场景生成视频
        for i, scene in enumerate(scenes):
            logger.info(f"正在生成第{i+1}/{len(scenes)}个场景: {scene[:50]}...")
            
            # 构建内容项
            content_items = [TextContent(text=scene)]
            
            # 如果有上一帧，添加为首帧
            if last_frame_url:
                content_items.append(
                    ImageURLContent(
                        image_url=ImageURL(url=last_frame_url),
                        role="first_frame"
                    )
                )
            
            # 生成视频（最后一个场景不需要返回最后一帧）
            is_last_scene = (i == len(scenes) - 1)
            return_last_frame = not is_last_scene
            
            video_model = _get_video_model()
            # 增加单个视频生成的超时时间到 1200 秒（20分钟）
            video_url, response, current_last_frame = client.video_generation(
                content_items=content_items,
                model=video_model,
                resolution=resolution,
                ratio=ratio,
                duration=duration,
                watermark=watermark,
                return_last_frame=return_last_frame,
                max_wait_time=1200  # 单个视频最长等待 20 分钟
            )
            
            # 检查生成结果
            if not video_url:
                error_msg = f"第{i+1}个场景生成失败"
                logger.error(error_msg)
                return json.dumps({
                    "error": error_msg,
                    "status": "failed",
                    "completed_scenes": video_urls,
                    "failed_at_scene": i + 1
                }, ensure_ascii=False)
            
            # 保存视频URL
            video_urls.append(video_url)
            
            # 更新最后一帧URL，用于下一个场景
            if not is_last_scene:
                last_frame_url = current_last_frame
            
            logger.info(f"第{i+1}个场景生成成功")
        
        # 计算总时长
        total_duration = len(scenes) * duration
        
        result = {
            "video_urls": video_urls,
            "total_duration": total_duration,
            "scene_count": len(scenes),
            "status": "success",
            "resolution": resolution,
            "ratio": ratio,
            "duration_per_scene": duration
        }
        
        logger.info(f"长视频生成完成，共{len(video_urls)}个片段，总时长{total_duration}秒")
        
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"长视频生成失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "status": "failed"
        }, ensure_ascii=False)


@tool
def generate_single_video(
    prompt: str,
    image_url: Optional[str] = None,
    resolution: str = "720p",
    ratio: str = "16:9",
    duration: int = 5,
    watermark: bool = False,
    runtime: ToolRuntime = None
) -> str:
    """
    生成单个视频片段。
    
    Args:
        prompt: 视频内容的文本描述
        image_url: 首帧图片URL（可选）
        resolution: 视频分辨率（480p, 720p, 1080p），默认720p
        ratio: 视频宽高比（16:9, 9:16, 1:1, 4:3, 3:4, 21:9, adaptive），默认16:9
        duration: 视频时长（4-12秒），默认5秒
        watermark: 是否添加水印，默认False
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        JSON字符串，包含视频URL和元数据
    """
    try:
        if not prompt:
            return json.dumps({
                "error": "视频描述不能为空",
                "status": "failed"
            }, ensure_ascii=False)
        
        if duration < 4 or duration > 12:
            return json.dumps({
                "error": "视频时长必须在4-12秒之间",
                "status": "failed"
            }, ensure_ascii=False)
        
        logger.info(f"开始生成视频: {prompt[:50]}...")
        
        # 获取上下文
        ctx = runtime.context if runtime else new_context(method="video.generate")
        
        # 初始化视频生成客户端
        client = VideoGenerationClient(ctx=ctx)
        
        # 构建内容项
        content_items = [TextContent(text=prompt)]
        
        if image_url:
            content_items.append(
                ImageURLContent(
                    image_url=ImageURL(url=image_url),
                    role="first_frame"
                )
            )
        
        # 生成视频
        video_model = _get_video_model()
        # 增加单个视频生成的超时时间到 1200 秒（20分钟）
        video_url, response, _ = client.video_generation(
            content_items=content_items,
            model=video_model,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            watermark=watermark,
            max_wait_time=1200  # 单个视频最长等待 20 分钟
        )
        
        if not video_url:
            return json.dumps({
                "error": "视频生成失败",
                "status": "failed"
            }, ensure_ascii=False)
        
        result = {
            "video_url": video_url,
            "duration": duration,
            "resolution": resolution,
            "ratio": ratio,
            "status": "success"
        }
        
        logger.info("视频生成成功")
        
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"视频生成失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "status": "failed"
        }, ensure_ascii=False)

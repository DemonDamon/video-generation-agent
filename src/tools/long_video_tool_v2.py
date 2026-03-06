"""
Long Video Generation Tool with Real-time Progress Feedback
支持实时进度反馈的长视频生成工具
"""

import json
import logging
import os
import time
from typing import Optional, List, Dict
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
def generate_long_video_with_progress(
    scenes: List[str],
    initial_image_url: Optional[str] = None,
    resolution: str = "720p",
    ratio: str = "16:9",
    duration: int = 5,
    watermark: bool = False,
    runtime: ToolRuntime = None
) -> str:
    """
    生成连贯的长视频，支持多个场景序列，并提供详细的实时进度信息。
    
    🎬 功能特点：
    - 逐场景顺序生成，保持视觉连贯性
    - 实时进度反馈，包含每个场景的执行状态
    - 预估生成时间，让用户了解等待时长
    - 详细的执行日志，便于追踪问题
    
    Args:
        scenes: 场景描述列表（建议3-5个场景）
        initial_image_url: 初始首帧图片URL（可选）
        resolution: 视频分辨率（480p, 720p, 1080p）
        ratio: 视频宽高比（16:9, 9:16, 1:1等）
        duration: 每个片段时长（4-12秒）
        watermark: 是否添加水印
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        包含详细进度信息的JSON字符串：
        - progress: 总体进度百分比
        - current_scene: 当前正在处理的场景
        - completed_scenes: 已完成的场景列表
        - estimated_remaining_time: 预估剩余时间（秒）
        - execution_details: 详细的执行过程
        - video_urls: 最终生成的视频URL列表
    """
    try:
        start_time = time.time()
        
        # 参数验证
        if not scenes or len(scenes) == 0:
            return json.dumps({
                "error": "场景描述不能为空",
                "status": "failed",
                "progress": 0
            }, ensure_ascii=False)
        
        if duration < 4 or duration > 12:
            return json.dumps({
                "error": "视频时长必须在4-12秒之间",
                "status": "failed",
                "progress": 0
            }, ensure_ascii=False)
        
        # 预估每个场景生成时间（基于经验值）
        estimated_time_per_scene = 30  # 秒
        
        logger.info(f"""
╔════════════════════════════════════════════════════════╗
║  长视频生成任务开始                                      ║
╠════════════════════════════════════════════════════════╣
║  场景数量: {len(scenes)} 个
║  每个场景时长: {duration} 秒
║  视频分辨率: {resolution}
║  宽高比: {ratio}
║  预估总耗时: {len(scenes) * estimated_time_per_scene} 秒
╚════════════════════════════════════════════════════════╝
        """)
        
        # 获取上下文
        ctx = runtime.context if runtime else new_context(method="video.generate_long")
        
        # 初始化视频生成客户端
        client = VideoGenerationClient(ctx=ctx)
        
        # 存储结果
        video_urls = []
        scene_details = []
        last_frame_url = initial_image_url
        
        # 逐场景生成视频
        for i, scene in enumerate(scenes):
            scene_start_time = time.time()
            progress = int((i / len(scenes)) * 100)
            
            logger.info(f"""
┌──────────────────────────────────────────────────────┐
│  场景 {i+1}/{len(scenes)} - 进度: {progress}%
├──────────────────────────────────────────────────────┤
│  描述: {scene[:60]}...
│  状态: 正在生成中...
│  预估剩余: {int((len(scenes) - i) * estimated_time_per_scene)} 秒
└──────────────────────────────────────────────────────┘
            """)
            
            # 构建内容项
            content_items = [TextContent(text=scene)]
            
            if last_frame_url:
                content_items.append(
                    ImageURLContent(
                        image_url=ImageURL(url=last_frame_url),
                        role="first_frame"
                    )
                )
                logger.info(f"  → 使用上一场景的最后一帧作为首帧")
            
            # 生成视频
            is_last_scene = (i == len(scenes) - 1)
            return_last_frame = not is_last_scene
            
            try:
                video_model = _get_video_model()
                video_url, response, current_last_frame = client.video_generation(
                    content_items=content_items,
                    model=video_model,
                    resolution=resolution,
                    ratio=ratio,
                    duration=duration,
                    watermark=watermark,
                    return_last_frame=return_last_frame
                )
                
                scene_end_time = time.time()
                scene_duration = int(scene_end_time - scene_start_time)
                
                if not video_url:
                    error_msg = f"场景 {i+1} 生成失败"
                    logger.error(f"  ✗ {error_msg}")
                    
                    # 返回部分结果
                    return json.dumps({
                        "error": error_msg,
                        "status": "partial_failure",
                        "progress": progress,
                        "completed_scenes": scene_details,
                        "video_urls": video_urls,
                        "failed_at_scene": i + 1,
                        "execution_time": int(time.time() - start_time)
                    }, ensure_ascii=False)
                
                # 成功生成
                logger.info(f"""
  ✓ 场景 {i+1} 生成成功！
    - 耗时: {scene_duration} 秒
    - 视频URL: {video_url[:80]}...
                """)
                
                # 保存结果
                video_urls.append(video_url)
                scene_details.append({
                    "scene_index": i + 1,
                    "scene_description": scene,
                    "video_url": video_url,
                    "generation_time": scene_duration,
                    "status": "success"
                })
                
                # 更新最后一帧
                if not is_last_scene:
                    last_frame_url = current_last_frame
                    logger.info(f"  → 已获取最后一帧，用于下一个场景")
                
            except Exception as e:
                logger.error(f"  ✗ 场景 {i+1} 生成异常: {str(e)}")
                return json.dumps({
                    "error": f"场景 {i+1} 生成异常: {str(e)}",
                    "status": "failed",
                    "progress": progress,
                    "completed_scenes": scene_details,
                    "video_urls": video_urls,
                    "failed_at_scene": i + 1,
                    "execution_time": int(time.time() - start_time)
                }, ensure_ascii=False)
        
        # 全部完成
        total_time = int(time.time() - start_time)
        total_duration = len(scenes) * duration
        
        logger.info(f"""
╔════════════════════════════════════════════════════════╗
║  ✓ 长视频生成完成！                                      ║
╠════════════════════════════════════════════════════════╣
║  总场景数: {len(scenes)} 个
║  总视频时长: {total_duration} 秒
║  实际耗时: {total_time} 秒
║  视频片段: {len(video_urls)} 个
╚════════════════════════════════════════════════════════╝
        """)
        
        result = {
            "status": "success",
            "progress": 100,
            "video_urls": video_urls,
            "total_duration": total_duration,
            "scene_count": len(scenes),
            "execution_time": total_time,
            "scene_details": scene_details,
            "resolution": resolution,
            "ratio": ratio,
            "duration_per_scene": duration,
            "average_time_per_scene": int(total_time / len(scenes))
        }
        
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"长视频生成失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "status": "failed",
            "progress": 0,
            "execution_time": int(time.time() - start_time) if 'start_time' in locals() else 0
        }, ensure_ascii=False)


@tool
def report_generation_progress(
    task_id: str,
    current_step: str,
    progress: int,
    message: str,
    details: Optional[Dict] = None,
    runtime: ToolRuntime = None
) -> str:
    """
    报告视频生成任务的实时进度（辅助工具）。
    
    Args:
        task_id: 任务ID
        current_step: 当前步骤描述
        progress: 进度百分比（0-100）
        message: 进度消息
        details: 详细信息（可选）
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        进度报告JSON
    """
    progress_report = {
        "task_id": task_id,
        "timestamp": time.time(),
        "current_step": current_step,
        "progress": progress,
        "message": message,
        "details": details or {}
    }
    
    logger.info(f"[Progress {progress}%] {current_step}: {message}")
    
    return json.dumps(progress_report, ensure_ascii=False)

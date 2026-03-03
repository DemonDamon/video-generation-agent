"""
视频链接获取工具
用于重新生成视频的有效访问链接
"""

import os
import logging
import re
from typing import Optional
from langchain.tools import tool, ToolRuntime
from coze_coding_dev_sdk.s3 import S3SyncStorage

logger = logging.getLogger(__name__)


@tool
def get_video_url(
    task_id: str,
    expire_time: int = 86400,
    runtime: ToolRuntime = None
) -> str:
    """
    根据视频任务ID重新生成有效的视频访问链接。
    
    Args:
        task_id: 视频生成任务ID（例如：cgt-20260303150629-qz8sl）
        expire_time: 链接有效期（秒），默认86400（1天）
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        JSON字符串，包含：
        - video_url: 有效的视频访问链接
        - task_id: 任务ID
        - expire_time: 有效期（秒）
        - status: 状态
        - error: 错误信息（如果失败）
    """
    try:
        import json
        
        logger.info(f"正在获取视频链接，任务ID: {task_id}")
        
        # 初始化对象存储客户端
        storage = S3SyncStorage(
            endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
            access_key="",
            secret_key="",
            bucket_name=os.getenv("COZE_BUCKET_NAME"),
            region="cn-beijing",
        )
        
        # 视频文件的可能key格式
        # 根据视频生成SDK的逻辑，key格式可能是：
        # video/video_generate_{task_id}.mp4
        possible_keys = [
            f"video/video_generate_{task_id}.mp4",
            f"video_generate_{task_id}.mp4",
        ]
        
        # 尝试查找视频文件
        video_key = None
        
        # 先尝试列出video/前缀下的文件
        try:
            result = storage.list_files(prefix="video/", max_keys=100)
            if result.get("keys"):
                # 在列表中查找匹配的文件
                for key in result["keys"]:
                    if task_id in key and key.endswith(".mp4"):
                        video_key = key
                        logger.info(f"找到视频文件: {video_key}")
                        break
        except Exception as e:
            logger.warning(f"列出视频文件失败: {e}")
        
        # 如果没找到，尝试直接使用预定义的key
        if not video_key:
            for key in possible_keys:
                try:
                    if storage.file_exists(file_key=key):
                        video_key = key
                        logger.info(f"找到视频文件: {video_key}")
                        break
                except Exception:
                    continue
        
        if not video_key:
            return json.dumps({
                "error": f"未找到任务ID为 {task_id} 的视频文件",
                "status": "not_found",
                "task_id": task_id
            }, ensure_ascii=False)
        
        # 生成新的签名URL
        video_url = storage.generate_presigned_url(
            key=video_key,
            expire_time=expire_time
        )
        
        logger.info(f"成功生成视频链接: {video_url[:80]}...")
        
        return json.dumps({
            "video_url": video_url,
            "video_key": video_key,
            "task_id": task_id,
            "expire_time": expire_time,
            "status": "success"
        }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"获取视频链接失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        import json
        return json.dumps({
            "error": error_msg,
            "status": "failed",
            "task_id": task_id
        }, ensure_ascii=False)


@tool
def list_recent_videos(
    prefix: str = "video/",
    max_keys: int = 20,
    runtime: ToolRuntime = None
) -> str:
    """
    列出最近生成的视频文件。
    
    Args:
        prefix: 文件前缀，默认"video/"
        max_keys: 最大返回数量，默认20
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        JSON字符串，包含视频文件列表
    """
    try:
        import json
        
        logger.info(f"正在列出视频文件，前缀: {prefix}")
        
        # 初始化对象存储客户端
        storage = S3SyncStorage(
            endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
            access_key="",
            secret_key="",
            bucket_name=os.getenv("COZE_BUCKET_NAME"),
            region="cn-beijing",
        )
        
        # 列出文件
        result = storage.list_files(prefix=prefix, max_keys=max_keys)
        
        videos = []
        for key in result.get("keys", []):
            if key.endswith(".mp4"):
                # 从key中提取任务ID
                # 格式：video/video_generate_cgt-20260303150629-qz8sl.mp4
                match = re.search(r'(cgt-\d+-\w+)\.mp4', key)
                task_id = match.group(1) if match else "unknown"
                
                videos.append({
                    "key": key,
                    "task_id": task_id,
                })
        
        return json.dumps({
            "videos": videos,
            "total": len(videos),
            "status": "success"
        }, ensure_ascii=False)
        
    except Exception as e:
        import json
        error_msg = f"列出视频文件失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "status": "failed"
        }, ensure_ascii=False)

"""
Long Video Generation Tool V3 - Enhanced with Auto-Merge
增强版长视频生成工具：自动拼接 + 1080p + 优化模板
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import requests
from typing import Optional, List, Dict
from langchain.tools import tool, ToolRuntime
from coze_coding_dev_sdk.video import (
    VideoGenerationClient,
    TextContent,
    ImageURLContent,
    ImageURL
)
from coze_coding_dev_sdk.s3 import S3SyncStorage
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
            model = video_model.get("model", "doubao-seedance-2-0-260128")
            logger.info(f"使用视频生成模型: {model}")
            return model
    except Exception as e:
        logger.warning(f"读取配置文件失败，使用默认模型: {e}")
        return "doubao-seedance-2-0-260128"


def _get_video_output_dir() -> str:
    """获取视频输出目录，在 FaaS 环境中使用 /tmp"""
    # 优先使用环境变量
    env_dir = os.getenv("LOCAL_VIDEO_OUTPUT_DIR")
    if env_dir:
        return env_dir
    
    # 检测是否在 FaaS 环境（/opt/bytefaas 存在且只读）
    if os.path.exists("/opt/bytefaas"):
        return "/tmp/output/videos"
    
    return "output/videos"


# 场景描述优化模板
SCENE_DESCRIPTION_TEMPLATE = """
[场景 {index}/{total}]
镜头类型: {shot_type}
主体动作: {subject_action}
环境描述: {environment}
光影效果: {lighting}
运镜方式: {camera_movement}
时间氛围: {time_atmosphere}

优化描述: {optimized_description}
"""

# 镜头类型参考
SHOT_TYPES = {
    "远景": "展示整体环境和大场景，适合开场和过渡",
    "全景": "展示人物全身和周围环境，适合介绍场景",
    "中景": "展示人物上半身，适合表现人物互动",
    "近景": "展示人物面部或物体细节，适合表现情感",
    "特写": "极度聚焦细节，适合强调重点",
    "跟拍": "跟随主体移动，适合表现动态过程",
    "航拍": "空中俯视视角，适合展示壮阔场景"
}

# 运镜方式参考
CAMERA_MOVEMENTS = {
    "固定": "相机保持静止，画面稳定",
    "推镜头": "相机向前移动，聚焦主体",
    "拉镜头": "相机向后移动，展示环境",
    "横摇": "相机水平转动，展示全景",
    "俯仰": "相机垂直转动，改变视角",
    "跟镜头": "跟随主体移动，保持距离",
    "环绕": "围绕主体旋转，立体展示"
}


@tool
def generate_long_video_v3(
    scenes: List[str],
    initial_image_url: Optional[str] = None,
    resolution: str = "1080p",
    ratio: str = "16:9",
    duration: int = 5,
    watermark: bool = False,
    auto_merge: bool = True,
    merge_output_name: str = "long_video.mp4",
    runtime: ToolRuntime = None
) -> str:
    """
    生成连贯的长视频（增强版），支持自动拼接和高清画质。
    
    🎬 增强功能：
    - 默认1080p高清画质
    - 自动拼接所有场景为完整视频
    - 优化的场景描述生成
    - 详细的进度和性能反馈
    - 单个视频URL返回（自动合并后）
    
    Args:
        scenes: 场景描述列表（建议3-5个场景）
        initial_image_url: 初始首帧图片URL（可选）
        resolution: 视频分辨率（默认1080p，可选480p, 720p）
        ratio: 视频宽高比（16:9, 9:16, 1:1等）
        duration: 每个片段时长（4-12秒，默认5秒）
        watermark: 是否添加水印
        auto_merge: 是否自动拼接（默认True）
        merge_output_name: 拼接后的文件名
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        包含详细信息的JSON字符串：
        - video_url: 最终视频URL（如启用拼接）或片段列表
        - merged: 是否已拼接
        - total_duration: 总时长
        - scene_count: 场景数量
        - execution_time: 执行时间
        - scene_details: 各场景详情
    """
    start_time = time.time()
    
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
        
        logger.info(f"""
╔══════════════════════════════════════════════════════════════╗
║  🎬 增强版长视频生成任务 V3                                      ║
╠══════════════════════════════════════════════════════════════╣
║  场景数量: {len(scenes)} 个
║  每个场景时长: {duration} 秒
║  视频分辨率: {resolution}（高清）
║  宽高比: {ratio}
║  自动拼接: {'是' if auto_merge else '否'}
║  预估总时长: ~{len(scenes) * 180} 秒（含拼接）
╚══════════════════════════════════════════════════════════════╝
        """)
        
        # 获取上下文
        ctx = runtime.context if runtime else new_context(method="video.generate_long_v3")
        
        # 初始化视频生成客户端
        client = VideoGenerationClient(ctx=ctx)
        
        # 存储结果
        video_urls = []
        scene_details = []
        last_frame_url = initial_image_url
        
        # ===== 第一阶段：生成所有场景 =====
        logger.info("\n【阶段 1/2】生成视频片段...")
        
        for i, scene in enumerate(scenes):
            scene_start_time = time.time()
            progress = int((i / len(scenes)) * 80)  # 前80%用于生成
            
            logger.info(f"""
┌──────────────────────────────────────────────────────────────┐
│  📍 场景 {i+1}/{len(scenes)} - 进度: {progress}%
├──────────────────────────────────────────────────────────────┤
│  原始描述: {scene[:50]}...
│  状态: 正在生成中...
└──────────────────────────────────────────────────────────────┘
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
                logger.info(f"  🔗 使用上一场景的最后一帧作为首帧")
            
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
                    logger.error(f"  ❌ {error_msg}")
                    
                    # 返回部分结果（如有已生成的片段）
                    if video_urls:
                        logger.info(f"  ⚠️ 已有 {len(video_urls)} 个片段生成成功")
                    
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
                logger.info(f"  ✅ 场景 {i+1} 生成成功！耗时: {scene_duration}秒")
                
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
                if not is_last_scene and current_last_frame:
                    last_frame_url = current_last_frame
                    logger.info(f"  🔗 已获取最后一帧")
                
            except Exception as e:
                logger.error(f"  ❌ 场景 {i+1} 生成异常: {str(e)}")
                return json.dumps({
                    "error": f"场景 {i+1} 生成异常: {str(e)}",
                    "status": "failed",
                    "progress": progress,
                    "completed_scenes": scene_details,
                    "video_urls": video_urls,
                    "failed_at_scene": i + 1,
                    "execution_time": int(time.time() - start_time)
                }, ensure_ascii=False)
        
        # ===== 第二阶段：自动拼接 =====
        merged_video_url = None
        merge_info = None
        
        if auto_merge and len(video_urls) > 0:
            logger.info(f"\n【阶段 2/2】自动拼接 {len(video_urls)} 个视频片段...")
            
            merge_result = _merge_video_segments(
                video_urls=video_urls,
                output_name=merge_output_name
            )
            
            if merge_result.get("status") == "success":
                merged_video_url = merge_result.get("video_url")
                merge_info = {
                    "duration": merge_result.get("duration"),
                    "processing_time": merge_result.get("processing_time")
                }
                logger.info(f"  ✅ 视频拼接完成！总时长: {merge_result.get('duration')}秒")
            else:
                logger.warning(f"  ⚠️ 视频拼接失败: {merge_result.get('error')}")
                # 拼接失败不影响整体，返回片段列表
        
        # 计算总耗时
        total_time = int(time.time() - start_time)
        total_duration = len(video_urls) * duration
        
        logger.info(f"""
╔══════════════════════════════════════════════════════════════╗
║  ✅ 长视频生成完成！                                            ║
╠══════════════════════════════════════════════════════════════╣
║  总场景数: {len(scenes)} 个
║  总视频时长: {total_duration} 秒
║  实际耗时: {total_time} 秒
║  视频片段: {len(video_urls)} 个
║  自动拼接: {'✅ 已完成' if merged_video_url else '⚠️ 未执行/失败'}
║  最终画质: {resolution}
╚══════════════════════════════════════════════════════════════╝
        """)
        
        # 构建返回结果
        result = {
            "status": "success",
            "progress": 100,
            # 如果拼接成功，返回单个URL；否则返回片段列表
            "video_url": merged_video_url if merged_video_url else None,
            "video_urls": video_urls if not merged_video_url else None,
            "merged": merged_video_url is not None,
            "merge_info": merge_info,
            "total_duration": total_duration,
            "scene_count": len(scenes),
            "execution_time": total_time,
            "scene_details": scene_details,
            "resolution": resolution,
            "ratio": ratio,
            "duration_per_scene": duration,
            "average_time_per_scene": int(total_time / len(scenes)) if scenes else 0
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


def _merge_video_segments(
    video_urls: List[str],
    output_name: str = "merged_video.mp4"
) -> Dict:
    """
    内部方法：合并多个视频片段
    
    Args:
        video_urls: 视频URL列表
        output_name: 输出文件名
    
    Returns:
        包含合并结果的字典
    """
    try:
        merge_start_time = time.time()
        
        if not video_urls:
            return {"error": "视频URL列表为空", "status": "failed"}
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        video_files = []
        
        # 下载所有视频片段
        for i, url in enumerate(video_urls):
            logger.info(f"  📥 下载片段 {i+1}/{len(video_urls)}...")
            
            try:
                response = requests.get(url, timeout=120)
                response.raise_for_status()
                
                file_path = os.path.join(temp_dir, f"segment_{i:03d}.mp4")
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                
                video_files.append(file_path)
                logger.info(f"    ✅ 片段 {i+1} 下载完成")
                
            except Exception as e:
                logger.error(f"    ❌ 片段 {i+1} 下载失败: {e}")
                # 清理
                for f in video_files:
                    try:
                        os.remove(f)
                    except:
                        pass
                try:
                    os.rmdir(temp_dir)
                except:
                    pass
                
                return {"error": f"视频片段 {i+1} 下载失败: {str(e)}", "status": "failed"}
        
        # 创建文件列表
        list_file = os.path.join(temp_dir, "filelist.txt")
        with open(list_file, 'w') as f:
            for video_file in video_files:
                f.write(f"file '{video_file}'\n")
        
        # 输出文件
        output_file = os.path.join(temp_dir, output_name)
        
        # 使用 ffmpeg 合并视频
        logger.info("  🔧 使用 ffmpeg 合并视频...")
        
        try:
            # 使用 concat demuxer 方法（无损拼接）
            cmd = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', list_file,
                '-c', 'copy',  # 无重编码，速度快
                '-y',  # 覆盖输出文件
                output_file
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            if result.returncode != 0:
                logger.error(f"    ❌ ffmpeg 错误: {result.stderr}")
                raise Exception(f"ffmpeg 执行失败: {result.stderr}")
            
            logger.info("    ✅ 视频合并完成")
            
        except subprocess.TimeoutExpired:
            return {"error": "视频合并超时（超过5分钟）", "status": "failed"}
        except Exception as e:
            logger.error(f"    ❌ ffmpeg 执行异常: {e}")
            return {"error": f"视频合并失败: {str(e)}", "status": "failed"}
        
        # 获取视频时长
        try:
            duration_cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                output_file
            ]
            duration_result = subprocess.run(duration_cmd, capture_output=True, text=True)
            total_duration = float(duration_result.stdout.strip())
        except:
            total_duration = 0
        
        video_url = None
        video_key = None
        
        # 优先使用对象存储；未配置时保存到本地文件
        bucket_url = os.getenv("COZE_BUCKET_ENDPOINT_URL")
        bucket_name = os.getenv("COZE_BUCKET_NAME")
        
        if bucket_url and bucket_name:
            # 上传到对象存储
            logger.info("  📤 上传合并后的视频...")
            try:
                storage = S3SyncStorage(
                    endpoint_url=bucket_url,
                    access_key="",
                    secret_key="",
                    bucket_name=bucket_name,
                    region="cn-beijing",
                )
                with open(output_file, 'rb') as f:
                    video_content = f.read()
                video_key = storage.upload_file(
                    file_content=video_content,
                    file_name=f"long_videos/{output_name}",
                    content_type="video/mp4"
                )
                video_url = storage.generate_presigned_url(
                    key=video_key,
                    expire_time=604800
                )
                logger.info(f"    ✅ 视频上传完成")
            except Exception as e:
                logger.error(f"    ❌ 上传失败: {e}")
                return {"error": f"视频上传失败: {str(e)}", "status": "failed"}
        else:
            # 保存到本地目录（无需对象存储）
            output_dir = _get_video_output_dir()
            output_dir = os.path.abspath(output_dir)
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as e:
                # 如果无法创建目录，尝试使用 /tmp
                logger.warning(f"无法创建输出目录 {output_dir}: {e}，使用 /tmp")
                output_dir = "/tmp/output/videos"
                os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.splitext(output_name)[0]
            ext = os.path.splitext(output_name)[1] or ".mp4"
            unique_name = f"{base_name}_{int(time.time())}{ext}"
            dest_path = os.path.join(output_dir, unique_name)
            shutil.copy2(output_file, dest_path)
            logger.info(f"    ✅ 视频已保存到本地: {dest_path}")
            base_url = os.getenv("LOCAL_VIDEO_BASE_URL", "")
            if base_url:
                video_url = f"{base_url.rstrip('/')}/videos/{unique_name}"
            else:
                video_url = f"file:///{dest_path.replace(os.sep, '/')}"
            video_key = dest_path
        
        # 清理临时文件
        try:
            for f in video_files:
                os.remove(f)
            os.remove(list_file)
            os.remove(output_file)
            os.rmdir(temp_dir)
        except:
            pass
        
        # 计算耗时
        merge_time = int(time.time() - merge_start_time)
        
        return {
            "video_url": video_url,
            "video_key": video_key,
            "duration": round(total_duration, 2),
            "segment_count": len(video_urls),
            "processing_time": merge_time,
            "status": "success"
        }
        
    except Exception as e:
        error_msg = f"视频合并失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg, "status": "failed"}


@tool
def optimize_scene_description(
    original_scene: str,
    shot_type: str = "中景",
    camera_movement: str = "推镜头",
    runtime: ToolRuntime = None
) -> str:
    """
    优化场景描述，添加专业的镜头语言。
    
    Args:
        original_scene: 原始场景描述
        shot_type: 镜头类型（远景/全景/中景/近景/特写/跟拍/航拍）
        camera_movement: 运镜方式（固定/推镜头/拉镜头/横摇/俯仰/跟镜头/环绕）
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        优化后的场景描述
    """
    try:
        # 获取镜头和运镜说明
        shot_desc = SHOT_TYPES.get(shot_type, "标准视角")
        movement_desc = CAMERA_MOVEMENTS.get(camera_movement, "稳定画面")
        
        # 构建优化描述
        optimized = f"{shot_type}，{original_scene}。{movement_desc}。"
        
        result = {
            "original": original_scene,
            "optimized": optimized,
            "shot_type": shot_type,
            "shot_description": shot_desc,
            "camera_movement": camera_movement,
            "movement_description": movement_desc
        }
        
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            "error": f"场景优化失败: {str(e)}",
            "original": original_scene
        }, ensure_ascii=False)


@tool
def get_video_url(
    task_id: str = None,
    video_key: str = None,
    runtime: ToolRuntime = None
) -> str:
    """
    根据任务ID或视频Key重新生成有效的视频访问链接。
    
    解决视频链接签名过期问题，生成新的有效链接（7天有效期）。
    
    Args:
        task_id: 视频生成任务ID（可选）
        video_key: 视频在对象存储中的Key（可选）
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        JSON字符串，包含新的视频访问URL
    """
    try:
        if not video_key:
            return json.dumps({
                "error": "需要提供 video_key 参数",
                "status": "failed"
            }, ensure_ascii=False)
        
        logger.info(f"重新生成视频链接: {video_key}")
        
        # 初始化存储
        storage = S3SyncStorage(
            endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
            access_key="",
            secret_key="",
            bucket_name=os.getenv("COZE_BUCKET_NAME"),
            region="cn-beijing",
        )
        
        # 生成新的签名URL
        video_url = storage.generate_presigned_url(
            key=video_key,
            expire_time=604800  # 7天
        )
        
        logger.info(f"✅ 新链接生成成功")
        
        return json.dumps({
            "video_url": video_url,
            "video_key": video_key,
            "expire_seconds": 604800,
            "status": "success"
        }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"获取视频链接失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "status": "failed"
        }, ensure_ascii=False)

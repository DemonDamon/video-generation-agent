"""
视频拼接工具
使用 ffmpeg 自动合并多个视频片段
"""

import os
import json
import logging
import tempfile
import subprocess
import requests
from typing import List, Optional
from langchain.tools import tool, ToolRuntime
from coze_coding_dev_sdk.s3 import S3SyncStorage

logger = logging.getLogger(__name__)


@tool
def merge_videos(
    video_urls: List[str],
    output_name: str = "merged_video.mp4",
    add_transitions: bool = False,
    runtime: ToolRuntime = None
) -> str:
    """
    合并多个视频片段为一个完整视频。
    
    🎬 功能特点：
    - 自动下载所有视频片段
    - 使用 ffmpeg 高质量拼接
    - 可选添加过渡效果
    - 自动上传到对象存储
    - 返回完整的视频链接
    
    Args:
        video_urls: 视频片段URL列表
        output_name: 输出文件名（默认：merged_video.mp4）
        add_transitions: 是否添加过渡效果（默认：False）
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        JSON字符串，包含：
        - video_url: 合并后的视频链接
        - duration: 总时长（秒）
        - segment_count: 片段数量
        - status: 状态
        - error: 错误信息（如果失败）
    """
    try:
        import time
        
        start_time = time.time()
        
        if not video_urls or len(video_urls) == 0:
            return json.dumps({
                "error": "视频URL列表不能为空",
                "status": "failed"
            }, ensure_ascii=False)
        
        logger.info(f"开始合并 {len(video_urls)} 个视频片段")
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        video_files = []
        
        # 下载所有视频片段
        for i, url in enumerate(video_urls):
            logger.info(f"下载视频片段 {i+1}/{len(video_urls)}...")
            
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                
                file_path = os.path.join(temp_dir, f"segment_{i:03d}.mp4")
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                
                video_files.append(file_path)
                logger.info(f"  ✓ 片段 {i+1} 下载完成")
                
            except Exception as e:
                logger.error(f"  ✗ 片段 {i+1} 下载失败: {e}")
                # 清理临时文件
                for f in video_files:
                    try:
                        os.remove(f)
                    except:
                        pass
                try:
                    os.rmdir(temp_dir)
                except:
                    pass
                
                return json.dumps({
                    "error": f"视频片段 {i+1} 下载失败: {str(e)}",
                    "status": "failed"
                }, ensure_ascii=False)
        
        # 创建文件列表
        list_file = os.path.join(temp_dir, "filelist.txt")
        with open(list_file, 'w') as f:
            for video_file in video_files:
                # 使用相对路径或绝对路径
                f.write(f"file '{video_file}'\n")
        
        # 输出文件
        output_file = os.path.join(temp_dir, output_name)
        
        # 使用 ffmpeg 合并视频
        logger.info("正在使用 ffmpeg 合并视频...")
        
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
                logger.error(f"ffmpeg 错误: {result.stderr}")
                raise Exception(f"ffmpeg 执行失败: {result.stderr}")
            
            logger.info("  ✓ 视频合并完成")
            
        except subprocess.TimeoutExpired:
            return json.dumps({
                "error": "视频合并超时（超过5分钟）",
                "status": "failed"
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"ffmpeg 执行异常: {e}")
            return json.dumps({
                "error": f"视频合并失败: {str(e)}",
                "status": "failed"
            }, ensure_ascii=False)
        
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
        
        # 上传到对象存储
        logger.info("正在上传合并后的视频...")
        
        try:
            storage = S3SyncStorage(
                endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
                access_key="",
                secret_key="",
                bucket_name=os.getenv("COZE_BUCKET_NAME"),
                region="cn-beijing",
            )
            
            # 读取文件内容
            with open(output_file, 'rb') as f:
                video_content = f.read()
            
            # 上传
            video_key = storage.upload_file(
                file_content=video_content,
                file_name=f"merged/{output_name}",
                content_type="video/mp4"
            )
            
            # 生成签名URL（有效期7天）
            video_url = storage.generate_presigned_url(
                key=video_key,
                expire_time=604800  # 7天
            )
            
            logger.info(f"  ✓ 视频上传完成: {video_url[:80]}...")
            
        except Exception as e:
            logger.error(f"上传失败: {e}")
            return json.dumps({
                "error": f"视频上传失败: {str(e)}",
                "status": "failed"
            }, ensure_ascii=False)
        
        # 清理临时文件
        try:
            for f in video_files:
                os.remove(f)
            os.remove(list_file)
            os.remove(output_file)
            os.rmdir(temp_dir)
        except:
            pass
        
        # 计算总耗时
        total_time = int(time.time() - start_time)
        
        logger.info(f"视频合并完成，总时长: {total_duration}秒，耗时: {total_time}秒")
        
        return json.dumps({
            "video_url": video_url,
            "video_key": video_key,
            "duration": round(total_duration, 2),
            "segment_count": len(video_urls),
            "processing_time": total_time,
            "status": "success"
        }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"视频合并失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "status": "failed"
        }, ensure_ascii=False)


@tool
def get_video_info(
    video_url: str,
    runtime: ToolRuntime = None
) -> str:
    """
    获取视频的详细信息（时长、分辨率、帧率等）。
    
    Args:
        video_url: 视频URL
        runtime: 工具运行时上下文（自动注入）
    
    Returns:
        JSON字符串，包含视频的详细信息
    """
    try:
        import tempfile
        
        logger.info(f"获取视频信息: {video_url[:60]}...")
        
        # 下载视频到临时文件
        response = requests.get(video_url, timeout=60)
        response.raise_for_status()
        
        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, "temp_video.mp4")
        
        with open(temp_file, 'wb') as f:
            f.write(response.content)
        
        # 使用 ffprobe 获取信息
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            temp_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return json.dumps({
                "error": "无法获取视频信息",
                "status": "failed"
            }, ensure_ascii=False)
        
        # 解析结果
        import json as json_lib
        probe_data = json_lib.loads(result.stdout)
        
        # 提取关键信息
        video_stream = None
        audio_stream = None
        
        for stream in probe_data.get('streams', []):
            if stream.get('codec_type') == 'video':
                video_stream = stream
            elif stream.get('codec_type') == 'audio':
                audio_stream = stream
        
        info = {
            "duration": float(probe_data.get('format', {}).get('duration', 0)),
            "size": int(probe_data.get('format', {}).get('size', 0)),
            "bit_rate": int(probe_data.get('format', {}).get('bit_rate', 0)),
            "format": probe_data.get('format', {}).get('format_name', 'unknown'),
            "video": {
                "width": video_stream.get('width', 0) if video_stream else 0,
                "height": video_stream.get('height', 0) if video_stream else 0,
                "codec": video_stream.get('codec_name', 'unknown') if video_stream else 'unknown',
                "fps": eval(video_stream.get('r_frame_rate', '0/1')) if video_stream else 0,
                "duration": float(video_stream.get('duration', 0)) if video_stream else 0
            } if video_stream else None,
            "audio": {
                "codec": audio_stream.get('codec_name', 'unknown') if audio_stream else 'unknown',
                "sample_rate": int(audio_stream.get('sample_rate', 0)) if audio_stream else 0,
                "channels": int(audio_stream.get('channels', 0)) if audio_stream else 0
            } if audio_stream else None,
            "status": "success"
        }
        
        # 清理临时文件
        try:
            os.remove(temp_file)
            os.rmdir(temp_dir)
        except:
            pass
        
        return json.dumps(info, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"获取视频信息失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "error": error_msg,
            "status": "failed"
        }, ensure_ascii=False)

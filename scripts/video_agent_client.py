#!/usr/bin/env python3
"""
视频生成 Agent 客户端
支持多轮对话，友好的交互体验

功能：
- 自动拼接流式响应内容
- 支持多轮对话（相同 session_id）
- 友好的终端输出格式
- 自动保存视频链接
"""

import json
import requests
import sys
import time
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from pathlib import Path
from requests.exceptions import ChunkedEncodingError, RequestException


class VideoAgentClient:
    """视频生成 Agent 客户端"""
    
    def __init__(
        self,
        base_url: str = "https://tpjcdhrn36.coze.site",
        token: Optional[str] = None,
        project_id: str = "7611753037392199723",
        session_id: Optional[str] = None,
        max_retries: int = 2
    ):
        """
        初始化客户端
        
        Args:
            base_url: API 基础地址
            token: 授权令牌
            project_id: 项目 ID
            session_id: 会话 ID（用于多轮对话，不传则自动生成）
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.project_id = project_id
        self.session_id = session_id or f"session-{int(time.time())}"
        self.url = f"{self.base_url}/stream_run"
        self.cancel_url = f"{self.base_url}/cancel"
        self.max_retries = max_retries
        
        # 存储历史视频链接
        self.video_links = []
    
    def chat(
        self,
        text: str,
        verbose: bool = True,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> dict:
        """
        发送消息并获取响应
        
        Args:
            text: 用户输入文本
            verbose: 是否显示详细输出
            
        Returns:
            包含完整响应和元数据的字典
        """
        # 本地服务（localhost/127.0.0.1）可不传 token
        is_local = "localhost" in self.base_url or "127.0.0.1" in self.base_url
        token = self.token or ("local" if is_local else None)
        if not token:
            error_msg = "未配置 token，请使用 --token 或 --token-file 指定有效令牌"
            if verbose:
                print(f"❌ {error_msg}")
            return {"error": error_msg, "status_code": None}

        payload = {
            "content": {
                "query": {
                    "prompt": [{"type": "text", "content": {"text": text}}]
                }
            },
            "type": "query",
            "session_id": self.session_id,
            "project_id": self.project_id
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        
        if verbose:
            print(f"\n{'='*60}")
            print(f"📤 用户输入: {text}")
            print(f"{'='*60}\n")
        
        max_attempts = self.max_retries + 1
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            response = None
            try:
                response = requests.post(
                    self.url,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=1200  # 20分钟超时
                )

                if response.status_code != 200:
                    print(f"❌ 请求失败: {response.status_code}")
                    print(response.text)
                    return {"error": response.text, "status_code": response.status_code}

                result = self._process_stream(response, verbose, event_callback)
                if self._is_retryable_error(result.get("error")) and attempt < max_attempts:
                    wait_seconds = min(2 ** (attempt - 1), 5)
                    if verbose:
                        print(f"\n🔄 检测到流式中断，第 {attempt}/{max_attempts} 次重试，{wait_seconds} 秒后继续...")
                    time.sleep(wait_seconds)
                    continue

                return result
            except RequestException as e:
                last_exception = e
                if attempt < max_attempts:
                    wait_seconds = min(2 ** (attempt - 1), 5)
                    if verbose:
                        print(f"\n⚠️ 网络异常: {e}")
                        print(f"🔄 第 {attempt}/{max_attempts} 次重试，{wait_seconds} 秒后继续...")
                    time.sleep(wait_seconds)
                    continue
                return {"error": {"type": "request_exception", "message": str(e)}, "status_code": None}
            finally:
                if response is not None:
                    response.close()

        return {"error": {"type": "request_exception", "message": str(last_exception)}, "status_code": None}
    
    def _process_stream(
        self,
        response,
        verbose: bool = True,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> dict:
        """
        处理流式响应
        
        Args:
            response: requests 响应对象
            verbose: 是否显示详细输出
            
        Returns:
            解析后的响应数据
        """
        result = {
            "answer": "",
            "tool_calls": [],
            "videos": [],
            "error": None,
            "finish": False,
            "raw_messages": [],
            "run_id": None,
        }
        
        current_tool = None
        
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                
                if line.startswith("data:"):
                    data_text = line[5:].strip()
                    
                    try:
                        msg = json.loads(data_text)
                        result["raw_messages"].append(msg)
                        run_id = msg.get("run_id")
                        if run_id:
                            result["run_id"] = run_id
                        
                        msg_type = msg.get("type")
                        content = msg.get("content", {})
                        
                        # 处理不同类型的消息
                        if msg_type == "answer":
                            # 文本回答（流式）
                            answer_part = content.get("answer", "") if isinstance(content, dict) else ""
                            if answer_part:
                                result["answer"] += answer_part
                                progress = self._extract_progress(answer_part)
                                if progress and event_callback:
                                    event_callback({
                                        "type": "progress",
                                        "progress": progress,
                                        "run_id": result.get("run_id"),
                                    })
                                if verbose:
                                    print(answer_part, end="", flush=True)
                        
                        elif msg_type == "tool_request":
                            # 工具调用请求（兼容不同字段结构）
                            tool_req = content.get("tool_request", {}) if isinstance(content, dict) else {}
                            if not isinstance(tool_req, dict):
                                tool_req = {}
                            tool_name = self._resolve_tool_name(msg, content)
                            current_tool = tool_name
                            
                            if verbose:
                                print(f"\n\n🔧 调用工具: {tool_name}")
                                if tool_name == "unknown" and isinstance(content, dict):
                                    print(f"   ↳ 未匹配到工具名字段，content keys: {list(content.keys())}")
                            
                            result["tool_calls"].append({
                                "name": tool_name,
                                "params": tool_req.get("arguments", {})
                            })
                            if event_callback:
                                event_callback({
                                    "type": "tool_request",
                                    "tool_name": tool_name,
                                    "run_id": result.get("run_id"),
                                })
                        
                        elif msg_type == "tool_response":
                            # 工具调用响应
                            tool_resp = content.get("tool_response", {}) if isinstance(content, dict) else {}
                            
                            # 尝试解析视频链接
                            self._extract_videos(tool_resp, result, verbose)
                            if event_callback:
                                event_callback({
                                    "type": "tool_response",
                                    "run_id": result.get("run_id"),
                                })
                        
                        elif msg_type == "message_end":
                            # 消息结束
                            result["finish"] = True
                            if event_callback:
                                event_callback({
                                    "type": "message_end",
                                    "run_id": result.get("run_id"),
                                })
                            
                            if verbose:
                                print("\n")  # 换行
                        
                        elif msg_type == "error":
                            # 错误消息
                            error_info = content.get("error", {}) if isinstance(content, dict) else content
                            result["error"] = error_info
                            if event_callback:
                                event_callback({
                                    "type": "error",
                                    "error": error_info,
                                    "run_id": result.get("run_id"),
                                })
                            if verbose:
                                print(f"\n❌ 错误: {error_info}")
                        
                        elif msg_type == "heartbeat":
                            # 心跳消息（静默处理）
                            if event_callback:
                                event_callback({
                                    "type": "heartbeat",
                                    "run_id": msg.get("run_id") or result.get("run_id"),
                                })
                        
                    except json.JSONDecodeError:
                        if verbose:
                            print(f"[解析失败] {data_text}")
        except ChunkedEncodingError as e:
            result["error"] = {
                "type": "stream_interrupted",
                "message": str(e),
                "hint": "流式连接被提前中断，通常是网关超时或服务端断开"
            }
            if verbose:
                print(f"\n❌ 错误: {result['error']['message']}")
        except RequestException as e:
            result["error"] = {
                "type": "request_exception",
                "message": str(e)
            }
            if verbose:
                print(f"\n❌ 错误: {result['error']['message']}")
        
        return result

    def _extract_progress(self, text: str) -> Optional[str]:
        """从回复文本中提取进度信息（尽力而为）。"""
        if not text:
            return None
        patterns = [
            r"进度[:：]\s*\d+%",
            r"场景\s*\d+\s*/\s*\d+",
            r"第\s*\d+\s*批次",
            r"预计.*?分钟",
            r"正在生成.*",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    def _resolve_tool_name(self, msg: dict, content: dict) -> str:
        """兼容多种返回结构解析工具名。"""
        if not isinstance(content, dict):
            content = {}
        tool_req = content.get("tool_request", {})
        if not isinstance(tool_req, dict):
            tool_req = {}

        candidates = [
            tool_req.get("name"),
            tool_req.get("tool_name"),
            tool_req.get("tool"),
            content.get("tool_name"),
            content.get("name"),
            msg.get("tool_name"),
            msg.get("name"),
        ]

        for name in candidates:
            if isinstance(name, str) and name.strip():
                return name.strip()
        return "unknown"

    def _is_retryable_error(self, error) -> bool:
        """是否属于可自动重试的短暂错误。"""
        if not error:
            return False
        if isinstance(error, dict):
            error_type = str(error.get("type", "")).lower()
            message = str(error.get("message", "")).lower()
        else:
            error_type = ""
            message = str(error).lower()

        return error_type in {"stream_interrupted", "request_exception"} or "response ended prematurely" in message

    def cancel_run(self, run_id: str) -> dict:
        """取消服务端运行任务。"""
        is_local = "localhost" in self.base_url or "127.0.0.1" in self.base_url
        token = self.token or ("local" if is_local else None)
        if not token:
            return {"status": "failed", "message": "未配置 token，无法取消任务"}

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            resp = requests.post(
                f"{self.cancel_url}/{run_id}",
                headers=headers,
                timeout=30,
            )
            try:
                return resp.json()
            except Exception:
                return {"status": "unknown", "code": resp.status_code, "raw": resp.text}
        except RequestException as e:
            return {"status": "failed", "message": str(e)}
    
    def _extract_videos(self, tool_resp: dict, result: dict, verbose: bool):
        """
        从工具响应中提取视频链接
        
        Args:
            tool_resp: 工具响应内容
            result: 结果字典
            verbose: 是否显示详细输出
        """
        content = tool_resp.get("content", "")
        
        # 尝试解析 JSON
        try:
            data = json.loads(content) if isinstance(content, str) else content
            
            # 提取视频 URL
            video_url = data.get("video_url")
            if video_url:
                result["videos"].append(video_url)
                self.video_links.append({
                    "url": video_url,
                    "time": datetime.now().isoformat()
                })
                if verbose:
                    print(f"\n🎬 视频链接: {video_url}")
            
            # 提取多个视频 URL
            video_urls = data.get("video_urls", [])
            for url in video_urls:
                if url and url not in result["videos"]:
                    result["videos"].append(url)
                    self.video_links.append({
                        "url": url,
                        "time": datetime.now().isoformat()
                    })
                    if verbose:
                        print(f"\n🎬 视频链接: {url}")
            
            # 显示场景详情
            scene_details = data.get("scene_details", [])
            if scene_details and verbose:
                print(f"\n📋 场景详情:")
                for scene in scene_details:
                    idx = scene.get("scene_index", "?")
                    status = "✅" if scene.get("status") == "success" else "❌"
                    gen_time = scene.get("generation_time", "?")
                    print(f"   场景 {idx}: {status} (耗时: {gen_time}秒)")
            
            # 显示统计信息
            if data.get("status") == "success" and verbose:
                total_time = data.get("execution_time", "?")
                total_duration = data.get("total_duration", "?")
                scene_count = data.get("scene_count", "?")
                merged = "✅" if data.get("merged") else "❌"
                
                print(f"\n📊 生成统计:")
                print(f"   总场景数: {scene_count}")
                print(f"   视频时长: {total_duration}秒")
                print(f"   执行耗时: {total_time}秒")
                print(f"   自动拼接: {merged}")
                
        except (json.JSONDecodeError, TypeError):
            pass
    
    def get_video_history(self) -> list:
        """获取历史视频链接"""
        return self.video_links
    
    def new_session(self, session_id: Optional[str] = None):
        """
        开始新会话
        
        Args:
            session_id: 新的会话 ID（可选）
        """
        self.session_id = session_id or f"session-{int(time.time())}"
        print(f"🔄 新会话已创建: {self.session_id}")


@dataclass
class AsyncChatJob:
    job_id: str
    prompt: str
    status: str = "queued"  # queued/running/success/failed/cancelled
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    last_update: str = ""
    last_tool: str = ""
    run_id: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class AsyncChatManager:
    """本地后台任务管理：不阻塞交互输入。"""

    def __init__(self, client: VideoAgentClient):
        self.client = client
        self.jobs: Dict[str, AsyncChatJob] = {}
        self.lock = threading.Lock()

    def submit(self, prompt: str) -> AsyncChatJob:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        job = AsyncChatJob(job_id=job_id, prompt=prompt)
        with self.lock:
            self.jobs[job_id] = job

        worker = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        worker.start()
        return job

    def _run_job(self, job_id: str):
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = time.time()
            job.last_update = "任务已开始"

        def on_event(event: Dict[str, Any]):
            with self.lock:
                j = self.jobs.get(job_id)
                if not j:
                    return
                if event.get("run_id"):
                    j.run_id = event["run_id"]
                if event.get("type") == "tool_request":
                    j.last_tool = event.get("tool_name", "")
                    j.last_update = f"调用工具: {j.last_tool}"
                elif event.get("type") == "progress":
                    j.last_update = event.get("progress", "") or j.last_update
                elif event.get("type") == "heartbeat":
                    if not j.last_update:
                        j.last_update = "任务执行中（心跳）"

        result = self.client.chat(job.prompt, verbose=False, event_callback=on_event)
        with self.lock:
            job = self.jobs[job_id]
            job.result = result
            job.ended_at = time.time()
            job.run_id = result.get("run_id") or job.run_id
            if result.get("error"):
                err = result["error"]
                job.status = "failed"
                job.error = err if isinstance(err, str) else json.dumps(err, ensure_ascii=False)
                print(f"\n🔔 [任务完成] {job.job_id} 失败: {job.error}")
            else:
                job.status = "success"
                videos = result.get("videos", [])
                print(f"\n🔔 [任务完成] {job.job_id} 成功，视频数量: {len(videos)}")
                for url in videos[:3]:
                    print(f"   🎬 {url}")
                if len(videos) > 3:
                    print(f"   ... 其余 {len(videos) - 3} 个链接可用 status 查看")

    def list_jobs(self) -> List[AsyncChatJob]:
        with self.lock:
            return sorted(self.jobs.values(), key=lambda x: x.created_at, reverse=True)

    def get_job(self, job_id: str) -> Optional[AsyncChatJob]:
        with self.lock:
            return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"status": "not_found", "message": f"任务不存在: {job_id}"}
            run_id = job.run_id
            status = job.status

        if status not in {"queued", "running"}:
            return {"status": "not_running", "message": f"任务当前状态为 {status}，无需取消"}
        if not run_id:
            return {"status": "pending", "message": "任务尚未拿到 run_id，稍后再试"}

        result = self.client.cancel_run(run_id)
        with self.lock:
            job = self.jobs.get(job_id)
            if job and result.get("status") in {"success", "already_completed"}:
                job.status = "cancelled"
                job.ended_at = time.time()
                job.last_update = "已发送取消请求"
        return result


def _print_jobs(manager: AsyncChatManager):
    jobs = manager.list_jobs()
    if not jobs:
        print("\n暂无后台任务")
        return
    print("\n📋 后台任务列表:")
    for j in jobs:
        spent = int((j.ended_at or time.time()) - (j.started_at or j.created_at))
        print(f"   - {j.job_id} | {j.status} | {spent}s | {j.last_update or '无'}")


def _print_job_detail(manager: AsyncChatManager, job_id: str):
    job = manager.get_job(job_id)
    if not job:
        print(f"\n❌ 未找到任务: {job_id}")
        return
    print("\n🧾 任务详情:")
    print(f"   ID: {job.job_id}")
    print(f"   状态: {job.status}")
    print(f"   run_id: {job.run_id or '暂无'}")
    print(f"   最近进度: {job.last_update or '暂无'}")
    if job.last_tool:
        print(f"   最近工具: {job.last_tool}")
    if job.result and job.result.get("videos"):
        print("   视频链接:")
        for u in job.result["videos"]:
            print(f"   - {u}")
    if job.error:
        print(f"   错误: {job.error}")


def interactive_mode(client: VideoAgentClient):
    """
    交互模式：持续对话
    
    Args:
        client: 客户端实例
    """
    print("\n" + "="*60)
    print("🎥 视频生成 Agent - 交互模式")
    print("="*60)
    print(f"📌 会话 ID: {client.session_id}")
    print("💡 命令: quit/new/history/bg <内容>/jobs/status <job_id>/cancel <job_id>/help")
    print("="*60 + "\n")
    manager = AsyncChatManager(client)
    
    while True:
        try:
            user_input = input("👤 你: ").strip()
            
            if not user_input:
                continue
            
            # 命令处理
            if user_input.lower() == "quit":
                print("\n👋 再见！")
                break
            
            elif user_input.lower() == "new":
                client.new_session()
                continue
            
            elif user_input.lower() == "history":
                history = client.get_video_history()
                if history:
                    print("\n📹 历史视频:")
                    for i, v in enumerate(history, 1):
                        print(f"   {i}. {v['url']}")
                        print(f"      时间: {v['time']}")
                else:
                    print("\n暂无视频记录")
                continue
            elif user_input.lower() == "help":
                print("\n📚 可用命令:")
                print("   quit                     退出")
                print("   new                      新会话")
                print("   history                  查看视频历史")
                print("   bg <内容>                后台提交任务（不阻塞）")
                print("   jobs                     查看所有后台任务")
                print("   status <job_id>          查看任务详情和进度")
                print("   cancel <job_id>          取消任务")
                continue
            elif user_input.lower() == "jobs":
                _print_jobs(manager)
                continue
            elif user_input.lower().startswith("status "):
                job_id = user_input.split(" ", 1)[1].strip()
                _print_job_detail(manager, job_id)
                continue
            elif user_input.lower().startswith("cancel "):
                job_id = user_input.split(" ", 1)[1].strip()
                result = manager.cancel_job(job_id)
                print(f"\n🛑 取消结果: {json.dumps(result, ensure_ascii=False)}")
                continue
            elif user_input.lower().startswith("bg "):
                prompt = user_input[3:].strip()
                if not prompt:
                    print("\n❌ 用法: bg 你的请求")
                    continue
                job = manager.submit(prompt)
                print(f"\n🚀 后台任务已提交: {job.job_id}")
                print("   你可以继续提问；用 jobs/status 查看进度")
                continue
            
            # 发送消息
            print("\n🤖 Agent: ", end="")
            client.chat(user_input)
            
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")


def main():
    """主函数"""
    # 配置
    import argparse
    
    parser = argparse.ArgumentParser(description="视频生成 Agent 客户端")
    parser.add_argument("--url", default="https://tpjcdhrn36.coze.site", help="API 地址")
    parser.add_argument("--token", required=False, help="授权令牌")
    parser.add_argument("--token-file", default=".token", help="token 文件路径（默认: .token）")
    parser.add_argument("--project", default="7611753037392199723", help="项目 ID")
    parser.add_argument("--session", default=None, help="会话 ID（用于多轮对话）")
    parser.add_argument("--message", "-m", default=None, help="单次消息（不进入交互模式）")
    
    args = parser.parse_args()
    
    token = args.token
    if not token and args.token_file:
        token_path = Path(args.token_file)
        if token_path.exists():
            token = token_path.read_text(encoding="utf-8").strip()

    # 创建客户端
    client = VideoAgentClient(
        base_url=args.url,
        token=token,
        project_id=args.project,
        session_id=args.session
    )
    
    if args.message:
        # 单次消息模式
        result = client.chat(args.message)
        
        print("\n" + "="*60)
        print("📝 完整回复:")
        print("="*60)
        print(result["answer"])
        
        if result["videos"]:
            print("\n🎬 生成的视频:")
            for url in result["videos"]:
                print(f"   {url}")
        
        if result["error"]:
            print(f"\n❌ 错误: {result['error']}")
    else:
        # 交互模式
        interactive_mode(client)


if __name__ == "__main__":
    main()

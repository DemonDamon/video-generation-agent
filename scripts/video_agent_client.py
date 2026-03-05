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
from typing import Optional, Generator
from datetime import datetime


class VideoAgentClient:
    """视频生成 Agent 客户端"""
    
    def __init__(
        self,
        base_url: str = "https://tpjcdhrn36.coze.site",
        token: str = "<YOUR_TOKEN>",
        project_id: str = "7611753037392199723",
        session_id: Optional[str] = None
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
        
        # 存储历史视频链接
        self.video_links = []
    
    def chat(self, text: str, verbose: bool = True) -> dict:
        """
        发送消息并获取响应
        
        Args:
            text: 用户输入文本
            verbose: 是否显示详细输出
            
        Returns:
            包含完整响应和元数据的字典
        """
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
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        
        if verbose:
            print(f"\n{'='*60}")
            print(f"📤 用户输入: {text}")
            print(f"{'='*60}\n")
        
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
        
        return self._process_stream(response, verbose)
    
    def _process_stream(self, response, verbose: bool = True) -> dict:
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
            "raw_messages": []
        }
        
        current_tool = None
        
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            
            if line.startswith("data:"):
                data_text = line[5:].strip()
                
                try:
                    msg = json.loads(data_text)
                    result["raw_messages"].append(msg)
                    
                    msg_type = msg.get("type")
                    content = msg.get("content", {})
                    
                    # 处理不同类型的消息
                    if msg_type == "answer":
                        # 文本回答（流式）
                        answer_part = content.get("answer", "")
                        if answer_part:
                            result["answer"] += answer_part
                            if verbose:
                                print(answer_part, end="", flush=True)
                    
                    elif msg_type == "tool_request":
                        # 工具调用请求
                        tool_req = content.get("tool_request", {})
                        tool_name = tool_req.get("name", "unknown")
                        current_tool = tool_name
                        
                        if verbose:
                            print(f"\n\n🔧 调用工具: {tool_name}")
                        
                        result["tool_calls"].append({
                            "name": tool_name,
                            "params": tool_req.get("arguments", {})
                        })
                    
                    elif msg_type == "tool_response":
                        # 工具调用响应
                        tool_resp = content.get("tool_response", {})
                        
                        # 尝试解析视频链接
                        self._extract_videos(tool_resp, result, verbose)
                    
                    elif msg_type == "message_end":
                        # 消息结束
                        result["finish"] = True
                        
                        if verbose:
                            print("\n")  # 换行
                    
                    elif msg_type == "error":
                        # 错误消息
                        error_info = content.get("error", {})
                        result["error"] = error_info
                        if verbose:
                            print(f"\n❌ 错误: {error_info}")
                    
                    elif msg_type == "heartbeat":
                        # 心跳消息（静默处理）
                        pass
                    
                except json.JSONDecodeError:
                    if verbose:
                        print(f"[解析失败] {data_text}")
        
        return result
    
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
    print("💡 输入 'quit' 退出，'new' 开始新会话，'history' 查看视频历史")
    print("="*60 + "\n")
    
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
    parser.add_argument("--token", required=True, help="授权令牌")
    parser.add_argument("--project", default="7611753037392199723", help="项目 ID")
    parser.add_argument("--session", default=None, help="会话 ID（用于多轮对话）")
    parser.add_argument("--message", "-m", default=None, help="单次消息（不进入交互模式）")
    
    args = parser.parse_args()
    
    # 创建客户端
    client = VideoAgentClient(
        base_url=args.url,
        token=args.token,
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

"""
带心跳机制的 AgentStreamRunner

解决长时间工具执行导致前端 SSE 连接超时的问题。

问题：原始的 AgentStreamRunner 没有心跳机制，工具执行期间无消息发送，
前端认为连接超时而断开，导致工具成功后 LLM 无法发送最终回复。

解决方案：添加 30 秒间隔的心跳消息，保持连接活跃。
"""

import time
import asyncio
import threading
import contextvars
import logging
from typing import Any, Dict, AsyncIterable, Optional
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from coze_coding_utils.runtime_ctx.context import Context
from coze_coding_utils.helper.agent_helper import (
    to_client_message,
    to_stream_input,
    agent_iter_server_messages,
)
from coze_coding_utils.messages.server import (
    create_message_end_dict,
    create_message_error_dict,
    MESSAGE_END_CODE_CANCELED,
)
from coze_coding_utils.error.classifier import classify_error

logger = logging.getLogger(__name__)

# 心跳间隔（秒）
HEARTBEAT_INTERVAL_SECONDS = 30
# 总超时时间（秒）- 与 main.py 保持一致
TIMEOUT_SECONDS = 3600  # 1小时


class AgentStreamRunnerWithHeartbeat:
    """
    带心跳机制的 AgentStreamRunner
    
    与原始 AgentStreamRunner 的区别：
    - 添加了 heartbeat_sender 协程，每 30 秒发送一次心跳消息
    - 心跳消息保持 SSE 连接活跃，防止前端超时断开
    - 支持长时间运行的工具调用（如视频生成）
    """
    
    async def astream(
        self,
        payload: Dict[str, Any],
        graph: CompiledStateGraph,
        run_config: RunnableConfig,
        ctx: Context,
        run_opt: Optional[Any] = None
    ) -> AsyncIterable[Any]:
        """
        异步流式执行 Agent，带心跳机制
        
        Args:
            payload: 输入数据
            graph: LangGraph 编译后的图
            run_config: 运行配置
            ctx: 运行时上下文
            run_opt: 运行选项（可选）
        
        Yields:
            流式消息字典
        """
        client_msg, session_id = to_client_message(payload)
        run_config["recursion_limit"] = 100
        run_config["configurable"] = {"thread_id": session_id}
        stream_input = to_stream_input(client_msg)

        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        context = contextvars.copy_context()
        start_time = time.time()
        cancelled = threading.Event()
        
        # 心跳时间追踪
        last_heartbeat_time = [start_time]
        # 序列号追踪
        last_seq = [0]

        def producer():
            """生产者：执行 Agent 并将消息放入队列"""
            try:
                if cancelled.is_set():
                    logger.info(f"Producer cancelled before start for run_id: {ctx.run_id}")
                    return

                items = graph.stream(stream_input, stream_mode="messages", config=run_config, context=ctx)
                server_msgs_iter = agent_iter_server_messages(
                    items,
                    session_id=client_msg.session_id,
                    query_msg_id=client_msg.local_msg_id,
                    local_msg_id=client_msg.local_msg_id,
                    run_id=ctx.run_id,
                    log_id=ctx.logid,
                )
                
                for sm in server_msgs_iter:
                    if cancelled.is_set():
                        logger.info(f"Producer cancelled during iteration for run_id: {ctx.run_id}")
                        cancel_msg = create_message_end_dict(
                            code=MESSAGE_END_CODE_CANCELED,
                            message="Stream cancelled by upstream",
                            session_id=client_msg.session_id,
                            query_msg_id=client_msg.local_msg_id,
                            log_id=ctx.logid,
                            time_cost_ms=int((time.time() - start_time) * 1000),
                            reply_id=getattr(sm, 'reply_id', ''),
                            sequence_id=last_seq[0] + 1,
                        )
                        loop.call_soon_threadsafe(q.put_nowait, ("message", cancel_msg))
                        return

                    if time.time() - start_time > TIMEOUT_SECONDS:
                        logger.error(f"Agent execution timeout after {TIMEOUT_SECONDS}s for run_id: {ctx.run_id}")
                        timeout_msg = create_message_end_dict(
                            code="TIMEOUT",
                            message=f"Execution timeout: exceeded {TIMEOUT_SECONDS} seconds",
                            session_id=client_msg.session_id,
                            query_msg_id=client_msg.local_msg_id,
                            log_id=ctx.logid,
                            time_cost_ms=int((time.time() - start_time) * 1000),
                            reply_id=getattr(sm, 'reply_id', ''),
                            sequence_id=last_seq[0] + 1,
                        )
                        loop.call_soon_threadsafe(q.put_nowait, ("message", timeout_msg))
                        return
                    
                    # 发送正常消息
                    loop.call_soon_threadsafe(q.put_nowait, ("message", sm.dict()))
                    last_seq[0] = sm.sequence_id
                    
            except Exception as ex:
                if cancelled.is_set():
                    logger.info(f"Producer exception after cancel for run_id: {ctx.run_id}, ignoring: {ex}")
                    return
                err = classify_error(ex, {"node_name": "astream"})
                end_msg = create_message_error_dict(
                    code=str(err.code),
                    message=err.message,
                    session_id=client_msg.session_id,
                    query_msg_id=client_msg.local_msg_id,
                    log_id=ctx.logid,
                    reply_id="",
                    sequence_id=last_seq[0] + 1,
                )
                loop.call_soon_threadsafe(q.put_nowait, ("message", end_msg))
            finally:
                # 发送结束信号
                loop.call_soon_threadsafe(q.put_nowait, (None, None))

        async def heartbeat_sender():
            """
            心跳发送器：定期发送心跳消息保持连接活跃
            
            每 HEARTBEAT_INTERVAL_SECONDS 秒检查一次是否需要发送心跳。
            如果距离上次消息已超过心跳间隔，则发送心跳消息。
            """
            while True:
                try:
                    await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                    
                    if cancelled.is_set():
                        logger.debug(f"Heartbeat sender stopped for run_id: {ctx.run_id}")
                        return
                    
                    current_time = time.time()
                    if current_time - last_heartbeat_time[0] >= HEARTBEAT_INTERVAL_SECONDS:
                        # 发送心跳消息
                        heartbeat_msg = {
                            "type": "heartbeat",
                            "event": "ping",
                            "timestamp": int(current_time * 1000),
                            "run_id": ctx.run_id,
                        }
                        await q.put(("heartbeat", heartbeat_msg))
                        last_heartbeat_time[0] = current_time
                        logger.debug(f"Heartbeat sent for run_id: {ctx.run_id}")
                        
                except asyncio.CancelledError:
                    logger.debug(f"Heartbeat sender cancelled for run_id: {ctx.run_id}")
                    return
                except Exception as e:
                    logger.error(f"Heartbeat sender error for run_id: {ctx.run_id}: {e}")
                    return

        # 启动生产者线程
        producer_thread = threading.Thread(
            target=lambda: context.run(producer),
            daemon=True
        )
        producer_thread.start()
        
        # 启动心跳协程（关键！这是原始实现缺少的）
        heartbeat_task = asyncio.create_task(heartbeat_sender())

        try:
            while True:
                try:
                    # 使用 wait_for 避免无限阻塞
                    item = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_INTERVAL_SECONDS * 2)
                except asyncio.TimeoutError:
                    # 如果队列长时间无消息，检查生产者是否还活着
                    if not producer_thread.is_alive():
                        logger.info(f"Producer thread ended for run_id: {ctx.run_id}")
                        break
                    continue
                
                if item[0] is None:
                    # 收到结束信号
                    break
                
                msg_type, msg_data = item
                
                # 更新心跳时间（任何消息都算作活跃）
                last_heartbeat_time[0] = time.time()
                
                # 更新序列号
                if msg_type == "message" and isinstance(msg_data, dict):
                    if "sequence_id" in msg_data:
                        last_seq[0] = msg_data["sequence_id"]
                
                yield msg_data
                
        except asyncio.CancelledError:
            logger.info(f"Stream cancelled for run_id: {ctx.run_id}")
            cancelled.set()
            
            end_msg = create_message_end_dict(
                code=MESSAGE_END_CODE_CANCELED,
                message="Stream execution cancelled",
                session_id=client_msg.session_id,
                query_msg_id=client_msg.local_msg_id,
                log_id=ctx.logid,
                time_cost_ms=int((time.time() - start_time) * 1000),
                reply_id="",
                sequence_id=last_seq[0] + 1,
            )
            yield end_msg
            raise
        finally:
            # 清理资源
            cancelled.set()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            
            # 等待生产者线程结束（最多等 2 秒）
            producer_thread.join(timeout=2)
            
            logger.info(f"Stream ended for run_id: {ctx.run_id}, duration: {int(time.time() - start_time)}s")

    def stream(
        self,
        payload: Dict[str, Any],
        graph: CompiledStateGraph,
        run_config: RunnableConfig,
        ctx: Context,
        run_opt: Optional[Any] = None
    ):
        """
        同步流式执行（保留兼容性）
        
        注意：同步模式下无法实现真正的异步心跳。
        建议使用 astream 方法以获得完整的心跳支持。
        """
        import warnings
        warnings.warn(
            "Synchronous stream() does not support heartbeat mechanism. "
            "Use astream() for long-running tasks.",
            UserWarning
        )
        
        client_msg, session_id = to_client_message(payload)
        run_config["recursion_limit"] = 100
        run_config["configurable"] = {"thread_id": session_id}
        stream_input = to_stream_input(client_msg)
        t0 = time.time()
        
        try:
            items = graph.stream(stream_input, stream_mode="messages", config=run_config, context=ctx)
            server_msgs_iter = agent_iter_server_messages(
                items,
                session_id=client_msg.session_id,
                query_msg_id=client_msg.local_msg_id,
                local_msg_id=client_msg.local_msg_id,
                run_id=ctx.run_id,
                log_id=ctx.logid,
            )
            for sm in server_msgs_iter:
                yield sm.dict()
        except asyncio.CancelledError:
            logger.info(f"Stream cancelled for run_id: {ctx.run_id}")
            end_msg = create_message_end_dict(
                code=MESSAGE_END_CODE_CANCELED,
                message="Stream execution cancelled",
                session_id=client_msg.session_id,
                query_msg_id=client_msg.local_msg_id,
                log_id=ctx.logid,
                time_cost_ms=int((time.time() - t0) * 1000),
                reply_id="",
                sequence_id=1,
            )
            yield end_msg
            raise
        except Exception as ex:
            err = classify_error(ex, {"node_name": "stream"})
            end_msg = create_message_error_dict(
                code=str(err.code),
                message=err.message,
                session_id=client_msg.session_id,
                query_msg_id=client_msg.local_msg_id,
                log_id=ctx.logid,
                reply_id="",
                sequence_id=1,
            )
            yield end_msg

import argparse
import asyncio
import json
import threading
import traceback
import logging
import warnings
import time
import uuid
import re
import requests
from typing import Any, Dict, Iterable, AsyncIterable, AsyncGenerator, Optional
import cozeloop
import uvicorn
import os as _os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from coze_coding_utils.runtime_ctx.context import new_context, Context
from coze_coding_utils.helper import graph_helper
from coze_coding_utils.log.node_log import LOG_FILE
from coze_coding_utils.log.write_log import setup_logging, request_context
from coze_coding_utils.log.config import LOG_LEVEL
from coze_coding_utils.error.classifier import ErrorClassifier, classify_error
from coze_coding_utils.helper.stream_runner import AgentStreamRunner, WorkflowStreamRunner,agent_stream_handler,workflow_stream_handler, RunOpt

# 导入带心跳的 AgentStreamRunner
from utils.heartbeat_stream_runner import AgentStreamRunnerWithHeartbeat

# 过滤掉已知的非关键警告
warnings.filterwarnings('ignore', message='.*opening the async pool.*')
warnings.filterwarnings('ignore', message='.*Pydantic serializer warnings.*')
warnings.filterwarnings('ignore', category=DeprecationWarning, module='psycopg_pool')

setup_logging(
    log_file=LOG_FILE,
    max_bytes=100 * 1024 * 1024, # 100MB
    backup_count=5,
    log_level=LOG_LEVEL,
    use_json_format=True,
    console_output=True
)

# 禁用 cozeloop 追踪相关的错误日志（配额不足警告，不影响核心功能）
logging.getLogger('cozeloop.internal.trace.trace').setLevel(logging.CRITICAL)
logging.getLogger('cozeloop.internal.httpclient.http_client').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)
from coze_coding_utils.helper.agent_helper import to_stream_input
from coze_coding_utils.openai.handler import OpenAIChatHandler
from coze_coding_utils.log.parser import LangGraphParser
from coze_coding_utils.log.err_trace import extract_core_stack
from coze_coding_utils.log.loop_trace import init_run_config, init_agent_config


# 超时配置常量
# 长视频生成可能需要很长时间（多场景 × 单场景生成时间）
# 设置为 3600 秒（1小时），足以支持 3-4 个场景的长视频生成
TIMEOUT_SECONDS = 3600  # 1小时

class GraphService:
    def __init__(self):
        # 用于跟踪正在运行的任务（使用asyncio.Task）
        self.running_tasks: Dict[str, asyncio.Task] = {}
        # 后台任务状态（task_id 维度）
        self.background_tasks: Dict[str, Dict[str, Any]] = {}
        # 错误分类器
        self.error_classifier = ErrorClassifier()
        # stream runner
        # 使用带心跳的 AgentStreamRunner，解决长时间工具执行导致的超时问题
        self._agent_stream_runner = AgentStreamRunnerWithHeartbeat()
        self._workflow_stream_runner = WorkflowStreamRunner()
        self._graph = None
        self._graph_lock = threading.Lock()
        self._task_lock = threading.Lock()

    @staticmethod
    def _extract_progress_hint(text: str) -> str:
        if not text:
            return ""
        patterns = [
            r"进度[:：]\s*\d+%",
            r"场景\s*\d+\s*/\s*\d+",
            r"第\s*\d+\s*批次",
            r"正在生成[^。\n]*",
            r"预计[^。\n]*分钟",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                return m.group(0)
        return ""

    def _update_task_state(self, task_id: str, patch: Dict[str, Any]):
        with self._task_lock:
            task = self.background_tasks.get(task_id)
            if not task:
                return
            task.update(patch)
            task["updated_at"] = time.time()

    async def _post_callback(self, task_id: str):
        with self._task_lock:
            task = self.background_tasks.get(task_id)
            if not task:
                return
            callback_url = task.get("callback_url")
            callback_headers = task.get("callback_headers") or {}
            callback_payload = {
                "task_id": task_id,
                "run_id": task.get("run_id"),
                "status": task.get("status"),
                "progress": task.get("progress"),
                "last_update": task.get("last_update"),
                "error": task.get("error"),
                "result": task.get("result"),
                "created_at": task.get("created_at"),
                "started_at": task.get("started_at"),
                "ended_at": task.get("ended_at"),
            }

        if not callback_url:
            return

        def _send():
            try:
                requests.post(
                    callback_url,
                    json=callback_payload,
                    headers=callback_headers,
                    timeout=30,
                )
            except Exception as e:
                logger.error(f"Callback failed for task_id={task_id}: {e}")

        await asyncio.to_thread(_send)

    async def _run_background_task(
        self,
        task_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        workflow_debug: bool = False,
    ):
        ctx = new_context(method="task_background_run", headers=headers)
        request_context.set(ctx)
        run_id = ctx.run_id
        started_at = time.time()
        self._update_task_state(task_id, {
            "status": "running",
            "run_id": run_id,
            "started_at": started_at,
            "last_update": "任务已启动",
        })

        graph = self._get_graph(ctx)
        if graph_helper.is_agent_proj():
            run_config = init_agent_config(graph, ctx)
        else:
            run_config = init_run_config(graph, ctx)

        run_opt = RunOpt(workflow_debug=workflow_debug)
        result = {
            "answer": "",
            "videos": [],
            "error": None,
            "finish": False,
            "raw_messages": [],
            "run_id": run_id,
        }
        last_tool = ""

        try:
            # 注册运行中的 run_id，便于 /cancel 复用
            current_task = asyncio.current_task()
            if current_task:
                self.running_tasks[run_id] = current_task

            async for chunk in self.astream(payload, graph, run_config=run_config, ctx=ctx, run_opt=run_opt):
                if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[1], dict):
                    chunk = chunk[1]
                if not isinstance(chunk, dict):
                    continue

                result["raw_messages"].append(chunk)
                msg_type = chunk.get("type")
                content = chunk.get("content", {})
                if chunk.get("run_id"):
                    result["run_id"] = chunk["run_id"]
                    run_id = chunk["run_id"]
                    self._update_task_state(task_id, {"run_id": run_id})

                if msg_type == "answer":
                    answer_part = content.get("answer", "") if isinstance(content, dict) else ""
                    if answer_part:
                        result["answer"] += answer_part
                        hint = self._extract_progress_hint(answer_part)
                        if hint:
                            self._update_task_state(task_id, {
                                "progress": hint,
                                "last_update": hint,
                            })
                elif msg_type == "tool_request":
                    tool_req = content.get("tool_request", {}) if isinstance(content, dict) else {}
                    if isinstance(tool_req, dict):
                        last_tool = tool_req.get("name") or tool_req.get("tool_name") or last_tool
                    update_text = f"调用工具: {last_tool}" if last_tool else "工具调用中"
                    self._update_task_state(task_id, {
                        "last_tool": last_tool,
                        "last_update": update_text,
                    })
                elif msg_type == "tool_response":
                    tool_resp = content.get("tool_response", {}) if isinstance(content, dict) else {}
                    tool_content = tool_resp.get("content", "")
                    try:
                        data = json.loads(tool_content) if isinstance(tool_content, str) else tool_content
                        if isinstance(data, dict):
                            video_url = data.get("video_url")
                            if video_url and video_url not in result["videos"]:
                                result["videos"].append(video_url)
                            video_urls = data.get("video_urls") or []
                            if isinstance(video_urls, list):
                                for u in video_urls:
                                    if u and u not in result["videos"]:
                                        result["videos"].append(u)
                            if data.get("progress") is not None:
                                self._update_task_state(task_id, {
                                    "progress": data.get("progress"),
                                    "last_update": f"进度: {data.get('progress')}",
                                })
                    except Exception:
                        pass
                elif msg_type == "message_end":
                    result["finish"] = True
                elif msg_type == "error":
                    err = content.get("error", {}) if isinstance(content, dict) else content
                    result["error"] = err
                    self._update_task_state(task_id, {
                        "last_update": "任务执行错误",
                        "error": err if isinstance(err, str) else json.dumps(err, ensure_ascii=False),
                    })
                elif msg_type == "heartbeat":
                    if not result["finish"]:
                        self._update_task_state(task_id, {
                            "last_update": "任务执行中（心跳）",
                        })

            end_time = time.time()
            if result.get("error"):
                self._update_task_state(task_id, {
                    "status": "failed",
                    "ended_at": end_time,
                    "result": result,
                    "progress": "failed",
                })
            else:
                self._update_task_state(task_id, {
                    "status": "success",
                    "ended_at": end_time,
                    "result": result,
                    "progress": "100%",
                    "last_update": "任务完成",
                })

        except asyncio.CancelledError:
            self._update_task_state(task_id, {
                "status": "cancelled",
                "ended_at": time.time(),
                "progress": "cancelled",
                "last_update": "任务已取消",
            })
            raise
        except Exception as e:
            self._update_task_state(task_id, {
                "status": "failed",
                "ended_at": time.time(),
                "progress": "failed",
                "error": str(e),
                "last_update": "任务异常失败",
            })
            logger.error(f"Background task failed task_id={task_id}: {e}", exc_info=True)
        finally:
            self.running_tasks.pop(run_id, None)
            await self._post_callback(task_id)

    async def submit_background_task(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        callback_url: Optional[str] = None,
        callback_headers: Optional[Dict[str, str]] = None,
        workflow_debug: bool = False,
    ) -> Dict[str, Any]:
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        now = time.time()
        task_record = {
            "task_id": task_id,
            "run_id": None,
            "status": "queued",
            "progress": "queued",
            "last_update": "任务已入队",
            "last_tool": "",
            "error": None,
            "result": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "ended_at": None,
            "callback_url": callback_url,
            "callback_headers": callback_headers or {},
        }
        with self._task_lock:
            self.background_tasks[task_id] = task_record

        job = asyncio.create_task(
            self._run_background_task(
                task_id=task_id,
                payload=payload,
                headers=headers,
                workflow_debug=workflow_debug,
            )
        )
        with self._task_lock:
            self.background_tasks[task_id]["asyncio_task"] = job

        return {
            "task_id": task_id,
            "status": "queued",
            "message": "任务已提交，可通过 /task/status/{task_id} 查询进度",
        }

    def get_background_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._task_lock:
            task = self.background_tasks.get(task_id)
            if not task:
                return None
            safe = dict(task)
            safe.pop("asyncio_task", None)
            safe.pop("callback_headers", None)
            return safe

    def cancel_background_task(self, task_id: str) -> Dict[str, Any]:
        with self._task_lock:
            task = self.background_tasks.get(task_id)
            if not task:
                return {"status": "not_found", "task_id": task_id, "message": "任务不存在"}
            run_id = task.get("run_id")
            raw_asyncio_task = task.get("asyncio_task")
            status = task.get("status")

        if status in {"success", "failed", "cancelled"}:
            return {"status": "not_running", "task_id": task_id, "message": f"任务已结束: {status}"}

        cancel_result = {"status": "pending", "task_id": task_id, "message": "已请求取消"}
        if run_id:
            cancel_result = self.cancel_run(run_id)
            cancel_result["task_id"] = task_id

        if raw_asyncio_task and not raw_asyncio_task.done():
            raw_asyncio_task.cancel()

        self._update_task_state(task_id, {
            "status": "cancelled",
            "ended_at": time.time(),
            "progress": "cancelled",
            "last_update": "任务已取消",
        })
        return cancel_result

    def _get_graph(self, ctx=Context):
        if graph_helper.is_agent_proj():
            return graph_helper.get_agent_instance("agents.agent", ctx)

        if self._graph is not None:
            return self._graph
        with self._graph_lock:
            if self._graph is not None:
                return self._graph
            self._graph = graph_helper.get_graph_instance("graphs.graph")
            return self._graph

    @staticmethod
    def _sse_event(data: Any, event_id: Any = None) -> str:
        id_line = f"id: {event_id}\n" if event_id else ""
        return f"{id_line}event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    def _get_stream_runner(self):
        if graph_helper.is_agent_proj():
            return self._agent_stream_runner
        else:
            return self._workflow_stream_runner

    # 流式运行（原始迭代器）：本地调用使用
    def stream(self, payload: Dict[str, Any], run_config: RunnableConfig, ctx=Context) -> Iterable[Any]:
        graph = self._get_graph(ctx)
        stream_runner = self._get_stream_runner()
        for chunk in stream_runner.stream(payload, graph, run_config, ctx):
            yield chunk

    # 同步运行：本地/HTTP 通用
    async def run(self, payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
        if ctx is None:
            ctx = new_context("run")

        run_id = ctx.run_id
        logger.info(f"Starting run with run_id: {run_id}")

        try:
            graph = self._get_graph(ctx)
            # custom tracer
            run_config = init_run_config(graph, ctx)
            run_config["configurable"] = {"thread_id": ctx.run_id}

            # 直接调用，LangGraph会在当前任务上下文中执行
            # 如果当前任务被取消，LangGraph的执行也会被取消
            return await graph.ainvoke(payload, config=run_config, context=ctx)

        except asyncio.CancelledError:
            logger.info(f"Run {run_id} was cancelled")
            return {"status": "cancelled", "run_id": run_id, "message": "Execution was cancelled"}
        except Exception as e:
            # 使用错误分类器分类错误
            err = self.error_classifier.classify(e, {"node_name": "run", "run_id": run_id})
            # 记录详细的错误信息和堆栈跟踪
            logger.error(
                f"Error in GraphService.run: [{err.code}] {err.message}\n"
                f"Category: {err.category.name}\n"
                f"Traceback:\n{extract_core_stack()}"
            )
            # 保留原始异常堆栈，便于上层返回真正的报错位置
            raise
        finally:
            # 清理任务记录
            self.running_tasks.pop(run_id, None)

    # 流式运行（SSE 格式化）：HTTP 路由使用
    async def stream_sse(self, payload: Dict[str, Any], ctx=None, run_opt: Optional[RunOpt] = None) -> AsyncGenerator[str, None]:
        if ctx is None:
            ctx = new_context(method="stream_sse")
        if run_opt is None:
            run_opt = RunOpt()

        run_id = ctx.run_id
        logger.info(f"Starting stream with run_id: {run_id}")
        graph = self._get_graph(ctx)
        if graph_helper.is_agent_proj():
            run_config = init_agent_config(graph, ctx)
        else:
            run_config = init_run_config(graph, ctx)  # vibeflow

        is_workflow = not graph_helper.is_agent_proj()

        try:
            async for chunk in self.astream(payload, graph, run_config=run_config, ctx=ctx, run_opt=run_opt):
                if is_workflow and isinstance(chunk, tuple):
                    event_id, data = chunk
                    yield self._sse_event(data, event_id)
                else:
                    yield self._sse_event(chunk)
        finally:
            # 清理任务记录
            self.running_tasks.pop(run_id, None)
            cozeloop.flush()

    # 取消执行 - 使用asyncio的标准方式
    def cancel_run(self, run_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
        """
        取消指定run_id的执行

        使用asyncio.Task.cancel()来取消任务,这是标准的Python异步取消机制。
        LangGraph会在节点之间检查CancelledError,实现优雅的取消。
        """
        logger.info(f"Attempting to cancel run_id: {run_id}")

        # 查找对应的任务
        if run_id in self.running_tasks:
            task = self.running_tasks[run_id]
            if not task.done():
                # 使用asyncio的标准取消机制
                # 这会在下一个await点抛出CancelledError
                task.cancel()
                logger.info(f"Cancellation requested for run_id: {run_id}")
                return {
                    "status": "success",
                    "run_id": run_id,
                    "message": "Cancellation signal sent, task will be cancelled at next await point"
                }
            else:
                logger.info(f"Task already completed for run_id: {run_id}")
                return {
                    "status": "already_completed",
                    "run_id": run_id,
                    "message": "Task has already completed"
                }
        else:
            logger.warning(f"No active task found for run_id: {run_id}")
            return {
                "status": "not_found",
                "run_id": run_id,
                "message": "No active task found with this run_id. Task may have already completed or run_id is invalid."
            }

    # 运行指定节点：本地/HTTP 通用
    async def run_node(self, node_id: str, payload: Dict[str, Any], ctx=None) -> Any:
        if ctx is None or Context.run_id == "":
            ctx = new_context(method="node_run")

        _graph = self._get_graph()
        node_func, input_cls, output_cls = graph_helper.get_graph_node_func_with_inout(_graph.get_graph(), node_id)
        if node_func is None or input_cls is None:
            raise KeyError(f"node_id '{node_id}' not found")

        parser = LangGraphParser(_graph)
        metadata = parser.get_node_metadata(node_id) or {}

        _g = StateGraph(input_cls, input_schema=input_cls, output_schema=output_cls)
        _g.add_node("sn", node_func, metadata=metadata)
        _g.set_entry_point("sn")
        _g.add_edge("sn", END)
        _graph = _g.compile()

        run_config = init_run_config(_graph, ctx)
        return await _graph.ainvoke(payload, config=run_config)

    def graph_inout_schema(self) -> Any:
        if graph_helper.is_agent_proj():
            return {"input_schema": {}, "output_schema": {}}
        builder = getattr(self._get_graph(), 'builder', None)
        if builder is not None:
            input_cls = getattr(builder, 'input_schema', None) or self.graph.get_input_schema()
            output_cls = getattr(builder, 'output_schema', None) or self.graph.get_output_schema()
        else:
            logger.warning(f"No builder input schema found for graph_inout_schema, using graph input schema instead")
            input_cls = self.graph.get_input_schema()
            output_cls = self.graph.get_output_schema()

        return {
            "input_schema": input_cls.model_json_schema(), 
            "output_schema": output_cls.model_json_schema(),
            "code":0,
            "msg":""
        }

    async def astream(self, payload: Dict[str, Any], graph: CompiledStateGraph, run_config: RunnableConfig, ctx=Context, run_opt: Optional[RunOpt] = None) -> AsyncIterable[Any]:
        stream_runner = self._get_stream_runner()
        async for chunk in stream_runner.astream(payload, graph, run_config, ctx, run_opt):
            yield chunk


service = GraphService()
app = FastAPI()

# 本地视频输出目录（当未配置对象存储时，视频保存到此目录，可通过 /videos/ 访问）
# 在 FaaS 部署环境中，使用 /tmp 目录（因为 /opt/bytefaas 是只读的）
# 检测方式：/opt/bytefaas 目录存在
_default_video_output = "/tmp/output/videos" if _os.path.exists("/opt/bytefaas") else "output/videos"
_video_output_dir = _os.getenv("LOCAL_VIDEO_OUTPUT_DIR", _default_video_output)
_video_output_abs = _os.path.abspath(_video_output_dir)

# 确保目录存在（仅在可写文件系统上创建）
try:
    _os.makedirs(_video_output_abs, exist_ok=True)
    app.mount("/videos", StaticFiles(directory=_video_output_abs), name="videos")
    logger.info(f"Static videos mounted at /videos -> {_video_output_abs}")
except OSError as e:
    logger.warning(f"Cannot create video output directory {_video_output_abs}: {e}")
    logger.info("Video output will use object storage only")

# OpenAI 兼容接口处理器
openai_handler = OpenAIChatHandler(service)


@app.post("/run")
async def http_run(request: Request) -> Dict[str, Any]:
    global result
    raw_body = await request.body()
    try:
        body_text = raw_body.decode("utf-8")
    except Exception as e:
        body_text = str(raw_body)
        raise HTTPException(status_code=400,
                            detail=f"Invalid JSON format: {body_text}, traceback: {traceback.format_exc()}, error: {e}")

    ctx = new_context(method="run", headers=request.headers)
    run_id = ctx.run_id
    request_context.set(ctx)

    logger.info(
        f"Received request for /run: "
        f"run_id={run_id}, "
        f"query={dict(request.query_params)}, "
        f"body={body_text}"
    )

    try:
        payload = await request.json()

        # 创建任务并记录 - 这是关键，让我们可以通过run_id取消任务
        task = asyncio.create_task(service.run(payload, ctx))
        service.running_tasks[run_id] = task

        try:
            result = await asyncio.wait_for(task, timeout=float(TIMEOUT_SECONDS))
        except asyncio.TimeoutError:
            logger.error(f"Run execution timeout after {TIMEOUT_SECONDS}s for run_id: {run_id}")
            task.cancel()
            try:
                result = await task
            except asyncio.CancelledError:
                return {
                    "status": "timeout",
                    "run_id": run_id,
                    "message": f"Execution timeout: exceeded {TIMEOUT_SECONDS} seconds"
                }

        if not result:
            result = {}
        if isinstance(result, dict):
            result["run_id"] = run_id
        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in http_run: {e}, traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON format, {extract_core_stack()}")

    except asyncio.CancelledError:
        logger.info(f"Request cancelled for run_id: {run_id}")
        result = {"status": "cancelled", "run_id": run_id, "message": "Execution was cancelled"}
        return result

    except Exception as e:
        # 使用错误分类器获取错误信息
        error_response = service.error_classifier.get_error_response(e, {"node_name": "http_run", "run_id": run_id})
        logger.error(
            f"Unexpected error in http_run: [{error_response['error_code']}] {error_response['error_message']}, "
            f"traceback: {traceback.format_exc()}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": error_response["error_code"],
                "error_message": error_response["error_message"],
                "stack_trace": extract_core_stack(),
            }
        )
    finally:
        cozeloop.flush()


HEADER_X_WORKFLOW_STREAM_MODE = "x-workflow-stream-mode"


def _register_task(run_id: str, task: asyncio.Task):
    service.running_tasks[run_id] = task


@app.post("/stream_run")
async def http_stream_run(request: Request):
    ctx = new_context(method="stream_run", headers=request.headers)
    workflow_stream_mode = request.headers.get(HEADER_X_WORKFLOW_STREAM_MODE, "").lower()
    workflow_debug = workflow_stream_mode == "debug"
    request_context.set(ctx)
    raw_body = await request.body()
    try:
        body_text = raw_body.decode("utf-8")
    except Exception as e:
        body_text = str(raw_body)
        raise HTTPException(status_code=400,
                            detail=f"Invalid JSON format: {body_text}, traceback: {extract_core_stack()}, error: {e}")
    run_id = ctx.run_id
    is_agent = graph_helper.is_agent_proj()
    logger.info(
        f"Received request for /stream_run: "
        f"run_id={run_id}, "
        f"is_agent_project={is_agent}, "
        f"query={dict(request.query_params)}, "
        f"body={body_text}"
    )
    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in http_stream_run: {e}, traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON format:{extract_core_stack()}")

    if is_agent:
        stream_generator = agent_stream_handler(
            payload=payload,
            ctx=ctx,
            run_id=run_id,
            stream_sse_func=service.stream_sse,
            sse_event_func=service._sse_event,
            error_classifier=service.error_classifier,
            register_task_func=_register_task,
        )
    else:
        stream_generator = workflow_stream_handler(
            payload=payload,
            ctx=ctx,
            run_id=run_id,
            stream_sse_func=service.stream_sse,
            sse_event_func=service._sse_event,
            error_classifier=service.error_classifier,
            register_task_func=_register_task,
            run_opt=RunOpt(workflow_debug=workflow_debug),
        )

    response = StreamingResponse(stream_generator, media_type="text/event-stream")
    return response

@app.post("/cancel/{run_id}")
async def http_cancel(run_id: str, request: Request):
    """
    取消指定run_id的执行

    使用asyncio.Task.cancel()实现取消,这是Python标准的异步任务取消机制。
    LangGraph会在节点之间的await点检查CancelledError,实现优雅取消。
    """
    ctx = new_context(method="cancel", headers=request.headers)
    request_context.set(ctx)
    logger.info(f"Received cancel request for run_id: {run_id}")
    result = service.cancel_run(run_id, ctx)
    return result


@app.post("/task/submit")
async def http_task_submit(request: Request):
    """
    提交后台异步任务（非阻塞）。

    请求体格式：
    {
      "payload": {...},                # 必填，和 /stream_run 的请求体一致
      "callback_url": "https://...",   # 可选，任务结束后回调
      "callback_headers": {...},       # 可选，回调时附带的请求头
      "workflow_debug": false          # 可选，workflow 调试模式
    }
    """
    ctx = new_context(method="task_submit", headers=request.headers)
    request_context.set(ctx)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    payload = body.get("payload")
    callback_url = body.get("callback_url")
    callback_headers = body.get("callback_headers") or {}
    workflow_debug = bool(body.get("workflow_debug", False))

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="'payload' is required and must be an object")
    if callback_url is not None and not isinstance(callback_url, str):
        raise HTTPException(status_code=400, detail="'callback_url' must be a string")
    if not isinstance(callback_headers, dict):
        raise HTTPException(status_code=400, detail="'callback_headers' must be an object")

    headers = dict(request.headers)
    result = await service.submit_background_task(
        payload=payload,
        headers=headers,
        callback_url=callback_url,
        callback_headers=callback_headers,
        workflow_debug=workflow_debug,
    )
    return result


@app.get("/task/status/{task_id}")
async def http_task_status(task_id: str):
    """查询后台任务状态。"""
    status = service.get_background_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"task_id '{task_id}' not found")
    return status


@app.get("/task/result/{task_id}")
async def http_task_result(task_id: str):
    """查询后台任务结果（仅任务结束后可拿到完整结果）。"""
    status = service.get_background_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"task_id '{task_id}' not found")
    return {
        "task_id": task_id,
        "status": status.get("status"),
        "run_id": status.get("run_id"),
        "error": status.get("error"),
        "result": status.get("result"),
    }


@app.post("/task/cancel/{task_id}")
async def http_task_cancel(task_id: str):
    """按 task_id 取消后台任务。"""
    result = service.cancel_background_task(task_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message", "task not found"))
    return result


@app.post(path="/node_run/{node_id}")
async def http_node_run(node_id: str, request: Request):
    raw_body = await request.body()
    try:
        body_text = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body_text = str(raw_body)
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {body_text}")
    ctx = new_context(method="node_run", headers=request.headers)
    request_context.set(ctx)
    logger.info(
        f"Received request for /node_run/{node_id}: "
        f"query={dict(request.query_params)}, "
        f"body={body_text}",
    )

    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in http_node_run: {e}, traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON format:{extract_core_stack()}")
    try:
        return await service.run_node(node_id, payload, ctx)
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"node_id '{node_id}' not found or input miss required fields, traceback: {extract_core_stack()}")
    except Exception as e:
        # 使用错误分类器获取错误信息
        error_response = service.error_classifier.get_error_response(e, {"node_name": node_id})
        logger.error(
            f"Unexpected error in http_node_run: [{error_response['error_code']}] {error_response['error_message']}, "
            f"traceback: {traceback.format_exc()}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": error_response["error_code"],
                "error_message": error_response["error_message"],
                "stack_trace": extract_core_stack(),
            }
        )
    finally:
        cozeloop.flush()


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI Chat Completions API 兼容接口"""
    ctx = new_context(method="openai_chat", headers=request.headers)
    request_context.set(ctx)

    logger.info(f"Received request for /v1/chat/completions: run_id={ctx.run_id}")

    try:
        payload = await request.json()
        return await openai_handler.handle(payload, ctx)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in openai_chat_completions: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    finally:
        cozeloop.flush()


@app.get("/health")
async def health_check():
    try:
        # 这里可以添加更多的健康检查逻辑
        return {
            "status": "ok",
            "message": "Service is running",
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get(path="/graph_parameter")
async def http_graph_inout_parameter(request: Request):
    return service.graph_inout_schema()

def parse_args():
    parser = argparse.ArgumentParser(description="Start FastAPI server")
    parser.add_argument("-m", type=str, default="http", help="Run mode, support http,flow,node")
    parser.add_argument("-n", type=str, default="", help="Node ID for single node run")
    parser.add_argument("-p", type=int, default=5000, help="HTTP server port")
    parser.add_argument("-i", type=str, default="", help="Input JSON string for flow/node mode")
    return parser.parse_args()


def parse_input(input_str: str) -> Dict[str, Any]:
    """Parse input string, support both JSON string and plain text"""
    if not input_str:
        return {"text": "你好"}

    # Try to parse as JSON first
    try:
        return json.loads(input_str)
    except json.JSONDecodeError:
        # If not valid JSON, treat as plain text
        return {"text": input_str}

def start_http_server(port):
    workers = 1
    # 注意：禁用 reload 功能，避免代码修改时自动重启导致正在运行的长视频生成任务丢失
    # 如需开发调试，可以临时改为 True，但注意长时间任务会被中断
    reload = False
    # if graph_helper.is_dev_env():
    #     reload = True

    logger.info(f"Start HTTP Server, Port: {port}, Workers: {workers}, Reload: {reload}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload, workers=workers)

if __name__ == "__main__":
    args = parse_args()
    if args.m == "http":
        start_http_server(args.p)
    elif args.m == "flow":
        payload = parse_input(args.i)
        result = asyncio.run(service.run(payload))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.m == "node" and args.n:
        payload = parse_input(args.i)
        result = asyncio.run(service.run_node(args.n, payload))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.m == "agent":
        agent_ctx = new_context(method="agent")
        for chunk in service.stream(
                {
                    "type": "query",
                    "session_id": "1",
                    "message": "你好",
                    "content": {
                        "query": {
                            "prompt": [
                                {
                                    "type": "text",
                                    "content": {"text": "现在几点了？请调用工具获取当前时间"},
                                }
                            ]
                        }
                    },
                },
                run_config={"configurable": {"session_id": "1"}},
                ctx=agent_ctx,
        ):
            print(chunk)

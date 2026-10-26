"""
Agent handler — EdgeOne Makers
========================================

文件路径 agents/chat/index.py 自动映射为 **POST /chat**。
（Makers 约定：目录名 = 路由名，`index` 为默认入口。）

出行决策 Agent：用户输入位置 + 品牌偏好 → 检索附近商场 → 核对品牌门店 → 比较距离 → 生成推荐。
技术栈为 **LangGraph**（ReAct 循环 + 高德工具 + 按会话保存的多轮记忆），
模型走环境变量里的 OpenAI 兼容网关（AI_GATEWAY_*）。

`context` 契约：
    context.request.body    — dict，请求体
    context.request.signal  — asyncio.Event，/chat/stop 被调用时置位
    context.conversation_id — 会话 ID（拿来当 LangGraph 的 thread_id，实现连续追问）
    context.store           — 平台内置存储
"""

from typing import Any, AsyncGenerator
import asyncio
import json

from dotenv import load_dotenv

from .._logger import create_logger
from .._travel.graph import astream_agent

load_dotenv()

logger = create_logger("chat")


# ========== SSE Helper ==========
def sse_event(event: str, data: dict) -> str:
    """格式化一个 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ========== Core Handler ==========
async def handler(context: Any) -> AsyncGenerator[str, None]:
    """Makers 入口：把 LangGraph 的事件流转成 SSE 推给前端。

    事件映射（对齐前端 src/api.ts 的约定）：
        LangGraph token → SSE text_delta
        LangGraph tool  → SSE tool_called
        LangGraph error → SSE error
        流结束          → SSE done
    """
    request = context.request
    body = request.body if isinstance(request.body, dict) else {}
    message = body.get("message")

    if not message:
        yield sse_event("error", {"message": "'message' is required"})
        yield sse_event("done", {})
        return

    cid = context.conversation_id or "default"
    # 多轮记忆的关键：同一会话 ID 复用同一个 LangGraph 线程
    thread_id = cid

    raw_user_id = body.get("userId") or body.get("user_id") or ""
    user_id = str(raw_user_id).strip() or None

    logger.log(f"[request] cid={cid}, uid={user_id or '-'}, message={message[:50]!r}")

    cancel_signal = getattr(request, "signal", None)
    stopped = False
    answer_parts: list[str] = []

    # 先把用户消息落到平台存储，保证 /history 与会话列表能读到本轮
    if cid:
        try:
            await context.store.append_message(
                conversation_id=cid, role="user", content=message, user_id=user_id
            )
        except Exception as e:  # 存储失败不应影响对话本身
            logger.error(f"[store] append user failed: {type(e).__name__}: {e}")

    try:
        async for event in astream_agent(message, thread_id=thread_id):
            # 用户点了「停止」就中断 LLM 调用
            if cancel_signal is not None and cancel_signal.is_set():
                stopped = True
                break

            etype = event.get("type")

            if etype == "token":
                delta = event.get("text", "")
                if delta:
                    answer_parts.append(delta)
                    yield sse_event("text_delta", {"delta": delta})

            elif etype == "tool":
                tool_name = event.get("name", "")
                if tool_name:
                    logger.log(f"[stream] tool_called: {tool_name}")
                    yield sse_event("tool_called", {"tool": tool_name})

            elif etype == "error":
                logger.error(f"[stream] agent error: {event.get('text', '')}")
                yield sse_event("error", {"message": event.get("text", "")})

    except asyncio.CancelledError:
        stopped = True
        logger.log("[stream] cancelled")
    except Exception as e:
        logger.error(f"[stream] error: {type(e).__name__}: {e}")
        yield sse_event("error", {"message": str(e), "errorType": type(e).__name__})
    finally:
        # 落库完整回答，供 /history 回看
        answer = "".join(answer_parts)
        if answer and cid:
            try:
                await context.store.append_message(
                    conversation_id=cid, role="assistant", content=answer
                )
            except Exception as e:
                logger.error(f"[store] append assistant failed: {type(e).__name__}: {e}")

        yield sse_event("done", {"stopped": stopped})

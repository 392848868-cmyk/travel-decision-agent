"""LangGraph 图定义：出行决策 Agent 的大脑。

结构（ReAct 循环）：
    ┌─────────┐   需要工具?    ┌──────────┐
    │  agent  │ ─────────────▶ │  tools   │
    │ (LLM)   │ ◀───────────── │(高德API) │
    └─────────┘   工具返回     └──────────┘
         │ 不需要工具
         ▼
       END（输出推荐）

记忆：checkpointer 按 thread_id 保存完整消息历史，因此支持多轮追问。
"""

from __future__ import annotations

import inspect
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from .config import get_llm_config
from .prompts import SYSTEM_PROMPT
from .tools import TOOLS, TOOL_LABELS

# 不同 langgraph 版本的记忆类名不一致，做兼容
try:  # langgraph >= 0.3
    from langgraph.checkpoint.memory import InMemorySaver as _Checkpointer
except ImportError:  # pragma: no cover
    from langgraph.checkpoint.memory import MemorySaver as _Checkpointer  # type: ignore

_checkpointer: Any | None = None
_graph: Any | None = None


def get_checkpointer() -> Any:
    """全局单例：Web 服务重启前，多轮对话记忆一直保留。"""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _Checkpointer()
    return _checkpointer


def _build_llm() -> ChatOpenAI:
    cfg = get_llm_config()
    return ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        temperature=0.2,
        timeout=60,
        max_retries=1,
    )


def get_graph():
    """构建（并缓存）LangGraph 图。"""
    global _graph
    if _graph is not None:
        return _graph

    kwargs: dict[str, Any] = {
        "checkpointer": get_checkpointer(),
        "tools": TOOLS,
    }
    # 兼容不同版本 create_react_agent 的系统提示词参数名
    sig = inspect.signature(create_react_agent).parameters
    if "prompt" in sig:
        kwargs["prompt"] = SYSTEM_PROMPT
    elif "state_modifier" in sig:  # pragma: no cover
        kwargs["state_modifier"] = SYSTEM_PROMPT
    elif "messages_modifier" in sig:  # pragma: no cover
        kwargs["messages_modifier"] = SYSTEM_PROMPT

    _graph = create_react_agent(_build_llm(), **kwargs)
    return _graph


def _to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return "" if content is None else str(content)


async def astream_agent(message: str, thread_id: str = "default") -> AsyncIterator[dict]:
    """流式执行 Agent，产出前端可直接渲染的事件流。

    事件类型：
      - {"type": "tool", "name": "检索附近商场"}   工具被调用（前端显示进度）
      - {"type": "token", "text": "..."}         模型输出的文本片段
      - {"type": "error", "text": "..."}         出错信息
    """
    emitted_tools: set[str] = set()
    try:
        graph = get_graph()  # 密钥缺失等配置错误会在这里抛出，统一转成 error 事件
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
        async for chunk, meta in graph.astream(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            stream_mode="messages",
        ):
            node = meta.get("langgraph_node", "")

            # 工具执行完成后会回传 ToolMessage，带工具名
            if node == "tools":
                tool_name = getattr(chunk, "name", "") or ""
                if tool_name and tool_name not in emitted_tools:
                    emitted_tools.add(tool_name)
                    # name=英文原名（前端按它匹配图标），label=中文名（直接展示用）
                    yield {
                        "type": "tool",
                        "name": tool_name,
                        "label": TOOL_LABELS.get(tool_name, tool_name),
                    }
                continue

            # 流式模型返回 AIMessageChunk；不支持流式的模型会直接给 AIMessage，两种都要接住
            if not isinstance(chunk, (AIMessageChunk, AIMessage)):
                continue

            # 模型决定调用工具：这里能提前拿到工具名
            for call in getattr(chunk, "tool_call_chunks", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
                if name and name not in emitted_tools:
                    emitted_tools.add(name)
                    yield {
                        "type": "tool",
                        "name": name,
                        "label": TOOL_LABELS.get(name, name),
                    }
            for call in getattr(chunk, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
                if name and name not in emitted_tools:
                    emitted_tools.add(name)
                    yield {
                        "type": "tool",
                        "name": name,
                        "label": TOOL_LABELS.get(name, name),
                    }

            text = _to_text(chunk.content)
            if text:
                yield {"type": "token", "text": text}

    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "text": f"Agent 执行失败：{exc}"}


def run_agent(message: str, thread_id: str = "default") -> str:
    """非流式执行，适合命令行调试或其他运行时集成。"""
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
    result = graph.invoke({"messages": [HumanMessage(content=message)]}, config=config)
    messages = result.get("messages", [])
    if not messages:
        return ""
    return _to_text(messages[-1].content)

"""Makers handler 测试：用假模型验证 agents/chat/index.py 的 SSE 协议是否正确。

这是「线上真正跑的那条链路」，不需要任何真实密钥。
运行：python tests/test_makers_handler.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

os.environ.setdefault("AI_GATEWAY_API_KEY", "sk-handler-test")
os.environ.pop("AMAP_API_KEY", None)  # 故意不配高德 Key，走工具容错分支

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402

from agents._travel import graph as graph_module  # noqa: E402
from agents._travel.prompts import SYSTEM_PROMPT  # noqa: E402
from agents._travel.tools import TOOLS  # noqa: E402
from agents.chat.index import handler  # noqa: E402


class ScriptedModel(BaseChatModel):
    """第一轮调工具，第二轮给结论。"""

    @property
    def _llm_type(self) -> str:
        return "scripted-model"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        ai_count = sum(1 for m in messages if isinstance(m, AIMessage))
        if ai_count == 0:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "geocode_location",
                        "args": {"address": "红莲南路地铁站", "city": "北京"},
                        "id": "call_1",
                    }
                ],
            )
        else:
            msg = AIMessage(content="### 我的推荐\n\n**示例商场** —— 距离约 1.2 km")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self


class FakeStore:
    """模拟平台存储，记录写入情况。"""

    def __init__(self) -> None:
        self.written: list[dict] = []

    async def append_message(self, conversation_id, role, content, user_id=None):
        self.written.append(
            {"conversation_id": conversation_id, "role": role, "content": content, "user_id": user_id}
        )
        return "msg-id"


def parse_sse(raw: str) -> list[dict]:
    """把 'event: x\\ndata: {...}\\n\\n' 解析成 [{"event":..., "data":...}]。"""
    frames = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        frames.append({"event": event, "data": data})
    return frames


async def main() -> None:
    # 用假模型替换真实图，避免依赖密钥
    graph_module._graph = create_react_agent(
        ScriptedModel(), tools=TOOLS, prompt=SYSTEM_PROMPT, checkpointer=InMemorySaver()
    )

    store = FakeStore()
    context = SimpleNamespace(
        request=SimpleNamespace(body={"message": "我在红莲南路地铁站附近"}, signal=asyncio.Event()),
        conversation_id="handler-test",
        store=store,
    )

    raw = ""
    async for chunk in handler(context):
        raw += chunk

    frames = parse_sse(raw)
    events = [f["event"] for f in frames]

    print("SSE 事件序列:", events)
    print("原始输出前 200 字符:", raw[:200].replace("\n", "\\n"))

    assert "tool_called" in events, f"缺少工具事件: {events}"
    assert "text_delta" in events, f"缺少流式文本事件: {events}"
    assert events[-1] == "done", f"事件流没有以 done 结束: {events}"

    # 前端按英文工具名匹配图标，所以要传 name 而不是中文 label
    tool_frame = next(f for f in frames if f["event"] == "tool_called")
    assert tool_frame["data"]["tool"] == "geocode_location", f"工具名应为英文原名: {tool_frame}"

    # 平台存储应写入本轮 user + assistant，供 /history 回看
    roles = [w["role"] for w in store.written]
    assert "user" in roles and "assistant" in roles, f"存储写入不完整: {roles}"

    # 缺 message 时应报错而不是崩
    empty_ctx = SimpleNamespace(
        request=SimpleNamespace(body={}, signal=asyncio.Event()),
        conversation_id="handler-test",
        store=FakeStore(),
    )
    raw2 = ""
    async for chunk in handler(empty_ctx):
        raw2 += chunk
    assert "error" in [f["event"] for f in parse_sse(raw2)], "缺 message 时未返回 error"

    print("\n[OK] Makers handler 测试通过：tool_called → text_delta → done，且历史已落库")


if __name__ == "__main__":
    asyncio.run(main())

"""冒烟测试：不需要任何真实密钥，验证「图能编译 + 工具能容错 + 循环能跑通」。

运行：python tests/smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，强制用 UTF-8 输出，避免中文/emoji 报编码错误
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

# 用假密钥让 LLM 客户端能构造出来（不会真的发请求）
os.environ.setdefault("AI_GATEWAY_API_KEY", "sk-smoke-test")
os.environ.setdefault("AI_GATEWAY_BASE_URL", "https://ai-gateway.edgeone.link/v1")
os.environ.setdefault("AI_GATEWAY_MODEL", "@makers/deepseek-v4-flash")
os.environ.pop("AMAP_API_KEY", None)  # 故意不配高德 Key，验证容错分支

from agents._travel import amap  # noqa: E402
from agents._travel.graph import get_graph  # noqa: E402
from agents._travel.tools import TOOLS, geocode_location  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    print(f"{'✅' if condition else '❌'} {name}" + (f" — {detail}" if detail else ""))


def test_tools_registered() -> None:
    names = sorted(t.name for t in TOOLS)
    check("四个工具已注册", len(TOOLS) == 4, ", ".join(names))
    check("工具都有描述", all(t.description for t in TOOLS))


def test_graph_compiled() -> None:
    graph = get_graph()
    nodes = set(graph.get_graph().nodes)
    check("LangGraph 图编译成功", {"agent", "tools"}.issubset(nodes), f"节点: {sorted(nodes)}")
    check("已挂载记忆 checkpointer", graph.checkpointer is not None)


def test_tool_without_key() -> None:
    """没有高德 Key 时，工具应返回结构化的错误说明，而不是抛异常。"""
    out = geocode_location.invoke({"address": "红莲南路地铁站"})
    check("工具缺 Key 时优雅报错", "error" in out and "AMAP_API_KEY" in out, out[:80])
    check("工具返回的是 JSON 字符串", out.startswith("{"))


def test_haversine_fallback() -> None:
    # 天安门(116.397428,39.90923) 与 北京西站(116.322056,39.894915) 直线约 6.8 km
    res = amap.haversine_distance("116.397428,39.90923", "116.322056,39.894915")
    check("距离兜底计算可用", 6000 < res["distance"] < 7600, f"{res['distance']} 米")


async def test_stream_loop() -> None:
    """用假模型跑一遍 ReAct 循环，确认工具节点会被真正执行。"""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.prebuilt import create_react_agent

    from agents._travel import graph as graph_module  # noqa: E402
    from agents._travel.prompts import SYSTEM_PROMPT  # noqa: E402

    class ScriptedModel(BaseChatModel):
        """按脚本出牌的假模型：第一轮调工具，第二轮给结论。"""

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
                            "args": {"address": "红莲南路地铁站"},
                            "id": "call_1",
                        }
                    ],
                )
            else:
                msg = AIMessage(content="已拿到位置，但缺少高德 Key，无法继续检索商场。")
            return ChatResult(generations=[ChatGeneration(message=msg)])

        def bind_tools(self, tools, **kwargs):  # ReAct 需要，这里直接返回自身
            return self

    test_graph = create_react_agent(
        ScriptedModel(), tools=TOOLS, prompt=SYSTEM_PROMPT, checkpointer=InMemorySaver()
    )

    events: list[dict] = []
    config = {"configurable": {"thread_id": "smoke"}, "recursion_limit": 10}
    async for chunk, meta in test_graph.astream(
        {"messages": [("user", "我在红莲南路地铁站附近")]}, config=config, stream_mode="messages"
    ):
        if meta.get("langgraph_node") == "tools":
            events.append({"type": "tool", "name": getattr(chunk, "name", "")})
        elif meta.get("langgraph_node") == "agent" and getattr(chunk, "content", None):
            events.append({"type": "token", "text": str(chunk.content)})

    check("工具节点被真正执行", any(e.get("name") == "geocode_location" for e in events))
    check("最终产出了回复文本", any(e["type"] == "token" for e in events))

    # 复用 graph_module 的事件解析逻辑，验证 _to_text 与流解析可用
    check("文本归一化函数可用", graph_module._to_text(["a", "b"]) == "ab")


def main() -> None:
    print("=" * 52)
    print(" 出行决策 Agent 冒烟测试（无需真实密钥）")
    print("=" * 52)
    test_tools_registered()
    test_graph_compiled()
    test_tool_without_key()
    test_haversine_fallback()
    asyncio.run(test_stream_loop())

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("-" * 52)
    print(f"通过 {passed}/{len(RESULTS)}")
    if passed != len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()

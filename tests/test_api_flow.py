"""接口链路测试：用假模型验证 /api/chat 的事件流协议是否正确。

运行：python tests/test_api_flow.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

os.environ.setdefault("AI_GATEWAY_API_KEY", "sk-smoke-test")
os.environ.pop("AMAP_API_KEY", None)

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402

from agents._travel import graph as graph_module  # noqa: E402
from agents._travel.prompts import SYSTEM_PROMPT  # noqa: E402
from agents._travel.tools import TOOLS  # noqa: E402


class ScriptedModel(BaseChatModel):
    """第一轮调 geocode_location，第二轮输出 Markdown 结论。"""

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
            msg = AIMessage(
                content="### 我的推荐\n\n| 商场 | 距离 |\n| --- | --- |\n| 示例商场 | 1.2 km |"
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self


def main() -> None:
    # 用假模型替换掉真实图，避免依赖任何密钥
    graph_module._graph = create_react_agent(
        ScriptedModel(), tools=TOOLS, prompt=SYSTEM_PROMPT, checkpointer=InMemorySaver()
    )

    from fastapi.testclient import TestClient

    from app import app

    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={"message": "我在红莲南路地铁站附近", "thread_id": "api-test"},
    )
    assert resp.status_code == 200, resp.status_code

    events = [json.loads(line) for line in resp.text.strip().splitlines() if line.strip()]
    types = [e["type"] for e in events]

    print("事件流:", json.dumps(events, ensure_ascii=False)[:300])
    assert "tool" in types, "缺少工具调用事件"
    assert "token" in types, "缺少文本流事件"
    assert events[-1]["type"] == "done", "事件流没有正确结束"
    assert events[0]["label"] == "地点解析", f"工具中文名映射异常: {events[0]}"

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert isinstance(health["llm_ready"], bool)

    print("\n✅ 接口链路测试通过：工具事件 → 文本流 → done")


if __name__ == "__main__":
    main()

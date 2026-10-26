"""出行决策 Agent —— FastAPI 服务入口。

- GET  /              聊天页面
- GET  /api/health    检查环境变量是否就位（不返回任何密钥值）
- POST /api/chat      流式对话，返回 NDJSON 事件流

本地启动：uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents._travel.graph import astream_agent

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="出行决策 Agent", version="1.0.0")


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户输入的出行问题")
    thread_id: str = Field(default="default", description="会话 ID，同一 ID 保留多轮记忆")


@app.get("/api/health")
def health() -> JSONResponse:
    """只返回「有没有配置」，绝不返回密钥内容。"""
    return JSONResponse(
        {
            "status": "ok",
            "llm_ready": bool(os.getenv("AI_GATEWAY_API_KEY")),
            "amap_ready": bool(os.getenv("AMAP_API_KEY")),
            "model": os.getenv("AI_GATEWAY_MODEL", "@makers/deepseek-v4-flash"),
        }
    )


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    async def event_stream():
        async for event in astream_agent(req.message, req.thread_id):
            yield json.dumps(event, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

"""统一的配置读取入口：所有密钥只从环境变量读取，代码里不出现任何明文 Key。"""

from __future__ import annotations

import os

# 让本地 .env 生效（部署到 EdgeOne Makers 时由平台注入环境变量，不会读到此文件）
try:  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 未安装时静默跳过
    pass


DEFAULT_BASE_URL = "https://ai-gateway.edgeone.link/v1"
DEFAULT_MODEL = "@makers/deepseek-v4-flash"


def get_llm_config() -> dict:
    """返回大模型连接配置（OpenAI 兼容协议，因此 LangGraph 可直接复用 langchain-openai）。"""
    api_key = os.getenv("AI_GATEWAY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "缺少 AI_GATEWAY_API_KEY。请到 EdgeOne Makers 控制台 → 模型与密钥 复制，"
            "或填入任意 OpenAI 兼容服务的 Key。"
        )
    return {
        "api_key": api_key,
        "base_url": os.getenv("AI_GATEWAY_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        "model": os.getenv("AI_GATEWAY_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
    }


def get_amap_key() -> str:
    key = os.getenv("AMAP_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "缺少 AMAP_API_KEY。请到高德开放平台控制台创建应用并添加「Web 服务」类型的 Key。"
        )
    return key

"""LangGraph 工具集：把高德能力包装成模型可调用的工具。

每个工具都返回「人话 + 结构化数据」的字符串，并且捕获异常后返回失败说明，
这样模型在工具失败时可以如实告诉用户，而不是崩溃或编造。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from . import amap


def _ok(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _fail(exc: Exception) -> str:
    return json.dumps({"error": str(exc)}, ensure_ascii=False)


@tool
def geocode_location(address: str, city: str = "") -> str:
    """把用户描述的地点转换成经纬度坐标。

    适用场景：用户说「我在红莲南路地铁站附近」「北京西站」这类地名时，
    必须先调用本工具拿到坐标，后续的商场检索和距离计算都依赖它。

    Args:
        address: 地点描述，如「红莲南路地铁站」「西单大悦城」。
        city: 可选的城市名，用于消歧，如「北京」。位置模糊时建议带上。

    Returns:
        包含 location（"经度,纬度"）、formatted_address 的 JSON 字符串。
    """
    try:
        return _ok(amap.geocode(address, city))
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@tool
def search_nearby_malls(location: str, radius: int = 5000) -> str:
    """按经纬度检索周边的商场 / 购物中心，返回候选清单。

    调用前提：location 必须是通过 geocode_location 或上一步工具得到的「经度,纬度」坐标。

    Args:
        location: 中心点坐标，格式 "116.1,39.2"。
        radius: 搜索半径（米），默认 5000，最大 50000。

    Returns:
        商场列表 JSON，每项含 name / address / location / distance(米)。
    """
    try:
        malls = amap.search_malls(location, radius=radius)
        if not malls:
            return _ok({"malls": [], "hint": "该范围内没有检索到商场，可增大 radius 或换个位置。"})
        return _ok({"count": len(malls), "malls": malls})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@tool
def check_brand_in_mall(mall_location: str, brand: str, radius: int = 400) -> str:
    """核对某个商场里（附近）是否存在指定品牌 / 店铺。

    调用前提：mall_location 是商场的坐标，来自 search_nearby_malls 的返回值。

    重要：需要核对多个品牌时，请**在一次调用里用逗号分隔传多个品牌**
    （例如 brand="倍轻松,西屋"），不要拆成多次调用 —— 高德接口有并发上限，
    拆开调用容易被限流。

    Args:
        mall_location: 商场坐标，格式 "116.1,39.2"。
        brand: 品牌名或店铺名；支持逗号分隔的多个品牌，如「倍轻松,西屋」。
        radius: 在商场坐标周边多大范围内查找，默认 400 米。

    Returns:
        JSON：{"mall": 坐标, "results": [{"brand":..., "found": true/false, "stores": [...]}]}
    """
    brands = [b.strip() for b in (brand or "").replace("，", ",").split(",") if b.strip()]
    if not brands:
        return _fail(ValueError("brand 不能为空"))

    try:
        results = []
        for one in brands:
            stores = amap.search_around(mall_location, keywords=one, radius=radius, max_results=5)
            # 过滤掉明显不相关的结果：名称里必须包含品牌关键字的连续片段
            matched = [s for s in stores if one in (s["name"] or "")]
            results.append(
                {
                    "brand": one,
                    "found": bool(matched),
                    "stores": matched[:3],
                    "hint": "" if matched else "未在该商场附近检索到该品牌，可能是没有门店或品牌名不准确。",
                }
            )
        return _ok({"mall": mall_location, "results": results})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@tool
def get_route_distance(origin: str, destination: str, mode: str = "straight") -> str:
    """计算从起点到目标商场的距离，用于比较「哪个更近」。

    Args:
        origin: 起点坐标，格式 "116.1,39.2"（通常是用户位置）。
        destination: 终点坐标，格式 "116.1,39.2"（通常是商场）。
        mode: straight=直线距离（默认，最稳）、drive=驾车、walk=步行。

    Returns:
        JSON：{"distance": 米, "duration": 秒, "mode": ...}
    """
    try:
        return _ok(amap.distance(origin, destination, mode))
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


TOOLS = [
    geocode_location,
    search_nearby_malls,
    check_brand_in_mall,
    get_route_distance,
]

# 工具中文名，用于前端展示「正在调用 xx」
TOOL_LABELS = {
    "geocode_location": "地点解析",
    "search_nearby_malls": "检索附近商场",
    "check_brand_in_mall": "核对品牌门店",
    "get_route_distance": "计算距离",
}

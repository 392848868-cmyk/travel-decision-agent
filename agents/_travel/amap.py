"""高德地图 Web 服务 API 的薄封装。

只做三件事：拼参数、发请求、把返回体裁剪成模型好读的结构。
任何一处失败都抛出可读的中文异常，交给上层工具转成「工具失败说明」。
"""

from __future__ import annotations

import math
from typing import Any

import requests

from .config import get_amap_key

AMAP_BASE = "https://restapi.amap.com"
TIMEOUT = 10

# 高德 POI 类型编码：060101=购物中心，060102=百货商场，060100=商场（父级）
MALL_TYPES = "060100|060101|060102"


def _get(path: str, params: dict[str, Any]) -> dict:
    params = {**params, "key": get_amap_key(), "output": "JSON"}
    try:
        resp = requests.get(f"{AMAP_BASE}{path}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"高德接口网络请求失败：{exc}") from exc

    if str(data.get("status")) != "1":
        raise RuntimeError(
            f"高德接口返回错误：{data.get('info', '未知错误')}（错误码 {data.get('infocode', '-')}）"
        )
    return data


def geocode(address: str, city: str = "") -> dict:
    """结构化地址 → 经纬度。返回 {"location": "116.1,39.2", "formatted_address": "..."}"""
    params: dict[str, Any] = {"address": address}
    if city:
        params["city"] = city
    data = _get("/v3/geocode/geo", params)

    geocodes = data.get("geocodes") or []
    if not geocodes:
        raise RuntimeError(f"地理编码没有匹配结果：{address}（可尝试补充城市名，如「北京·红莲南路地铁站」）")

    first = geocodes[0]
    location = first.get("location", "")
    if not location:
        raise RuntimeError(f"地理编码未返回坐标：{address}")
    return {
        "location": location,
        "formatted_address": first.get("formatted_address", address),
        "city": first.get("city", ""),
        "district": first.get("district", ""),
    }


def search_around(
    location: str,
    keywords: str = "",
    types: str = "",
    radius: int = 3000,
    max_results: int = 20,
) -> list[dict]:
    """周边搜索 POI。location 形如 "116.1,39.2"。"""
    params: dict[str, Any] = {
        "location": location,
        "radius": min(max(radius, 100), 50000),
        "sortrule": "distance",
        "offset": min(max_results, 25),
        "page": 1,
        "extensions": "base",
    }
    if keywords:
        params["keywords"] = keywords
    if types:
        params["types"] = types

    data = _get("/v3/place/around", params)
    pois = data.get("pois") or []

    results = []
    for poi in pois[:max_results]:
        results.append(
            {
                "id": poi.get("id", ""),
                "name": poi.get("name", ""),
                "address": poi.get("address", "") or poi.get("cityname", ""),
                "location": poi.get("location", ""),
                "type": poi.get("type", ""),
                "distance": poi.get("distance", ""),  # 周边搜索自带的直线距离（米）
            }
        )
    return results


def search_malls(location: str, radius: int = 5000, max_results: int = 10) -> list[dict]:
    """按商场类型检索周边商场，并尽量补充关键词检索结果。"""
    malls = search_around(location, types=MALL_TYPES, radius=radius, max_results=max_results)
    if len(malls) < 3:  # 类型编码覆盖不全时用关键词兜底
        extra = search_around(location, keywords="购物中心|商场", radius=radius, max_results=max_results)
        seen = {m["id"] or m["name"] for m in malls}
        for item in extra:
            key = item["id"] or item["name"]
            if key not in seen:
                malls.append(item)
                seen.add(key)
    return malls[:max_results]


def distance(origin: str, destination: str, mode: str = "straight") -> dict:
    """两点间距离。mode: straight=直线距离, drive=驾车导航距离, walk=步行距离。"""
    mode_map = {"straight": "0", "drive": "1", "walk": "3", "bike": "2"}
    if mode not in mode_map:
        raise ValueError(f"不支持的距离模式：{mode}（可选 straight / drive / walk）")

    data = _get(
        "/v3/distance",
        {"origins": origin, "destination": destination, "type": mode_map[mode]},
    )
    results = data.get("results") or []
    if not results:
        raise RuntimeError("距离接口未返回结果")

    first = results[0]
    if str(first.get("distance", "")).strip() in ("", "0") and mode != "straight":
        # 驾车/步行可能因道路数据缺失返回 0，退化为直线距离
        return haversine_distance(origin, destination)

    return {
        "distance": int(float(first.get("distance", 0))),
        "duration": first.get("duration", ""),
        "mode": mode,
    }


def haversine_distance(origin: str, destination: str) -> dict:
    """不依赖接口的球面距离兜底计算（单位：米）。"""
    try:
        lon1, lat1 = (float(v) for v in origin.split(","))
        lon2, lat2 = (float(v) for v in destination.split(","))
    except (ValueError, AttributeError):
        raise RuntimeError(f"坐标格式不正确，应为「经度,纬度」：{origin} / {destination}")

    radius = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return {
        "distance": int(2 * radius * math.asin(math.sqrt(a))),
        "duration": "",
        "mode": "straight(fallback)",
    }

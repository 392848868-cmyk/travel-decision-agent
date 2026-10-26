"""高德地图 Web 服务 API 的薄封装。

只做三件事：拼参数、发请求、把返回体裁剪成模型好读的结构。
任何一处失败都抛出可读的中文异常，交给上层工具转成「工具失败说明」。
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Any

import requests

from .config import get_amap_key

AMAP_BASE = "https://restapi.amap.com"
TIMEOUT = 10

# 高德 POI 类型编码：060101=购物中心，060102=百货商场，060100=商场（父级）
MALL_TYPES = "060100|060101|060102"

# ---------------------------------------------------------------------------
# 限流与重试
# 个人开发者「Web 服务」Key 的并发上限很低（QPS≈3，并发≈3）。
# LangGraph 的 ToolNode 会并发执行多个工具调用，很容易撞上高德的
# 10021（CUQPS_HAS_EXCEEDED_THE_LIMIT 并发超限）。
# 这里做两件事：① 用全局锁把所有高德请求串行化并拉开最小间隔；
#               ② 命中限流错误码时自动退避重试，让模型不必自己反复重试。
# ---------------------------------------------------------------------------
MIN_INTERVAL = 0.35          # 两次请求之间的最小间隔（秒）
RETRYABLE_CODES = {"10021", "10003", "10004", "10008"}  # 限流 / 并发 / 日调用量类
MAX_RETRIES = 4

_RATE_LOCK = threading.Lock()
_LAST_CALL = 0.0
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, dict] = {}


def _throttle() -> None:
    """全局串行节流：保证任意时刻只有一个请求在飞，且间隔不小于 MIN_INTERVAL。"""
    global _LAST_CALL
    with _RATE_LOCK:
        now = time.monotonic()
        wait = _LAST_CALL + MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.monotonic()


def _cache_key(path: str, params: dict[str, Any]) -> str:
    return path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))


def _request(path: str, params: dict[str, Any]) -> dict:
    params = {**params, "key": get_amap_key(), "output": "JSON"}
    try:
        resp = requests.get(f"{AMAP_BASE}{path}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"高德接口网络请求失败：{exc}") from exc


def _get(path: str, params: dict[str, Any]) -> dict:
    """带节流、缓存、限流重试的 GET。"""
    key = _cache_key(path, params)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached

    last_info = ""
    for attempt in range(MAX_RETRIES):
        _throttle()
        data = _request(path, params)
        if str(data.get("status")) == "1":
            with _CACHE_LOCK:
                _CACHE[key] = data
            return data

        info = data.get("info", "未知错误")
        code = str(data.get("infocode", ""))
        last_info = f"高德接口返回错误：{info}（错误码 {code or '-'}）"
        if code in RETRYABLE_CODES and attempt < MAX_RETRIES - 1:
            # 指数退避 + 抖动，避开被限流的窗口
            time.sleep(0.5 * (2**attempt) + random.random() * 0.4)
            continue
        raise RuntimeError(last_info)

    raise RuntimeError(last_info + "，已重试多次仍失败，请稍后再试。")


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


def _dedup(items: list[dict]) -> list[dict]:
    """去掉重复 POI：按 id 去重，坐标也相同的视为同一处（高德常把同一商场登记成两条）。"""
    seen_ids: set[str] = set()
    seen_loc: set[str] = set()
    out: list[dict] = []
    for item in items:
        pid = item.get("id") or ""
        loc = item.get("location") or ""
        if pid and pid in seen_ids:
            continue
        if loc and loc in seen_loc:
            continue
        if pid:
            seen_ids.add(pid)
        if loc:
            seen_loc.add(loc)
        out.append(item)
    return out


def search_malls(location: str, radius: int = 5000, max_results: int = 10) -> list[dict]:
    """按商场类型检索周边商场，并尽量补充关键词检索结果。"""
    malls = search_around(location, types=MALL_TYPES, radius=radius, max_results=max_results)
    if len(malls) < 3:  # 类型编码覆盖不全时用关键词兜底
        extra = search_around(location, keywords="购物中心|商场", radius=radius, max_results=max_results)
        malls = malls + extra
    # 同一商场常被登记成多条记录，去重后再按距离升序
    malls = _dedup(malls)
    malls.sort(key=lambda m: int(m.get("distance") or 0) if str(m.get("distance", "")).isdigit() else 10**9)
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

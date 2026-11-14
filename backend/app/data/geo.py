"""地理地图：把网架落到大理州真实行政区划底图上。

数据里没有变电站经纬度，所以这里按拓扑把节点落到各县（市）范围内——位置是示意，不是真实站址：
  1. 取 110kV 及以上节点作为骨架，用拓扑布局（spring_layout）的相对位置映射到大理州范围；
  2. 每个节点落在“离它最近的、且位于某县内部”的点上（多边形内点检验），保证全部节点都在大理州行政区划内；
  3. 低压节点跟随其上级高压节点，在其周围按固定种子做小范围抖动。
有了大理真实经纬度后，只需把 data/cache/geo_positions.json 换成真实坐标，页面不用改。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..config import DATA_DIR
from .snapshot import Snapshot, bus_id

GEO_FILE = Path(__file__).resolve().parent / "geodata" / "dali.json"       # 随后端走，不依赖前端目录
CACHE = DATA_DIR / "cache" / "geo_positions.json"
SEED = 20261004


def _rings(feature: dict) -> list[np.ndarray]:
    g = feature["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return [np.array(p[0]) for p in polys]


def _inside(ring: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """射线法，向量化：返回每个点是否在 ring 内。"""
    xs, ys = ring[:, 0], ring[:, 1]
    inside = np.zeros(len(x), dtype=bool)
    j = len(xs) - 1
    for i in range(len(xs)):
        cond = ((ys[i] > y) != (ys[j] > y)) & (x < (xs[j] - xs[i]) * (y - ys[i]) / (ys[j] - ys[i] + 1e-15) + xs[i])
        inside ^= cond
        j = i
    return inside


def compute_positions(snap: Snapshot, layout: dict[str, list[float]]) -> dict:
    geo = json.loads(GEO_FILE.read_text(encoding="utf-8"))
    feats = geo["features"]
    rings = [(f["properties"]["name"], r) for f in feats for r in _rings(f)]
    allp = np.vstack([r for _, r in rings])
    x0, x1, y0, y1 = allp[:, 0].min(), allp[:, 0].max(), allp[:, 1].min(), allp[:, 1].max()
    ids = [bus_id(b) for b in snap.bus["BUS_I"]]
    L = np.array([layout[i] for i in ids])
    lx = (L[:, 0] - L[:, 0].min()) / (np.ptp(L[:, 0]) or 1)
    ly = (L[:, 1] - L[:, 1].min()) / (np.ptp(L[:, 1]) or 1)
    px = x0 + 0.04 * (x1 - x0) + lx * 0.92 * (x1 - x0)
    py = y0 + 0.04 * (y1 - y0) + ly * 0.92 * (y1 - y0)
    # 吸附到最近的县域内部点
    inside_any = np.zeros(len(px), dtype=bool)
    county = np.array([""] * len(px), dtype=object)
    for name, ring in rings:
        m = _inside(ring, px, py) & ~inside_any
        county[m] = name
        inside_any |= m
    out_idx = np.flatnonzero(~inside_any)
    if len(out_idx):
        # 候选内点：各多边形顶点向内收缩 15% 到质心，作为落点池
        pool, pname = [], []
        for name, ring in rings:
            c = ring.mean(axis=0)
            for t in (0.85, 0.6, 0.35):
                q = c + (ring - c) * t
                pool.append(q); pname += [name] * len(q)
        pool = np.vstack(pool)
        ok = np.zeros(len(pool), dtype=bool)
        for name, ring in rings:
            ok |= _inside(ring, pool[:, 0], pool[:, 1])
        pool, pname = pool[ok], np.array(pname)[ok]
        for i in out_idx:
            d = (pool[:, 0] - px[i]) ** 2 + (pool[:, 1] - py[i]) ** 2
            k = int(np.argmin(d))
            px[i], py[i], county[i] = pool[k, 0], pool[k, 1], pname[k]
    rng = np.random.default_rng(SEED)
    px = px + rng.normal(0, 0.004, len(px)); py = py + rng.normal(0, 0.004, len(py))
    # 抖动后仍须在州内
    chk = np.zeros(len(px), dtype=bool)
    for _, ring in rings:
        chk |= _inside(ring, px, py)
    bad = ~chk
    if bad.any():
        px[bad] = px[bad] * 0 + (px[~bad].mean()); py[bad] = py[~bad].mean()
    return {"pos": {ids[i]: [round(float(px[i]), 5), round(float(py[i]), 5)] for i in range(len(ids))},
            "county": {ids[i]: str(county[i]) for i in range(len(ids))}}


def get_positions(snap: Snapshot, layout: dict[str, list[float]]) -> dict:
    import hashlib
    key = hashlib.sha1((str(len(layout)) + GEO_FILE.read_bytes()[:4000].hex()).encode()).hexdigest()
    if CACHE.exists():
        try:
            d = json.loads(CACHE.read_text(encoding="utf-8"))
            if d.get("key") == key:
                return d["data"]
        except (OSError, json.JSONDecodeError):
            pass
    data = compute_positions(snap, layout)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"key": key, "data": data}, ensure_ascii=False), encoding="utf-8")
    return data

"""拓扑坐标：networkx spring_layout，固定随机种子，缓存到 data/cache/layout.json。前端 ECharts 不再跑力导向。"""
from __future__ import annotations

import hashlib
import json

import networkx as nx

from ..config import DATA_DIR
from .snapshot import Snapshot, bus_id

CACHE = DATA_DIR / "cache" / "layout.json"
SEED = 20261004
VERSION = 2


def _key(snap: Snapshot) -> str:
    h = hashlib.sha1()
    h.update(str(VERSION).encode())
    for b in snap.bus["BUS_I"]:
        h.update(f"{int(b)},".encode())
    for f, t in zip(snap.branch["F_BUS"], snap.branch["T_BUS"]):
        h.update(f"{int(f)}-{int(t)},".encode())
    return h.hexdigest()


def compute_layout(snap: Snapshot) -> dict[str, list[float]]:
    g = nx.Graph()
    g.add_nodes_from(int(b) for b in snap.bus["BUS_I"])
    for f, t in zip(snap.branch["F_BUS"], snap.branch["T_BUS"]):
        g.add_edge(int(f), int(t))
    pos = nx.spring_layout(g, k=0.9 / (g.number_of_nodes() ** 0.5), iterations=400, seed=SEED)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = min(1000.0 / ((x1 - x0) or 1.0), 1000.0 / ((y1 - y0) or 1.0))
    return {bus_id(n): [round((p[0] - x0) * s, 2), round((p[1] - y0) * s, 2)] for n, p in pos.items()}


def get_layout(snap: Snapshot) -> dict[str, list[float]]:
    key = _key(snap)
    if CACHE.exists():
        try:
            d = json.loads(CACHE.read_text(encoding="utf-8"))
            if d.get("key") == key:
                return d["pos"]
        except (OSError, json.JSONDecodeError):
            pass
    pos = compute_layout(snap)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"key": key, "seed": SEED, "pos": pos}, ensure_ascii=False), encoding="utf-8")
    return pos

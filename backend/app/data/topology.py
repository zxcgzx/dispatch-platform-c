"""拓扑：孤岛型支路识别、可开断集合、停运后的孤岛计算、支路电压等级与类型。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property

import networkx as nx
import numpy as np

from .snapshot import Snapshot, bus_id


@dataclass
class Island:
    buses: list[int]                  # BUS_I 列表
    net_injection_mw: float           # Σ PG(在运机组) − Σ PD；>0 为净注入，<0 为净负荷
    gen_mw: float
    load_mw: float

    @property
    def bus_labels(self) -> list[str]:
        return [bus_id(b) for b in self.buses]


@dataclass
class Topology:
    snap: Snapshot
    in_service: np.ndarray = field(init=False)          # bool[nl]
    kv: np.ndarray = field(init=False)                  # 支路电压等级 = 两端 BASE_KV 较大者
    is_transformer: np.ndarray = field(init=False)
    isolating: np.ndarray = field(init=False)           # 孤岛型：在运、是桥、且无并联
    parallel_group: list[int] = field(init=False)       # 并联组大小（1 = 无并联）

    def __post_init__(self) -> None:
        br = self.snap.branch
        kvmap = self.snap.bus_kv()
        f = br["F_BUS"].to_numpy()
        t = br["T_BUS"].to_numpy()
        self.in_service = br["BR_STATUS"].to_numpy() > 0
        kf = np.array([kvmap.get(int(x), 0.0) for x in f])
        kt = np.array([kvmap.get(int(x), 0.0) for x in t])
        self.kv = np.maximum(kf, kt)
        self.is_transformer = (kf != kt) | (br["TAP"].to_numpy() != 0)
        # 并联：无向端点对相同
        key = [frozenset((int(a), int(b))) for a, b in zip(f, t)]
        cnt = Counter(k for k, s in zip(key, self.in_service) if s)
        self.parallel_group = [cnt.get(k, 1) if s else 1 for k, s in zip(key, self.in_service)]
        # 桥：在运简单图的桥，且该端点对只有一条在运支路
        simple = nx.Graph()
        simple.add_nodes_from(int(b) for b in self.snap.bus["BUS_I"])
        for k, s in zip(key, self.in_service):
            if s and len(k) == 2:
                a, b = tuple(k)
                simple.add_edge(a, b)
        bridges = {frozenset(e) for e in nx.bridges(simple)}
        self.isolating = np.array(
            [bool(s) and cnt.get(k, 0) == 1 and k in bridges for k, s in zip(key, self.in_service)]
        )

    # ---- 集合 ----
    @property
    def meshed(self) -> np.ndarray:
        return self.in_service & ~self.isolating

    def rule_rows(self, rule: str) -> list[int]:
        """规则 -> 支路行号（1 起）。all_in_service / meshed_in_service / meshed_kv_ge_110。"""
        if rule == "all_in_service":
            mask = self.in_service
        elif rule == "meshed_in_service":
            mask = self.meshed
        elif rule == "meshed_kv_ge_110":
            mask = self.meshed & (self.kv >= 110)
        else:
            raise ValueError(f"未知规则：{rule}")
        return [int(i) + 1 for i in np.flatnonzero(mask)]

    def graph(self, exclude_rows: set[int] | None = None) -> nx.MultiGraph:
        exclude_rows = exclude_rows or set()
        g = nx.MultiGraph()
        g.add_nodes_from(int(b) for b in self.snap.bus["BUS_I"])
        br = self.snap.branch
        for i in range(len(br)):
            if self.in_service[i] and (i + 1) not in exclude_rows:
                g.add_edge(int(br.F_BUS.iloc[i]), int(br.T_BUS.iloc[i]), key=i + 1)
        return g

    def is_connected(self) -> bool:
        return nx.is_connected(self.graph())

    def outage_islands(self, outage_rows: set[int]) -> list[Island]:
        """指定支路（行号）停运后，不在主网（含平衡节点）里的孤岛。"""
        if not outage_rows:
            return []
        g = self.graph(exclude_rows=set(outage_rows))
        comps = [set(c) for c in nx.connected_components(g)]
        if len(comps) <= 1:
            return []
        slack = [int(b) for b, ty in zip(self.snap.bus["BUS_I"], self.snap.bus["BUS_TYPE"]) if ty == 3]
        main = next((c for c in comps if slack and slack[0] in c), max(comps, key=len))
        pd_by = dict(zip(self.snap.bus["BUS_I"].astype(int), self.snap.bus["PD"]))
        gen = self.snap.gen
        gen_by: dict[int, float] = {}
        for gb, pg, st in zip(gen["GEN_BUS"], gen["PG"], gen["GEN_STATUS"]):
            if st > 0:
                gen_by[int(gb)] = gen_by.get(int(gb), 0.0) + float(pg)
        out: list[Island] = []
        for c in comps:
            if c is main:
                continue
            load = float(sum(pd_by.get(b, 0.0) for b in c))
            gmw = float(sum(gen_by.get(b, 0.0) for b in c))
            out.append(Island(buses=sorted(c), net_injection_mw=gmw - load, gen_mw=gmw, load_mw=load))
        out.sort(key=lambda x: -len(x.buses))
        return out

    @cached_property
    def isolating_net_load(self) -> dict[int, dict]:
        """每条孤岛型支路单独停运后的孤岛信息（用于 N-1 筛查里的“孤岛事故”统计）。

        孤岛型支路都是桥，一定是任一生成树的树边：以平衡节点为根做一次 DFS，
        桥下方子树就是被孤立的部分，用子树求和一次算完（O(N)）。
        逐条重建图求连通分量要 30 秒以上；结果与 outage_islands 一致（有测试对照）。
        """
        snap, br = self.snap, self.snap.branch
        simple = nx.Graph()
        simple.add_nodes_from(int(b) for b in snap.bus["BUS_I"])
        for i in range(len(br)):
            if self.in_service[i]:
                simple.add_edge(int(br.F_BUS.iloc[i]), int(br.T_BUS.iloc[i]))
        slack = [int(b) for b, ty in zip(snap.bus["BUS_I"], snap.bus["BUS_TYPE"]) if ty == 3]
        root = slack[0] if slack else int(snap.bus["BUS_I"].iloc[0])
        tree = nx.dfs_tree(simple, source=root)
        pd_by = dict(zip(snap.bus["BUS_I"].astype(int), snap.bus["PD"].astype(float)))
        gen_by: dict[int, float] = {}
        for gb, pg, st in zip(snap.gen["GEN_BUS"], snap.gen["PG"], snap.gen["GEN_STATUS"]):
            if st > 0:
                gen_by[int(gb)] = gen_by.get(int(gb), 0.0) + float(pg)
        load = {n: pd_by.get(n, 0.0) for n in tree}
        gen = {n: gen_by.get(n, 0.0) for n in tree}
        cnt = {n: 1 for n in tree}
        parent = {v: u for u, v in tree.edges()}
        for n in reversed(list(nx.dfs_preorder_nodes(tree, root))):
            p = parent.get(n)
            if p is not None:
                load[p] += load[n]
                gen[p] += gen[n]
                cnt[p] += cnt[n]
        res: dict[int, dict] = {}
        for i in np.flatnonzero(self.isolating):
            row = int(i) + 1
            a, b = int(br.F_BUS.iloc[i]), int(br.T_BUS.iloc[i])
            child = b if parent.get(b) == a else a if parent.get(a) == b else None
            if child is None:                                   # 不在树内（图不连通等）：退回逐条计算
                isl = self.outage_islands({row})
                res[row] = {"buses": sum(len(x.buses) for x in isl), "net_injection_mw": float(sum(x.net_injection_mw for x in isl)),
                            "load_mw": float(sum(x.load_mw for x in isl)), "gen_mw": float(sum(x.gen_mw for x in isl))}
                continue
            res[row] = {"buses": cnt[child], "load_mw": load[child], "gen_mw": gen[child], "net_injection_mw": gen[child] - load[child]}
        return res

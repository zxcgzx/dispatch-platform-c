"""问题分解：节点聚合、子任务划分、时空聚合。

- 问题类型识别：由规格里的结构算子推出（OPF / OTS / 含机组启停 / 含断面限额 ……）；
- 分区：按电压层和县域把 905 个节点聚成子区域，统计区域内节点、负荷、机组、联络线，联络线就是子问题之间的耦合；
- 时空聚合：时段方向按 k 个一组合并；节点方向把同一上级高压节点下的低压叶子并入；
- 子任务：每个区域一个子问题，区域边界上的联络线潮流作为协调变量。
不做协同求解本身（多智能体协同待开发）。
"""
from __future__ import annotations

import numpy as np

from ..data.geo import get_positions
from ..data.layout import get_layout
from ..data.library import Window, get_snapshot
from ..data.snapshot import bus_id, branch_id
from ..spec.schema import ModelSpec
from ..modeling.formulas import fixed_topology


def classify(spec: ModelSpec) -> dict:
    ops = {s.op_id for s in spec.structural}
    kinds: list[str] = []
    fixed = fixed_topology(spec)
    kinds.append("AC-OPF（固定拓扑）" if fixed else "AC-OTS（含拓扑重构）")
    if "unit_commitment" in ops:
        kinds.append("含机组启停（混合整数）")
    if "generator_redispatch" in ops:
        kinds.append("含机组出力再调度")
    if spec.omega.n_minus_1:
        kinds.append("含 N−1 安全约束")
    if any(s.kind == "objective" for s in spec.structural):
        kinds.append("多目标叠加")
    return {"types": kinds, "strategy": "按县域分区 + 联络线协调" if not fixed else "按县域分区求解 OPF，联络线潮流协调",
            "reason": "905 节点、1000 支路，其中 775 条一断开就形成孤岛，只有 225 条在网状部分；分区后各子问题规模下降一个量级"}


def partition(window: Window, group_t: int = 4) -> dict:
    snap, topo = get_snapshot(window.snapshot_ids[0])
    layout = get_layout(snap)
    pos = get_positions(snap, layout)
    county = pos["county"]
    ids = [bus_id(b) for b in snap.bus["BUS_I"]]
    names = sorted({county[i] for i in ids})
    pd = dict(zip(ids, snap.bus["PD"].to_numpy(dtype=float)))
    gen_at: dict[str, float] = {}
    for b, pg in zip(snap.gen["GEN_BUS"], snap.gen["PG"]):
        gen_at[bus_id(b)] = gen_at.get(bus_id(b), 0.0) + float(pg)
    regions = {n: {"name": n, "buses": 0, "load_mw": 0.0, "gen_mw": 0.0, "branches_in": 0, "tie_lines": [], "high_voltage_buses": 0} for n in names}
    kv = dict(zip(ids, snap.bus["BASE_KV"].to_numpy(dtype=float)))
    for i in ids:
        r = regions[county[i]]
        r["buses"] += 1
        r["load_mw"] += float(pd[i])
        r["gen_mw"] += float(gen_at.get(i, 0.0))
        r["high_voltage_buses"] += int(kv[i] >= 110)
    ties = 0
    for idx in range(len(snap.branch)):
        a, b = bus_id(snap.branch.F_BUS.iloc[idx]), bus_id(snap.branch.T_BUS.iloc[idx])
        ca, cb = county[a], county[b]
        if ca == cb:
            regions[ca]["branches_in"] += 1
        else:
            ties += 1
            lid = branch_id(idx + 1)
            regions[ca]["tie_lines"].append(lid)
            regions[cb]["tie_lines"].append(lid)
    rows = []
    for n in names:
        r = regions[n]
        rows.append({**r, "load_mw": round(r["load_mw"], 1), "gen_mw": round(r["gen_mw"], 1), "tie_count": len(r["tie_lines"]), "tie_lines": r["tie_lines"][:8]})
    rows.sort(key=lambda x: -x["buses"])
    # 节点聚合：低压叶子并入其高压上级
    deg = np.zeros(len(ids), dtype=int)
    idx_of = {i: k for k, i in enumerate(ids)}
    for idx in range(len(snap.branch)):
        deg[idx_of[bus_id(snap.branch.F_BUS.iloc[idx])]] += 1
        deg[idx_of[bus_id(snap.branch.T_BUS.iloc[idx])]] += 1
    leaves = int(((deg == 1) & (np.array([kv[i] for i in ids]) < 110)).sum())
    T = window.periods
    groups = [list(range(s + 1, min(s + group_t, T) + 1)) for s in range(0, T, group_t)]
    return {
        "regions": rows, "tie_total": ties, "n_regions": len(rows),
        "node_aggregation": {"buses": len(ids), "low_voltage_leaves": leaves, "after": len(ids) - leaves,
                             "note": "度为 1 的 35kV 及以下叶子节点并入其上级节点，负荷与机组按母线合并"},
        "time_aggregation": {"periods": T, "group": group_t, "groups": groups, "after": len(groups),
                             "note": f"每 {group_t} 个时段合并为 1 个决策段"},
        "status": "partition",
    }


def subtasks(window: Window, spec: ModelSpec) -> dict:
    p = partition(window)
    cls = classify(spec)
    return {"classify": cls, "partition": p,
            "subtasks": [{"id": f"sub-{i + 1}", "region": r["name"], "buses": r["buses"], "coupling": r["tie_count"],
                          "scale_ratio": round(r["buses"] / sum(x["buses"] for x in p["regions"]), 3)} for i, r in enumerate(p["regions"])]}

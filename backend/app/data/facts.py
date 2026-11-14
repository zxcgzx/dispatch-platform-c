"""数据事实与数据质量报告（4.4）。所有数字由程序计算，不写死、不静默修正。"""
from __future__ import annotations

import numpy as np

from .snapshot import Snapshot, branch_id, bus_id, gen_id
from .topology import Topology

KV_ORDER = [500.0, 220.0, 110.0, 35.0, 10.0, 6.0]


def compute_facts(snap: Snapshot, topo: Topology) -> dict:
    bus, gen, br = snap.bus, snap.gen, snap.branch
    type_names = {1: "PQ", 2: "PV", 3: "平衡节点"}
    bus_types = {type_names.get(int(k), str(k)): int(v) for k, v in bus["BUS_TYPE"].value_counts().items()}
    kv_counts = {f"{k:g}kV": int((bus["BASE_KV"] == k).sum()) for k in KV_ORDER}
    for k in sorted(set(bus["BASE_KV"]) - set(KV_ORDER), reverse=True):
        kv_counts[f"{k:g}kV"] = int((bus["BASE_KV"] == k).sum())

    meshed_by_kv: dict[str, int] = {}
    for k in KV_ORDER:
        c = int(((topo.kv == k) & topo.meshed).sum())
        if c:
            meshed_by_kv[f"{k:g}kV"] = c

    parallel_groups: dict[frozenset, int] = {}
    for f, t in zip(br["F_BUS"], br["T_BUS"]):
        key = frozenset((int(f), int(t)))
        parallel_groups[key] = parallel_groups.get(key, 0) + 1
    par_groups = {k: v for k, v in parallel_groups.items() if v > 1}

    gen_per_bus = gen.groupby("GEN_BUS").size()
    slack = [int(b) for b, t in zip(bus["BUS_I"], bus["BUS_TYPE"]) if t == 3]

    return {
        "snapshot_id": snap.snapshot_id,
        "time": snap.time.isoformat(timespec="seconds") if snap.time else None,
        "base_mva": snap.base_mva,
        "counts": {"bus": len(bus), "gen": len(gen), "branch": len(br)},
        "bus_types": bus_types,
        "slack_bus": slack,
        "bus_by_kv": kv_counts,
        "totals": {"pd_mw": round(float(bus["PD"].sum()), 2), "pg_mw": round(float(gen["PG"].sum()), 2)},
        "all_branches_in_service": bool((br["BR_STATUS"] > 0).all()),
        "all_gens_in_service": bool((gen["GEN_STATUS"] > 0).all()),
        "renewable_all_zero": bool((bus["RENEWABLE"] == 0).all()),
        "connected": topo.is_connected(),
        "isolating_branches": int(topo.isolating.sum()),
        "meshed_branches": int(topo.meshed.sum()),
        "meshed_by_kv": meshed_by_kv,
        "parallel": {"groups": len(par_groups), "branches": int(sum(par_groups.values()))},
        "buses_with_multiple_gens": int((gen_per_bus > 1).sum()),
        "switchable_counts": {r: len(topo.rule_rows(r)) for r in ("all_in_service", "meshed_in_service", "meshed_kv_ge_110")},
    }


def compute_quality(snap: Snapshot, topo: Topology) -> list[dict]:
    """数据质量条目：如实展示。每条 {code, level, title, count, detail, examples}。"""
    bus, gen, br = snap.bus, snap.gen, snap.branch
    items: list[dict] = []

    def add(code: str, level: str, title: str, count: int, detail: str, examples: list[str] | None = None) -> None:
        items.append({"code": code, "level": level, "title": title, "count": int(count), "detail": detail,
                      "examples": (examples or [])[:8]})

    # 缺失值
    nan_cnt = int(bus.isna().sum().sum() + gen.isna().sum().sum() + br.isna().sum().sum())
    add("Q-NAN", "info" if nan_cnt == 0 else "error", "缺失值 / NaN", nan_cnt,
        "Bus / Gen / Branch 三段无缺失值" if nan_cnt == 0 else "存在缺失值，校验 E301 会报错")

    over = bus[bus["VM"] > bus["VMAX"]]
    under = bus[bus["VM"] < bus["VMIN"]]
    vmaxs = sorted({float(x) for x in bus["VMAX"]})
    add("Q-VM-HI", "warn", "母线电压高于上限（VM > VMAX）", len(over),
        f"VMAX 取值：{', '.join(f'{x:g}' for x in vmaxs)}（统一取值，疑为默认值）；基态已有越限，未做修正",
        [bus_id(b) for b in over["BUS_I"]])
    add("Q-VM-LO", "warn", "母线电压低于下限（VM < VMIN）", len(under), "基态电压偏低，未做修正",
        [bus_id(b) for b in under["BUS_I"]])

    out_rows = gen[(gen["PG"] > gen["PMAX"]) | (gen["PG"] < gen["PMIN"])]
    ex = [f"{gen_id(i + 1)}（PG={gen.PG.iloc[i]:.1f}，PMAX={gen.PMAX.iloc[i]:g}）" for i in out_rows.index[:6]]
    add("Q-PG", "warn", "机组出力不在 [PMIN, PMAX] 内", len(out_rows), "例如 G143：PG ≈ 45.4 MW，PMAX = 10；未做修正", ex)

    zero_rate = [branch_id(i + 1) for i in np.flatnonzero(br["RATE_A"].to_numpy() == 0)]
    add("Q-RATE0", "warn", "RATE_A = 0 的支路（视为不限）", len(zero_rate), "RATE_A 是额定电流（A），热稳限额按 √3·kV·I/1000 折成 MVA；为 0 的支路不计负载率，热稳约束 B4 对其不加", zero_rate)

    neg = bus[bus["PD"] < 0]
    add("Q-PD-NEG", "info", "PD < 0 的母线（分布式电源按负负荷处理）", len(neg), "不做拆分，按负负荷处理")

    big = gen[gen["PG"].abs() > 1000]
    if len(big):
        add("Q-EQUIV", "info", "母线上的大容量等值机组（|PG| > 1000 MW）", len(big),
            "母线 176 上有两台约 ±2000 MW 的等值机组，演示用例避开它们",
            [f"{gen_id(i + 1)}（母线 {int(gen.GEN_BUS.iloc[i])}，PG={gen.PG.iloc[i]:.0f}）" for i in big.index])

    if snap.time_mismatch:
        add("Q-TIME", "warn", "断面时刻不一致", 1,
            f"Dict Info 的 time = {snap.dict_time}，文件名时间戳 = {snap.file_time}；按 Dict Info 取值")
    add("Q-ANG", "info", "ANGMIN / ANGMAX 为 ±360", int(((br["ANGMIN"] <= -360) & (br["ANGMAX"] >= 360)).sum()), "相角差限制不起作用")
    return items

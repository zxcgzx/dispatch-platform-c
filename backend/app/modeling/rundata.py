"""运行数据：把 16 个时段的断面整理成建模用的字典（生成代码的 build_model(data, spec) 的 data）。

约定：
- 每个对象的时变量是长度 T 的列表（下标 t-1），Δπ 只改这些列表的指定时段；
- 集合（可开断集合、事故集）按第 1 个时段的断面拓扑取（假设拓扑在 4 小时窗口内不变，见 ASSUMPTIONS）。
"""
from __future__ import annotations

import copy
from typing import Any

from ..data.library import Window, get_snapshot
from ..data.snapshot import Snapshot, branch_id, bus_id, gen_id
from ..spec.schema import DeltaPi

RULES = ("all_in_service", "meshed_in_service", "meshed_kv_ge_110")


def _cols(snap: Snapshot) -> dict[str, dict[str, list]]:
    """一个断面的列式数据（只展开一次）。"""
    b, g, r = snap.bus, snap.gen, snap.branch
    return {
        "bus": {c: b[c].tolist() for c in ("PD", "QD", "VMAX", "VMIN")},
        "gen": {c: g[c].tolist() for c in ("PMAX", "PMIN", "QMAX", "QMIN", "GEN_STATUS")},
        "branch": {c: r[c].tolist() for c in ("RATE_A", "BR_STATUS")},
    }


def build_data(window: Window, T: int | None = None) -> dict[str, Any]:
    T = min(T or window.periods, len(window.snapshot_ids))     # 时段数 = 断面数，二者不会不一致
    ids = window.snapshot_ids[:T]
    uniq = {sid: _cols(get_snapshot(sid)[0]) for sid in dict.fromkeys(ids)}
    s0, topo = get_snapshot(ids[0])
    base = s0.base_mva

    def series(kind: str, col: str, idx: int, conv=float) -> list:
        return [conv(uniq[sid][kind][col][idx]) for sid in ids]

    bus: dict[str, dict] = {}
    for idx in range(len(s0.bus)):
        bid = bus_id(s0.bus["BUS_I"].iloc[idx])
        bus[bid] = {
            "i": int(s0.bus["BUS_I"].iloc[idx]), "kv": float(s0.bus.BASE_KV.iloc[idx]), "type": int(s0.bus.BUS_TYPE.iloc[idx]),
            "pd": series("bus", "PD", idx), "qd": series("bus", "QD", idx),
            "gs": float(s0.bus.GS.iloc[idx]), "bs": float(s0.bus.BS.iloc[idx]),
            "vmax": series("bus", "VMAX", idx), "vmin": series("bus", "VMIN", idx),
            "vm0": float(s0.bus.VM.iloc[idx]), "va0": float(s0.bus.VA.iloc[idx]),
        }
    gen: dict[str, dict] = {}
    for idx in range(len(s0.gen)):
        gen[gen_id(idx + 1)] = {
            "bus": bus_id(int(s0.gen.GEN_BUS.iloc[idx])),
            "pmax": series("gen", "PMAX", idx), "pmin": series("gen", "PMIN", idx),
            "qmax": series("gen", "QMAX", idx), "qmin": series("gen", "QMIN", idx),
            "status": series("gen", "GEN_STATUS", idx, lambda x: int(x > 0)),
            "pg0": float(s0.gen.PG.iloc[idx]), "qg0": float(s0.gen.QG.iloc[idx]),
        }
    branch: dict[str, dict] = {}
    for idx in range(len(s0.branch)):
        r0 = s0.branch.iloc[idx]
        branch[branch_id(idx + 1)] = {
            "f": bus_id(int(r0.F_BUS)), "t": bus_id(int(r0.T_BUS)),
            "r": float(r0.BR_R), "x": float(r0.BR_X), "b": float(r0.BR_B),
            "tap": float(r0.TAP), "shift": float(r0.SHIFT),
            "rate": series("branch", "RATE_A", idx), "status": series("branch", "BR_STATUS", idx, lambda x: int(x > 0)),
            "pf0": float(r0.PF), "qf0": float(r0.QF), "pt0": float(r0.PT), "qt0": float(r0.QT),
        }
    slack = next((bus_id(int(b)) for b, t in zip(s0.bus["BUS_I"], s0.bus["BUS_TYPE"]) if t == 3), next(iter(bus)))
    rules = {r: [branch_id(x) for x in topo.rule_rows(r)] for r in RULES}
    return {"T": T, "base_mva": base, "slack": slack, "bus": bus, "gen": gen, "branch": branch,
            "switchable": rules, "contingency": rules}


_data_cache: dict[tuple, dict[str, Any]] = {}


def get_data(window: Window, T: int | None = None) -> dict[str, Any]:
    """带缓存的运行数据（只读使用；要改请 copy.deepcopy）。缓存键含断面文件修改时间，文件被替换后自动失效。"""
    from ..config import settings

    T = min(T or window.periods, len(window.snapshot_ids))
    ids = window.snapshot_ids[:T]
    stamp = tuple(f"{sid}@{(settings.snapshot_dir / (sid + '.txt')).stat().st_mtime_ns}" for sid in ids)
    key = (stamp, T)
    if key not in _data_cache:
        if len(_data_cache) >= 6:
            _data_cache.pop(next(iter(_data_cache)))
        _data_cache[key] = build_data(window, T)
    return _data_cache[key]


def period_list(dp_periods: list[int], T: int) -> list[int]:
    """Δπ 的时段（空 = 全部）截到 1..T。"""
    ps = dp_periods or list(range(1, T + 1))
    return [t for t in ps if 1 <= t <= T]


_FIELD = {
    ("bus", "PD"): ("bus", "pd"), ("bus", "QD"): ("bus", "qd"), ("bus", "VMAX"): ("bus", "vmax"), ("bus", "VMIN"): ("bus", "vmin"),
    ("gen", "PMAX"): ("gen", "pmax"), ("gen", "PMIN"): ("gen", "pmin"), ("gen", "GEN_STATUS"): ("gen", "status"),
    ("branch", "RATE_A"): ("branch", "rate"), ("branch", "BR_STATUS"): ("branch", "status"),
}
FIELD_OF = _FIELD


def effective_op(dp: DeltaPi) -> tuple[str, float] | None:
    """Δπ 的实际操作。推断项：确认后有 value 才生效（operation 缺省按 scale）；未确认返回 None。"""
    if dp.source == "explicit":
        return (dp.operation, float(dp.value)) if dp.operation and dp.value is not None else None
    if dp.value is None or not dp.confirmed:
        return None
    return (dp.operation or "scale", float(dp.value))


def apply_delta_pi(D: dict[str, Any], dps: list[DeltaPi]) -> tuple[dict[str, Any], set[str]]:
    """把 Δπ 应用到数据副本，返回 (新数据, 停运支路集合)。与生成代码里的 _dp 语义一致。"""
    D = copy.deepcopy(D)
    T = D["T"]
    out_branches: set[str] = set()
    for dp in dps:
        key = _FIELD.get((dp.component, dp.param))
        op = effective_op(dp)
        if key is None or op is None or dp.target not in D[key[0]]:
            continue
        arr = D[key[0]][dp.target][key[1]]
        o, v = op
        for t in period_list(dp.periods, T):
            if o == "scale":
                arr[t - 1] *= v
            elif o == "set":
                arr[t - 1] = int(v) if dp.param in ("BR_STATUS", "GEN_STATUS") else v
            elif o == "add":
                arr[t - 1] += v
        if dp.param == "BR_STATUS" and op == ("set", 0.0):
            out_branches.add(dp.target)
    return D, out_branches

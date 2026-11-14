"""内置求解器：直流近似的最优拓扑重构（DC-OTS）混合整数线性规划，用 HiGHS（scipy.optimize.milp）求解。

用途：让“指令 → 规格 → 求解 → 结果 → 指标”这条流程在没有外部求解链时也能真实跑通。
它按规格（Δπ、结构算子、ω）建模，输出和外部求解链同一份结果 JSON：开断方案、机组出力、线路潮流、母线电压（直流近似下取标幺 1.0）。

模型（对每个时段 t，按断面逐时段取数）：
  变量：θ_{i,t}、P^G_{g,t}、P_{l,t}、0-1 变量 z_{l,t}（仅可开断集合）、|P^G − P^{G,0}| 辅助变量
  约束：节点有功平衡；支路潮流 |P| ≤ z·RATE_A；开断支路用 Big-M 与 b·(θ_f − θ_t) 耦合；机组出力上下限；平衡节点 θ = 0；
        Δπ 的修改（停运、限额、负荷、机组出力）；结构算子（每时段 / 全部时段开关次数上限、断面限额）；
        N−1：按所选事故集做直流筛查（见 metrics.indicators），不展开进求解
  目标：Σ|P^G − P^{G,0}|（偏离当前方式最小）+ 开关动作惩罚 β·Σ|z_t − z_{t−1}|（有该算子时）+ 网损 / 电压偏差项（直流近似下为 0，注明）
这是直流近似，不是交流 AC-OTS；不做任何求解加速、热启动、调参。
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import scipy.sparse as sp
from scipy.optimize import Bounds, LinearConstraint, milp

from ..config import app_config
from ..data.library import Window, get_snapshot
from ..data.snapshot import branch_id, gen_id
from ..modeling import operators as ops
from ..modeling.rundata import apply_delta_pi, get_data
from ..spec.schema import ModelSpec

BIG_UNLIMITED = 20.0   # p.u.，RATE_A = 0 视为不限


def solve_spec(spec: ModelSpec, window: Window, time_limit: float | None = None) -> dict[str, Any]:
    t_all = time.perf_counter()
    T = window.periods
    snap, topo = get_snapshot(window.snapshot_ids[0])
    t0 = time.perf_counter()
    D0 = get_data(window)
    D, outage = apply_delta_pi(D0, spec.delta_pi)
    base = D["base_mva"]
    bus_ids = list(D["bus"])
    gen_ids = list(D["gen"])
    br_ids = list(D["branch"])
    nb, ng, nl = len(bus_ids), len(gen_ids), len(br_ids)
    bidx = {b: i for i, b in enumerate(bus_ids)}
    f = np.array([bidx[D["branch"][l]["f"]] for l in br_ids])
    t_ = np.array([bidx[D["branch"][l]["t"]] for l in br_ids])
    tap = np.array([D["branch"][l]["tap"] for l in br_ids])
    x = np.array([D["branch"][l]["x"] for l in br_ids])
    bsus = 1.0 / (x * np.where(tap == 0, 1.0, tap))            # MATPOWER 直流模型 b = 1/(x·τ)
    gb = np.array([bidx[D["gen"][g]["bus"]] for g in gen_ids])
    slack = bidx[D["slack"]]
    read_s = time.perf_counter() - t0

    fixed = spec.omega.problem == "multi_period_acopf" or any(s.op_id == "multi_period_acopf" for s in spec.structural)
    sw_ids = [] if fixed else [l for l in D["switchable"][spec.omega.switchable_rule] if l not in outage]
    sw_idx = {br_ids.index(l): k for k, l in enumerate(sw_ids)}
    ns = len(sw_ids)

    # ---- 变量编号（逐时段分块）：θ(nb) | pg(ng) | p(nl) | z(ns) | d(ng) | dz(ns)
    per = nb + ng + nl + ns + ng + ns
    N = per * T
    def ix(t: int, kind: str, k: int = 0) -> int:
        o = t * per
        return o + {"th": 0, "pg": nb, "p": nb + ng, "z": nb + ng + nl, "d": nb + ng + nl + ns, "dz": nb + ng + nl + ns + ng}[kind] + k

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    lo: list[float] = []
    hi: list[float] = []
    nrow = [0]

    def row(entries: list[tuple[int, float]], l: float, h: float) -> None:
        for c, v in entries:
            rows.append(nrow[0]); cols.append(c); vals.append(v)
        lo.append(l); hi.append(h); nrow[0] += 1

    lb = np.full(N, -np.inf)
    ub = np.full(N, np.inf)
    integ = np.zeros(N)
    cost = np.zeros(N)
    beta = None
    for s in spec.structural:
        if s.op_id == "switching_penalty":
            beta = float(ops.effective_params(s.op_id, s.params)["beta"])
    pg0 = np.array([D["gen"][g]["pg0"] for g in gen_ids]) / base
    sw_state0 = {l: D["branch"][l]["status"][0] for l in sw_ids}

    # 断面里未建模的等值注入与网损：c_i = PG⁰_i − PD⁰_i − 无损净流出_i（无损流取首末端有功的平均）。
    # 直流模型是无损的，而断面总出力比总负荷多 679 MW（网损 105 MW，其余是等值机组 / 平衡节点的等值注入）；
    # 把这部分按断面固定，断面本身就是模型的可行点，小改动只会引起小调整，而不是一次 660 MW 的虚假再调度。
    pbar = (snap.branch["PF"].to_numpy(dtype=float) - snap.branch["PT"].to_numpy(dtype=float)) / 2.0 / base
    net_out = np.zeros(nb)
    np.add.at(net_out, f, pbar)
    np.add.at(net_out, t_, -pbar)
    pd0 = np.array([snap.bus["PD"].iloc[bidx_snap] for bidx_snap in range(nb)]) / base
    gen_inj0 = np.zeros(nb)
    np.add.at(gen_inj0, gb, pg0)
    comp = gen_inj0 - pd0 - net_out                                  # 固定补偿（p.u.）
    for t in range(T):
        pd_t = np.array([D["bus"][b]["pd"][t] for b in bus_ids]) / base
        # 节点平衡：Σ pg − pd − 补偿 = Σ_out p − Σ_in p
        bal: list[list[tuple[int, float]]] = [[] for _ in range(nb)]
        for k in range(ng):
            bal[gb[k]].append((ix(t, "pg", k), 1.0))
        for l in range(nl):
            bal[f[l]].append((ix(t, "p", l), -1.0))
            bal[t_[l]].append((ix(t, "p", l), 1.0))
        for i in range(nb):
            row(bal[i], pd_t[i] + comp[i], pd_t[i] + comp[i])
        for i in range(nb):
            lb[ix(t, "th", i)], ub[ix(t, "th", i)] = -1.2, 1.2
        lb[ix(t, "th", slack)] = ub[ix(t, "th", slack)] = 0.0
        for k, g in enumerate(gen_ids):
            on = D["gen"][g]["status"][t]
            pmin = D["gen"][g]["pmin"][t] / base * on
            pmax = D["gen"][g]["pmax"][t] / base * on
            # 断面里 PG 本身越界的机组（数据质量问题）：只在用户没改它的上下限时，把当前出力纳入可行域，避免无谓无解；
            # 用户用 Δπ 改了 PMAX / PMIN 的机组，按用户设定严格执行
            if D["gen"][g]["pmax"][t] == D0["gen"][g]["pmax"][t]:
                pmax = max(pmax, pg0[k] * on)
            if D["gen"][g]["pmin"][t] == D0["gen"][g]["pmin"][t]:
                pmin = min(pmin, pg0[k] * on)
            lb[ix(t, "pg", k)], ub[ix(t, "pg", k)] = pmin, pmax
            lb[ix(t, "d", k)], ub[ix(t, "d", k)] = 0.0, 100.0
            cost[ix(t, "d", k)] = 1.0
            row([(ix(t, "d", k), 1.0), (ix(t, "pg", k), -1.0)], -pg0[k], np.inf)
            row([(ix(t, "d", k), 1.0), (ix(t, "pg", k), 1.0)], pg0[k], np.inf)
        for l in range(nl):
            lid = br_ids[l]
            on = D["branch"][lid]["status"][t] if lid not in outage else 0
            rt = D["branch"][lid]["rate"][t] / base
            R = rt if rt > 0 else BIG_UNLIMITED
            p = ix(t, "p", l)
            if on == 0:
                lb[p] = ub[p] = 0.0
                continue
            lb[p], ub[p] = -R, R
            if l in sw_idx:
                z = ix(t, "z", sw_idx[l])
                integ[z] = 1; lb[z], ub[z] = 0.0, 1.0
                row([(p, 1.0), (z, -R)], -np.inf, 0.0)
                row([(p, 1.0), (z, R)], 0.0, np.inf)
                big = max(bsus[l] * 2.4, R * 1.5)
                e = [(p, 1.0), (ix(t, "th", f[l]), -bsus[l]), (ix(t, "th", t_[l]), bsus[l])]
                row(e + [(z, big)], -np.inf, big)
                row(e + [(z, -big)], -big, np.inf)
            else:
                row([(p, 1.0), (ix(t, "th", f[l]), -bsus[l]), (ix(t, "th", t_[l]), bsus[l])], 0.0, 0.0)
        # 开关动作 dz ≥ |z_t − z_{t−1}|
        for k, l in enumerate(sw_ids):
            z, dz = ix(t, "z", k), ix(t, "dz", k)
            lb[dz], ub[dz] = 0.0, 1.0
            c0 = float(sw_state0[l])
            if t == 0:
                row([(dz, 1.0), (z, -1.0)], -c0, np.inf)
                row([(dz, 1.0), (z, 1.0)], c0, np.inf)
            else:
                zp = ix(t - 1, "z", k)
                row([(dz, 1.0), (z, -1.0), (zp, 1.0)], 0.0, np.inf)
                row([(dz, 1.0), (z, 1.0), (zp, -1.0)], 0.0, np.inf)
            if beta is not None:
                cost[dz] += beta
            else:
                cost[dz] += 1e-3          # 基础模型里的极小惩罚，避免无谓开断
    # ---- 结构算子
    msgs: list[str] = []
    for s in spec.structural:
        p = ops.effective_params(s.op_id, s.params)
        if s.op_id == "switching_limit_per_period" and ns:
            for t in range(T):
                row([(ix(t, "dz", k), 1.0) for k in range(ns)], -np.inf, float(p["k"]))
        elif s.op_id == "switching_limit_total" and ns:
            row([(ix(t, "dz", k), 1.0) for t in range(T) for k in range(ns)], -np.inf, float(p["K"]))
        elif s.op_id == "section_limit":
            idxs = [br_ids.index(b) for b in (p.get("branches") or []) if b in br_ids]
            lim = float(p["limit_mw"]) / base
            sign = {"forward": 1.0, "reverse": -1.0}.get(p.get("direction", "forward"), 1.0)
            for t in range(T):
                e = [(ix(t, "p", l), sign) for l in idxs]
                if p.get("direction") == "abs":
                    row(e, -lim, lim)
                else:
                    row(e, -np.inf, lim)
        elif s.op_id in ("loss_min", "voltage_deviation"):
            msgs.append(f"{s.op_id}：直流近似下网损与电压偏差为 0，该目标项在本求解器中不起作用；需要交流求解链才有意义。")
        elif s.op_id not in ops.operators():
            msgs.append(f"{s.id}（{s.op_id}）是自定义算子，内置求解器不执行。")
    if sw_ids == [] and not fixed:
        msgs.append("可开断集合为空，按固定拓扑求解。")
    A = sp.csr_matrix((vals, (rows, cols)), shape=(nrow[0], N))
    build_s = time.perf_counter() - t_all - read_s

    tl = float(time_limit if time_limit is not None else spec.solver_req.time_limit_s)
    t1 = time.perf_counter()
    res = milp(cost, constraints=LinearConstraint(A, lo, hi), integrality=integ, bounds=Bounds(lb, ub),
               options={"time_limit": tl, "mip_rel_gap": 1e-6})
    solve_s = time.perf_counter() - t1
    status = {0: "optimal", 1: "feasible", 2: "infeasible", 3: "error", 4: "error"}.get(res.status, "error")
    if res.status == 1 and res.x is not None:
        status = "feasible"
    out: dict[str, Any] = {
        "status": status, "solver": "HiGHS（直流近似 DC-OTS）", "objective": float(res.fun) if res.fun is not None else None,
        "periods": T, "timings_s": {"read": round(read_s, 3), "build": round(build_s, 3), "solve": round(solve_s, 3), "n1_check": None},
        "messages": msgs + [f"规模：变量 {N:,}（其中 0-1 变量 {int(integ.sum()):,}），约束 {nrow[0]:,}"],
    }
    if res.x is None:
        out["messages"].insert(0, "没有找到可行方案：约束互相冲突（例如限额过紧、停运造成孤岛或断面限额小于必要潮流）。")
        return out
    X = res.x
    bs: dict[str, list[int]] = {}
    for k, l in enumerate(sw_ids):
        arr = [int(round(X[ix(t, "z", k)])) for t in range(T)]
        if any(a == 0 for a in arr) or arr[0] != sw_state0[l]:
            bs[l] = arr
    for l in outage:
        bs[l] = [0] * T
    for l in br_ids:                                   # Δπ 里按时段停运的支路也要进方案
        st = D["branch"][l]["status"]
        if any(v == 0 for v in st) and l not in bs:
            bs[l] = [int(v) for v in st]
    gp = {g: [round(float(X[ix(t, "pg", k)] * base), 4) for t in range(T)] for k, g in enumerate(gen_ids)}
    changed = {g: v for g, v in gp.items() if max(abs(v[t] - D["gen"][g]["pg0"]) for t in range(T)) > 1e-3}
    flow = {}
    for l, lid in enumerate(br_ids):
        pv = [float(X[ix(t, "p", l)] * base) for t in range(T)]
        if D["branch"][lid]["rate"][0] > 0 or any(abs(v) > 1e-6 for v in pv):
            flow[lid] = {"pf": [round(v, 4) for v in pv], "qf": [0.0] * T, "pt": [round(-v, 4) for v in pv], "qt": [0.0] * T}
    out.update({
        "branch_status": bs, "gen_p": changed if changed else {}, "gen_p_all": None,
        "bus_vm": {}, "branch_flow": flow,
    })
    out["messages"].append("直流近似：只求有功，不输出母线电压；负载率按有功潮流 / RATE_A 计算。")
    out.pop("gen_p_all")
    return out

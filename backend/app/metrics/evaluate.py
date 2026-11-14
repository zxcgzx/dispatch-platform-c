"""评估一个版本：调整前（断面真实数据）与调整后（求解结果；mock 时为 None）的指标，加课题 3 风险与协商建议。"""
from __future__ import annotations

import numpy as np

from ..data.library import Window, get_snapshot
from ..data.snapshot import branch_id
from ..modeling.rundata import apply_delta_pi, get_data
from ..spec.schema import ModelSpec
from . import indicators as ind
from . import risk as risk_mod


def _summary(res: dict | None) -> dict:
    if not res:
        return {"has_result": False}
    return {"has_result": res["status"] != "mock", "status": res["status"], "solver": res.get("solver"), "objective": res.get("objective"),
            "n_branch_changed": len(res.get("branch_status") or {}), "n_gens": len(res.get("gen_p") or {})}


def evaluate(task_id: str, version: int, spec: ModelSpec, window: Window, result: dict | None) -> dict:
    snap, topo = get_snapshot(window.snapshot_ids[0])
    # ---- 调整前：断面真实数据
    before_rho = ind.branch_loading(snap)
    before = {
        "load_rate": ind.load_rate_metrics(before_rho, snap, topo),
        "voltage": ind.voltage_metrics(snap),
        "n1": ind.n1_screening(snap, topo, rule=spec.omega.contingency_rule),
    }
    # ---- 调整后：求解结果；mock / 没有结果 → None（界面显示“—”）
    after = None
    after_note = "未求解（mock 黑盒占位）：调整后指标显示“—”" if (not result or result["status"] == "mock") else None
    if result and result["status"] in ("optimal", "feasible"):
        after = _after(spec, window, snap, topo, result)
    elif result and result["status"] in ("infeasible", "error"):
        after_note = f"求解状态 {result['status']}：没有可用于评估的方案"
    metrics = {"before": before, "after": after, "after_note": after_note, "contingency_rule": spec.omega.contingency_rule,
               "unimplemented": {"vsm": "待开发：静态电压稳定裕度需要连续潮流", "renewable": "暂不计算：数据中没有新能源机组信息（RENEWABLE 全为 0）"}}
    basis = dict(after) if after is not None else before
    skipped: list[str] = []
    if after is not None:
        if basis.get("load_rate") is None:
            basis["load_rate"] = before["load_rate"]
            skipped.append("负载率沿用断面（结果里没有线路潮流）")
        if basis.get("voltage") is None:                # 直流近似不求电压：电压不参与调整后风险判断
            basis["voltage"] = None
            skipped.append("直流近似不求母线电压，电压不参与本次风险判断")
    risk = risk_mod.assess(task_id, version, {"load_rate": basis["load_rate"], "voltage": basis["voltage"], "n1": basis["n1"]}, _summary(result))
    risk["based_on"] = ("调整后（求解结果）" + ("；" + "；".join(skipped) if skipped else "")) if after is not None else "调整前（断面真实数据）"
    sug = risk_mod.suggestions(risk, {"load_rate": basis["load_rate"], "voltage": basis["voltage"], "n1": basis["n1"]}, spec.model_dump())
    return {"metrics": metrics, "risk": risk, "suggestions": sug}


def _after(spec: ModelSpec, window: Window, snap, topo, result: dict) -> dict:
    """调整后指标：拓扑 / 限额取 Δπ 与求解结果，潮流取求解结果。"""
    T = window.periods
    D, outage = apply_delta_pi(get_data(window), spec.delta_pi)
    # 取各时段指标的最坏值（负载率取每条支路的时段最大；N−1 取最差时段）
    status = {k: v for k, v in (result.get("branch_status") or {}).items()}
    flows = result.get("branch_flow") or {}
    nl = len(snap.branch)
    ids = snap.branch_ids
    rho_t: list[np.ndarray] = []
    n1_t: list[dict] = []
    for t in range(T):
        in_service = topo.in_service.copy()
        rate = np.array([D["branch"][b]["rate"][t] for b in ids], dtype=float)
        for i, b in enumerate(ids):
            if D["branch"][b]["status"][t] == 0:
                in_service[i] = False
            if b in status:
                in_service[i] = bool(status[b][t])
        fl = {b: {k: f[k][t] for k in ("pf", "qf", "pt", "qt")} for b, f in flows.items() if all(f.get(k) for k in ("pf", "qf", "pt", "qt"))}
        rho = ind.branch_loading(snap, flows=fl, rate=rate, strict_flows=bool(fl))
        rho = np.where(in_service, rho, np.nan)
        rho_t.append(rho)
        pf = np.array([flows[b]["pf"][t] if b in flows and flows[b].get("pf") else snap.branch.PF.iloc[i] for i, b in enumerate(ids)], dtype=float)
        n1_t.append(ind.n1_screening(snap, topo, flows_p=pf, rate=rate, in_service=in_service, rule=spec.omega.contingency_rule))
    rho_max = np.nanmax(np.vstack(rho_t), axis=0) if rho_t else np.full(nl, np.nan)
    worst_n1 = min(n1_t, key=lambda r: (r["pass_rate"] if r["pass_rate"] is not None else 1.0))
    vm = result.get("bus_vm") or {}
    voltage = None
    if vm:
        bidx = {f"B{int(b)}": i for i, b in enumerate(snap.bus["BUS_I"])}
        vmv = snap.bus["VM"].to_numpy(dtype=float).copy()
        worst = np.zeros(len(vmv))
        for b, arr in vm.items():
            i = bidx.get(b)
            if i is not None:
                a = np.asarray(arr, dtype=float)
                vmv[i] = a[int(np.argmax(np.abs(a - 1)))]
        voltage = ind.voltage_metrics(snap, vm=vmv)
    has_flow = bool(flows)
    return {"load_rate": ind.load_rate_metrics(rho_max, snap, topo) if has_flow else None, "voltage": voltage, "n1": worst_n1,
            "note": "各时段取最坏值；负载率只含结果里给了潮流的支路（没给的不计）" if flows else "结果里没有 branch_flow：负载率只能用断面潮流估计，不予显示",
            "has_flow": has_flow}

"""任务书指标 4.2：负载率、电压偏移、N−1 直流筛查。

调整前用断面里的潮流（PF、QF、PT、QT、VM）计算——这是真实数据；调整后用求解结果计算，mock 模式下显示“—”（返回 None）。

N−1 通过率是**直流近似筛查，不是交流 N−1 校核**，卡片上要写明：
  - 用 1/X 建直流 B 矩阵，有变比时按 MATPOWER 直流模型取 b = 1/(x·τ)，算 PTDF 和 LODF；
  - 事故集按 ω.contingency_rule 取，默认是网状部分的 225 条在运支路；
  - 对事故集中每条支路 c，事故后有功 f′ = f + LODF[:, c]·f_c，全部 |f′_l| ≤ RATE_A_l 即通过；
  - 通过率 = 通过数 / 评估数；
  - 事故集选了“全部在运支路”时，其中的孤岛型事故（775 条）不进 LODF，单列为“孤岛事故”，显示数量和涉及的净负荷。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from ..config import app_config
from ..data.snapshot import Snapshot, branch_id, bus_id
from ..data.topology import Topology


# ------------------------------------------------------------------------------------------------
# 负载率
# ------------------------------------------------------------------------------------------------
def branch_loading(snap: Snapshot, flows: dict[str, dict[str, float]] | None = None,
                   rate_scale: dict[str, float] | None = None, rate_set: dict[str, float] | None = None,
                   rate: np.ndarray | None = None, strict_flows: bool = False) -> np.ndarray:
    """每条支路的负载率 ρ = max(√(PF²+QF²), √(PT²+QT²)) / RATE_A；RATE_A = 0 视为不限（NaN）。

    flows：{L编号: {pf,qf,pt,qt}} 覆盖断面潮流（求解结果用）；strict_flows=True 时 flows 没覆盖的支路记 NaN（未知），不拿断面潮流顶替。
    rate：整条 RATE_A 数组覆盖（Δπ 之后的限额）；rate_scale / rate_set 是按支路的局部修改。"""
    br = snap.branch
    pf, qf, pt, qt = (br[c].to_numpy(dtype=float).copy() for c in ("PF", "QF", "PT", "QT"))
    rate = (br["RATE_A"].to_numpy(dtype=float) if rate is None else np.asarray(rate, dtype=float)).copy()
    ids = snap.branch_ids
    idx = {b: i for i, b in enumerate(ids)}
    unknown = np.zeros(len(ids), dtype=bool)
    if strict_flows:
        unknown[:] = True
    for b, f in (flows or {}).items():
        i = idx.get(b)
        if i is None:
            continue
        pf[i], qf[i], pt[i], qt[i] = f["pf"], f["qf"], f["pt"], f["qt"]
        unknown[i] = False
    for b, s in (rate_scale or {}).items():
        if b in idx:
            rate[idx[b]] *= s
    for b, v in (rate_set or {}).items():
        if b in idx:
            rate[idx[b]] = v
    s_use = np.maximum(np.hypot(pf, qf), np.hypot(pt, qt))
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = np.where((rate > 0) & ~unknown, s_use / rate, np.nan)
    return rho


def load_rate_metrics(rho: np.ndarray, snap: Snapshot, topo: Topology | None = None, top_n: int = 10) -> dict:
    """负载率卡片：最大值、平均值、≥ 重载阈值条数、≥ 越限阈值条数（阈值来自 config/app.yaml）。只算 RATE_A > 0 的支路。"""
    cfg = app_config()["thresholds"]
    hi, over = float(cfg["overload_ratio"]), float(cfg["violation_ratio"])
    valid = ~np.isnan(rho)
    r = rho[valid]
    order = np.argsort(-np.where(valid, rho, -1))[:top_n]
    return {
        "max": float(r.max()) if r.size else None,
        "mean": float(r.mean()) if r.size else None,
        "n_evaluated": int(valid.sum()),
        "n_overload": int((r >= hi).sum()), "n_violation": int((r >= over).sum()),
        "overload_threshold": hi, "violation_threshold": over,
        "n_unlimited": int((~valid).sum()),
        "top": [{"id": branch_id(int(i) + 1), "rho": float(rho[i]), "label": snap.branch_label(int(i) + 1)} for i in order if valid[i]],
    }


# ------------------------------------------------------------------------------------------------
# 电压偏移
# ------------------------------------------------------------------------------------------------
def voltage_metrics(snap: Snapshot, vm: np.ndarray | None = None, vmax: np.ndarray | None = None, vmin: np.ndarray | None = None) -> dict:
    """ΔV_i = |VM_i − 1|：最大值、平均值、越出 [VMIN, VMAX] 的母线数。基态已有 231 个母线高于 1.05（如实说明，未修正）。"""
    b = snap.bus
    vm = b["VM"].to_numpy(dtype=float) if vm is None else vm
    vmax = b["VMAX"].to_numpy(dtype=float) if vmax is None else vmax
    vmin = b["VMIN"].to_numpy(dtype=float) if vmin is None else vmin
    dv = np.abs(vm - 1.0)
    hi, lo = vm > vmax, vm < vmin
    worst = np.argsort(-dv)[:8]
    return {
        "max": float(dv.max()), "mean": float(dv.mean()),
        "n_out": int((hi | lo).sum()), "n_above_vmax": int(hi.sum()), "n_below_vmin": int(lo.sum()),
        "n_buses": int(len(vm)),
        "note": f"基态已有 {int(hi.sum())} 个母线高于 VMAX（VMAX 统一为 {sorted(set(vmax.tolist()))[-1]:g}，疑为默认值），未做修正",
        "worst": [{"id": bus_id(int(b.BUS_I.iloc[i])), "dv": float(dv[i]), "vm": float(vm[i])} for i in worst],
    }


# ------------------------------------------------------------------------------------------------
# N−1 直流筛查
# ------------------------------------------------------------------------------------------------
def _dc_system(snap: Snapshot, in_service: np.ndarray, tap_ratio: bool = True):
    """返回 (A 关联矩阵 nl×nb, b 向量, slack 下标, B_red 因子化所需信息)。"""
    br = snap.branch
    bidx = snap.bus_index()
    nb, nl = len(snap.bus), len(br)
    f = np.array([bidx[int(x)] for x in br["F_BUS"]])
    t = np.array([bidx[int(x)] for x in br["T_BUS"]])
    x = br["BR_X"].to_numpy(dtype=float)
    tau = br["TAP"].to_numpy(dtype=float)
    tau = np.where(tau == 0, 1.0, tau) if tap_ratio else np.ones(nl)
    b = np.where(in_service, 1.0 / (x * tau), 0.0)           # MATPOWER 直流模型：b = 1/(x·τ)
    rows = np.r_[np.arange(nl), np.arange(nl)]
    cols = np.r_[f, t]
    vals = np.r_[np.ones(nl), -np.ones(nl)]
    A = sp.csr_matrix((vals, (rows, cols)), shape=(nl, nb))
    slack = next((i for i, ty in enumerate(snap.bus["BUS_TYPE"]) if ty == 3), 0)
    return A, b, slack, f, t


def ptdf_lodf(snap: Snapshot, in_service: np.ndarray, contingencies: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """PTDF（nl×nb）与 LODF 的需要列（nl×len(contingencies)）。contingencies 为支路下标（0 起），必须是在运支路且非桥。

    PTDF = diag(b)·A·B⁻¹（去掉平衡节点）；LODF[:, c] = PTDF_c(f_c − t_c) / (1 − PTDF_cc)。
    """
    A, b, slack, f, t = _dc_system(snap, in_service)
    nb = A.shape[1]
    Bbus = (A.T @ sp.diags(b) @ A).tocsc()
    keep = np.array([i for i in range(nb) if i != slack])
    Bred = Bbus[keep][:, keep].tocsc()
    lu = spla.splu(Bred)
    nl = A.shape[0]
    # 只对需要的事故支路求：X = B⁻¹ (e_f − e_t) 对每个事故
    cont = np.array(contingencies, dtype=int)
    rhs = np.zeros((nb, len(cont)))
    rhs[f[cont], np.arange(len(cont))] += 1.0
    rhs[t[cont], np.arange(len(cont))] -= 1.0
    X = np.zeros((nb, len(cont)))
    X[keep, :] = lu.solve(rhs[keep, :])
    # PTDF[:, c-注入]：支路 l 对“c 的端点转移”的灵敏度 = b_l·(A X)_l
    AX = A @ X                                               # nl × nc
    PT = b[:, None] * AX                                     # 每支路对 (e_f−e_t) 单位转移的潮流
    pcc = PT[cont, np.arange(len(cont))]                     # 事故支路自身的 PTDF
    return PT, pcc


def n1_screening(snap: Snapshot, topo: Topology, flows_p: np.ndarray | None = None, rate: np.ndarray | None = None,
                 in_service: np.ndarray | None = None, rule: str = "meshed_in_service") -> dict:
    """N−1 直流筛查。

    flows_p：事故前有功潮流（MW）基准，默认取断面 PF（首端有功）；rate：RATE_A（MVA，当作 MW 限额）；in_service：当前在运状态。
    """
    br = snap.branch
    nl = len(br)
    in_service = topo.in_service.copy() if in_service is None else in_service.astype(bool)
    rate = br["RATE_A"].to_numpy(dtype=float) if rate is None else rate
    f0 = br["PF"].to_numpy(dtype=float).copy() if flows_p is None else flows_p.astype(float)
    f0 = np.where(in_service, f0, 0.0)

    cont_rows = [r - 1 for r in topo.rule_rows(rule) if in_service[r - 1]]
    # 孤岛型事故（桥且无并联）不能进 LODF（1 − PTDF_cc = 0）：单列统计
    iso_cont = [i for i in cont_rows if topo.isolating[i]]
    mesh_cont = [i for i in cont_rows if not topo.isolating[i]]
    # 孤岛事故：各事故是分别发生的（N−1），累计值只是把每次事故的孤岛负荷加总，嵌套的孤岛会被重复计入，所以同时给出单次最大。
    iso_info: dict[str, Any] = {"count": len(iso_cont), "note": "各事故分别计；累计值会重复计入嵌套孤岛，仅作规模参考",
                                "buses_total": 0, "load_mw_total": 0.0, "gen_mw_total": 0.0, "net_injection_mw_total": 0.0, "largest": None}
    biggest = None
    for i in iso_cont:
        d = topo.isolating_net_load.get(i + 1)
        if not d:
            continue
        iso_info["buses_total"] += d["buses"]
        iso_info["load_mw_total"] += d["load_mw"]
        iso_info["gen_mw_total"] += d["gen_mw"]
        iso_info["net_injection_mw_total"] += d["net_injection_mw"]
        if biggest is None or abs(d["net_injection_mw"]) > abs(biggest[1]["net_injection_mw"]):
            biggest = (i + 1, d)
    iso_info["net_load_mw_total"] = -iso_info["net_injection_mw_total"]
    for k in ("load_mw_total", "gen_mw_total", "net_injection_mw_total", "net_load_mw_total"):
        iso_info[k] = round(iso_info[k], 2)
    if biggest:
        iso_info["largest"] = {"contingency": branch_id(biggest[0]), "buses": biggest[1]["buses"],
                               "net_injection_mw": round(biggest[1]["net_injection_mw"], 2), "load_mw": round(biggest[1]["load_mw"], 2)}

    # 并联支路：一条停运后，并联的另一条仍在运，仍可算 LODF（端点之间依然连通）
    PT, pcc = ptdf_lodf(snap, in_service, mesh_cont) if mesh_cont else (np.zeros((nl, 0)), np.zeros(0))
    passed, failed, skipped = 0, [], 0
    limited = rate > 0
    for k, c in enumerate(mesh_cont):
        denom = 1.0 - pcc[k]
        if abs(denom) < 1e-8:                                # 数值上等同孤岛：归入孤岛事故
            skipped += 1
            iso_info["count"] += 1
            continue
        lodf = PT[:, k] / denom
        lodf[c] = -1.0
        post = f0 + lodf * f0[c]
        post[c] = 0.0
        viol = limited & in_service & (np.abs(post) > rate + 1e-9)
        viol[c] = False
        if viol.any():
            worst = int(np.argmax(np.where(viol, np.abs(post) / np.where(limited, rate, 1.0), 0)))
            failed.append({"contingency": branch_id(c + 1), "n_violations": int(viol.sum()), "worst": branch_id(worst + 1),
                           "worst_rho": float(abs(post[worst]) / rate[worst]),
                           "violated": [branch_id(int(i) + 1) for i in np.flatnonzero(viol)[:12]]})
        else:
            passed += 1
    evaluated = len(mesh_cont) - skipped
    # 越限支路出现频次：协商建议用（把 N−1 越限的支路组成断面限额）
    freq: dict[str, int] = {}
    for fl in failed:
        for b in fl["violated"]:
            freq[b] = freq.get(b, 0) + 1
    top = sorted(freq.items(), key=lambda kv: -kv[1])[:8]
    return {
        "method": "直流近似筛查（PTDF / LODF），非交流 N−1 校核",
        "rule": rule, "rule_name": app_config()["rules"]["contingency_rules"].get(rule, rule),
        "contingency_total": len(cont_rows), "evaluated": evaluated, "passed": passed, "failed_count": len(failed),
        "pass_rate": (passed / evaluated) if evaluated else None,
        "failed": sorted(failed, key=lambda x: -x["worst_rho"])[:50],
        "frequent_violated": [{"id": b, "count": c} for b, c in top],
        "islanding": iso_info,
        "note": ("事故集含孤岛型支路：这类事故一断开就形成孤岛，不进 LODF，单列为“孤岛事故”"
                 if iso_info["count"] else "事故集全部在网状部分，无孤岛型事故"),
    }


def dc_n1_bruteforce(snap: Snapshot, in_service: np.ndarray, c: int, f0: np.ndarray | None = None) -> np.ndarray:
    """测试用的独立实现：对事故 c 重新解直流潮流（不用 PTDF / LODF），返回事故后各支路有功。

    节点注入由事故前支路潮流 f0 反推（A^T f0）。只有当 f0 本身是直流解（f0 = b·Aθ）时，
    这个重解才等于 f0 + LODF·f_c；真实断面里的 PF 是交流潮流（含网损），不满足这一点，所以交叉验证要用直流一致的 f0。"""
    A, b, slack, f, t = _dc_system(snap, in_service)
    nb = A.shape[1]
    if f0 is None:
        f0 = np.where(in_service, snap.branch["PF"].to_numpy(dtype=float), 0.0)
    inj = A.T @ f0                                           # 节点净注入（由事故前支路潮流反推）
    ins2 = in_service.copy()
    ins2[c] = False
    A2, b2, _, _, _ = _dc_system(snap, ins2)
    B2 = (A2.T @ sp.diags(b2) @ A2).tocsc()
    keep = np.array([i for i in range(nb) if i != slack])
    theta = np.zeros(nb)
    theta[keep] = spla.spsolve(B2[keep][:, keep].tocsc(), inj[keep])
    return b2 * (A2 @ theta)

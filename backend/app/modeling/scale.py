"""规模估算：按模板逐块计数，给出变量数、0-1 变量数、约束数；并列三种可开断集合口径下的开断变量数。

所有数由程序按当前数据与规格计算，不写死。计数口径与 codegen.py 生成的 Pyomo 代码一一对应：
  变量：v、theta（N·T）、pg、qg（G·T）、pf/qf/pr/qr（4·L·T）、z（|L^s|·T，0-1）、dz（|L^s|·T，连续，开关动作线性化）
  约束：B1、B2（各 N·T）、B3（8·L·T：潮流与开断两组各 4）、B4（RATE_A>0 的支路 × 时段 × 2 端）、
        B6（4·G·T）、B8（T）、dz 线性化（2·|L^s|·T）、结构算子约束；B7 不产生约束（z 已固定）；B9 按事故集展开，由求解链决定。
"""
from __future__ import annotations

from typing import Any

from ..data.library import Window
from ..spec.schema import ModelSpec
from .formulas import fixed_topology
from .rundata import apply_delta_pi, get_data

RULE_NAMES = {
    "all_in_service": "全部在运支路",
    "meshed_in_service": "网状部分在运支路",
    "meshed_kv_ge_110": "网状且 ≥110kV 在运支路",
}


def _switchable(D: dict[str, Any], rule: str, outage: set[str]) -> list[str]:
    return [l for l in D["switchable"][rule] if l not in outage]


def estimate(spec: ModelSpec, window: Window, T: int | None = None, with_n1: bool = True) -> dict:
    """规模估算。T 默认为 ω.periods（完整 16 时段）；试构建对照时传 T=1。"""
    T = T or spec.omega.periods
    D0 = get_data(window, T)
    D, outage = apply_delta_pi(D0, spec.delta_pi)
    N, G, L = len(D["bus"]), len(D["gen"]), len(D["branch"])
    fixed = fixed_topology(spec)

    ls = [] if fixed else _switchable(D, spec.omega.switchable_rule, outage)
    nls = len(ls)
    b4 = sum(2 for l in D["branch"].values() for t in range(T) if l["rate"][t] > 0)

    blocks: list[dict] = []

    def add(bid: str, title: str, var_c: int = 0, var_b: int = 0, cons: int = 0, note: str = "") -> None:
        blocks.append({"id": bid, "title": title, "vars_cont": var_c, "vars_bin": var_b, "cons": cons, "note": note})

    add("VARS", "变量", var_c=2 * N * T + 2 * G * T + 4 * L * T + nls * T, var_b=nls * T, cons=2 * nls * T,
        note="v、θ、pg、qg、pf/qf/pr/qr；z（0-1）与开关动作 dz（连续）；dz 线性化 2 组约束")
    add("B1", "有功平衡", cons=N * T)
    add("B2", "无功平衡", cons=N * T)
    add("B3", "支路潮流与开断", cons=8 * L * T, note="每条支路每时段 4 个潮流量 × 2 组（开断松弛 / 关断置零）")
    add("B4", "热稳", cons=b4, note=f"RATE_A = 0 的支路不加；实际加了 {b4 // 2 // max(T, 1) if T else 0} 条/时段×2 端（按均值）")
    add("B5", "电压", note="作为变量边界，不计约束")
    add("B6", "机组", cons=4 * G * T)
    add("B7", "不可开断支路", note="z 固定为断面状态，不产生变量和约束")
    add("B8", "平衡节点", cons=T)
    n1_note = ""
    if spec.omega.n_minus_1 and with_n1:
        ncon = len(D["contingency"][spec.omega.contingency_rule])
        n1_note = f"事故集 {ncon} 条（{RULE_NAMES.get(spec.omega.contingency_rule, spec.omega.contingency_rule)}）；按事故集展开，由求解链决定"
        add("B9", "N−1 安全约束（抽象）", note=n1_note)
    unknown: list[str] = []
    for s in spec.structural:
        if s.op_id == "switching_limit_per_period":
            add(s.id, s.op_id, cons=T if not s.pending_fields else 0)
        elif s.op_id == "switching_limit_total":
            add(s.id, s.op_id, cons=1 if not s.pending_fields else 0)
        elif s.op_id == "section_limit":
            add(s.id, s.op_id, cons=T if not s.pending_fields else 0)
        elif s.op_id == "unit_commitment":
            gu = sum(1 for g in D["gen"].values() if g["status"][0] == 1 and g["pmax"][0] > 0 and abs(g["pg0"]) < 1000)
            ok = not s.pending_fields
            add(s.id, s.op_id, var_c=(gu * T) if ok else 0, var_b=(gu * T) if ok else 0, cons=(4 * gu * T + 1) if ok else 0,
                note=f"{gu} 台可启停机组 × {T} 时段：u（0-1）与启停动作 du；出力上下限联动 2 组、du 线性化 2 组、总次数 1 条")
        elif s.op_id == "generator_redispatch":
            r = (s.params or {}).get("ramp_pct")
            add(s.id, s.op_id, cons=(G * max(T - 1, 0)) if r is not None else 0, note="爬坡约束 G·(T−1) 条" if r is not None else "不限爬坡：不增加约束")
        elif s.op_id in ("switching_penalty", "loss_min", "voltage_deviation", "multi_period_acopf", "cost_economic", "reliability_nm1", "renewable_accommodation"):
            add(s.id, s.op_id, note="目标项 / 固定拓扑，不增加变量与约束")
        else:
            unknown.append(s.id)
            add(s.id, s.op_id, note="自定义算子：规模未计入")

    tot_c = sum(b["vars_cont"] for b in blocks)
    tot_b = sum(b["vars_bin"] for b in blocks)
    tot_k = sum(b["cons"] for b in blocks)
    by_rule = {}
    for r in ("all_in_service", "meshed_in_service", "meshed_kv_ge_110"):
        n = 0 if fixed else len(_switchable(D, r, outage))
        by_rule[r] = {"name": RULE_NAMES[r], "branches": n, "binary_vars": n * T, "binary_vars_16": n * 16, "current": r == spec.omega.switchable_rule}
    return {
        "T": T, "buses": N, "gens": G, "branches": L, "switchable": nls,
        "vars_continuous": tot_c, "vars_binary": tot_b, "vars_total": tot_c + tot_b, "constraints": tot_k,
        "by_rule": by_rule, "blocks": blocks, "n1_note": n1_note, "fixed_topology": fixed,
        "unknown_ops": unknown, "outage": sorted(outage),
        "note": "B9（N−1）按事故集展开，由求解链决定，未计入约束数" if spec.omega.n_minus_1 and with_n1 else "",
    }

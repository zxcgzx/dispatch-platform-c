"""OTS → CMDP：把规格 + 断面整理成约束马尔可夫决策过程的各个要素，供后续强化学习使用。

CMDP = (S, A, P, r, c, γ)：
  状态 s_t   ：时段 t 的负荷、机组出力、支路在运状态、（可选）上一时段开关动作
  动作 a_t   ：可开断集合内各支路的开断 / 闭合（0-1），加机组出力调整量
  转移 P     ：时段推进 + 潮流方程（由求解链 / 仿真器给出）
  奖励 r_t   ：− 目标函数当期值（偏离当前方式、开关动作惩罚、各目标项）
  代价 c_t   ：安全约束的违反量，每类约束一项（负载率越限、N−1 不通过、电压越限、开关次数超限）
  折扣 γ     ：取 1（有限时段）
本模块只给出结构化描述与规模，不做强化学习训练。
"""
from __future__ import annotations

from ..data.library import Window
from ..modeling.rundata import apply_delta_pi, get_data
from ..spec.schema import ModelSpec
from ..modeling.formulas import fixed_topology


def build(spec: ModelSpec, window: Window) -> dict:
    D0 = get_data(window)
    D, outage = apply_delta_pi(D0, spec.delta_pi)
    T = window.periods
    fixed = fixed_topology(spec)
    sw = [] if fixed else [l for l in D["switchable"][spec.omega.switchable_rule] if l not in outage]
    ng = len(D["gen"])
    uc = next((s for s in spec.structural if s.op_id == "unit_commitment"), None)
    obj_terms = [{"op": s.op_id, "text": s.op_id} for s in spec.structural if s.kind == "objective"]
    cons: list[dict] = [
        {"id": "c_rho", "name": "负载率越限", "expr": "Σ_l max(0, ρ_l − 1)", "source": "B4 热稳"},
        {"id": "c_volt", "name": "电压越限", "expr": "Σ_i max(0, V_i − V̄_i, V̲_i − V_i)", "source": "B5 电压"},
    ]
    if spec.omega.n_minus_1:
        cons.append({"id": "c_n1", "name": "N−1 不通过", "expr": "不通过事故数 / 事故集大小", "source": "B9 N−1"})
    for s in spec.structural:
        if s.op_id == "switching_limit_per_period":
            cons.append({"id": "c_" + s.id, "name": f"每时段开关次数超限（k = {s.params.get('k')}）", "expr": "max(0, Σ|Δz_t| − k)", "source": s.id})
        elif s.op_id == "switching_limit_total":
            cons.append({"id": "c_" + s.id, "name": f"开关总次数超限（K = {s.params.get('K')}）", "expr": "max(0, Σ_tΣ|Δz| − K)", "source": s.id})
        elif s.op_id == "section_limit":
            cons.append({"id": "c_" + s.id, "name": "断面限额越限", "expr": "max(0, Σ_{l∈S} P_l − P̄_S)", "source": s.id})
    n_actions = len(sw) + (ng if any(s.op_id == "generator_redispatch" for s in spec.structural) else 0) + (ng if uc else 0)
    return {
        "periods": T, "gamma": 1.0,
        "state": {"dim": D["T"] and (len(D["bus"]) + ng + len(D["branch"])), "parts": [
            {"name": "母线有功负荷 P^D", "size": len(D["bus"])}, {"name": "机组出力 P^G", "size": ng}, {"name": "支路在运状态 z", "size": len(D["branch"])}]},
        "action": {"binary": len(sw), "continuous": ng if any(s.op_id == "generator_redispatch" for s in spec.structural) else 0,
                   "unit_commitment": ng if uc else 0, "per_step_total": n_actions,
                   "note": "可开断集合内每条支路一个 0-1 动作" + ("；固定拓扑下没有开断动作" if fixed else "")},
        "reward": {"expr": "r_t = −( Σ_g |P^G_{g,t} − P^{G,0}_g| + 目标项 )", "terms": ["偏离当前方式"] + [t["op"] for t in obj_terms]},
        "costs": cons,
        "horizon_actions": n_actions * T,
        "status": "todo",
        "note": "只给出 CMDP 的结构化描述；强化学习训练与仿真环境待接入。",
    }

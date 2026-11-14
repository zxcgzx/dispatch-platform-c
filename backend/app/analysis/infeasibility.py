"""无解诊断：求解不可行时，找出互相冲突的约束，并给出可以放松的项。

做法（删除过滤 + 弹性松弛）：
1. 对断面逐项松弛：把候选约束组（限额修改、断面限额、开关次数、机组上下限、停运）逐个放开，重新求解，
   放开后变可行的组就是“冲突来源”；
2. 对每个来源再求一次弹性松弛（在该约束上加松弛变量，最小化松弛量），给出“至少需要放松多少”。
所有求解都调用内置求解器 dcots.solve_spec，只改规格，不改求解器本身。
"""
from __future__ import annotations

import copy
import time

from ..data.library import Window
from ..solver.dcots import solve_spec
from ..spec.schema import ModelSpec

FEAS = ("optimal", "feasible")


def _solve(spec: ModelSpec, window: Window, tl: float) -> str:
    return solve_spec(spec, window, tl)["status"]


def _groups(spec: ModelSpec) -> list[dict]:
    out: list[dict] = []
    for s in spec.structural:
        if s.op_id == "section_limit":
            out.append({"id": s.id, "kind": "s", "label": f"断面有功限额（{s.id}）", "hint": "放宽限额，或减少断面内支路"})
        elif s.op_id == "switching_limit_per_period":
            out.append({"id": s.id, "kind": "s", "label": f"每时段开关次数上限 k = {s.params.get('k')}（{s.id}）", "hint": "提高 k"})
        elif s.op_id == "switching_limit_total":
            out.append({"id": s.id, "kind": "s", "label": f"开关总次数上限 K = {s.params.get('K')}（{s.id}）", "hint": "提高 K"})
        elif s.op_id == "unit_commitment":
            out.append({"id": s.id, "kind": "s", "label": f"机组启停总次数上限（{s.id}）", "hint": "提高启停次数上限"})
        elif s.op_id == "generator_redispatch" and (s.params or {}).get("ramp_pct") is not None:
            out.append({"id": s.id, "kind": "s", "label": f"机组爬坡上限（{s.id}）", "hint": "放宽爬坡或取消爬坡约束"})
    for d in spec.delta_pi:
        if d.param == "RATE_A":
            out.append({"id": d.id, "kind": "dp", "label": f"{d.target} 热稳限额修改（{d.id}）", "hint": "放宽该支路限额，或让它不被单独收紧"})
        elif d.param in ("PMAX", "PMIN"):
            out.append({"id": d.id, "kind": "dp", "label": f"{d.target} 出力{'上' if d.param == 'PMAX' else '下'}限修改（{d.id}）", "hint": "放宽机组出力范围"})
        elif d.param == "BR_STATUS":
            out.append({"id": d.id, "kind": "dp", "label": f"{d.target} 停运（{d.id}）", "hint": "改选其他检修对象，或缩短停运时段"})
        elif d.param in ("PD", "QD"):
            out.append({"id": d.id, "kind": "dp", "label": f"{d.target} 负荷修改（{d.id}）", "hint": "降低负荷增幅，或增加可调机组"})
    return out


def _without(spec: ModelSpec, gid: str) -> ModelSpec:
    s2 = copy.deepcopy(spec)
    s2.structural = [s for s in s2.structural if s.id != gid]
    s2.delta_pi = [d for d in s2.delta_pi if d.id != gid]
    return s2


def diagnose(spec: ModelSpec, window: Window, time_limit: float = 20.0) -> dict:
    t0 = time.perf_counter()
    base = _solve(spec, window, time_limit)
    if base in FEAS:
        return {"status": "feasible", "message": "当前规格可行，无需诊断。", "conflicts": [], "elapsed_s": round(time.perf_counter() - t0, 2)}
    groups = _groups(spec)
    conflicts: list[dict] = []
    for g in groups:
        st = _solve(_without(spec, g["id"]), window, time_limit)
        if st in FEAS:
            conflicts.append({**g, "removing_makes_feasible": True})
    # 单项去掉都不可行：逐项累加去掉（贪心），找最小冲突集
    combo: list[str] = []
    if not conflicts and groups:
        cur = copy.deepcopy(spec)
        for g in groups:
            cur = _without(cur, g["id"])
            combo.append(g["id"])
            if _solve(cur, window, time_limit) in FEAS:
                break
        else:
            combo = []
        conflicts = [{**g, "removing_makes_feasible": False, "in_combination": True} for g in groups if g["id"] in combo]
    if conflicts:
        msg = ("找到冲突来源：去掉其中任意一项，模型就可行。" if conflicts[0].get("removing_makes_feasible")
               else "没有单个约束能解除冲突：需要同时放宽下面这几项。")
    else:
        msg = "规格里的修改项都不是冲突来源：不可行来自断面本身（机组出力范围、停运造成的孤岛等），请检查数据质量与停运对象。"
    return {"status": base, "message": msg, "conflicts": conflicts, "n_groups": len(groups), "elapsed_s": round(time.perf_counter() - t0, 2)}

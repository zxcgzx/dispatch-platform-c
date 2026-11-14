"""测点 ↔ 节点转换（课题 2 接口）。

正向（节点 → 模拟测点），按怀柔讨论的构造机制：
  1. 每个母线节点 → 一个母线测点（BUS_MP）；
  2. 普通线路（TAP = 0）：两端各插入一个虚拟开关测点，原线路的阻抗、热稳极限放在两个开关之间的“线路边”，
     母线—开关两段是零阻抗连接边，只表示连接关系与状态；
  3. 变压器（TAP ≠ 0）：同样两端虚拟开关，中间是变压器测点（档位 / 变比），参数在“开关—变压器”边上；
  4. 发电机、负荷不建独立测点，信息挂在边界开关上：每个有机组的母线挂一个发电机边界开关，有负荷的母线挂一个负荷边界开关。
输出静态 / 动态两张表，按母线、变压器、开关、连接线路四类对象组织。

逆向（模拟测点 → 节点）：按正向构造的逆过程恢复 Bus / Gen / Branch；用映射表（mapping）保证平行支路、多机组母线无歧义。
回写（节点结果 → 测点动作）：支路停运映射到该支路两端虚拟开关；一条支路停运不能唯一反推出两端动作，这里默认两端同时断开，并在结果里写明。

范围说明：这是模拟测点的构造与恢复（用于课题 2 联调演示），不是真实电网测点的现场方案。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..data.snapshot import Snapshot, branch_id, bus_id, gen_id
from ..data.topology import Topology

SENTINEL = -999999.0


def build_mapping_and_tables(snap: Snapshot, topo: Topology) -> dict[str, Any]:
    bus, gen, br = snap.bus, snap.gen, snap.branch
    nb, nl = len(bus), len(br)
    base_kv = snap.bus_kv()

    # ---- 母线测点
    bus_mp = []
    for i in range(nb):
        b = int(bus.BUS_I.iloc[i])
        bus_mp.append({"mp_id": f"MP_B{b}", "node": bus_id(b), "kv": float(bus.BASE_KV.iloc[i]), "vm": float(bus.VM.iloc[i]),
                       "va": float(bus.VA.iloc[i]), "pd": float(bus.PD.iloc[i]), "qd": float(bus.QD.iloc[i])})
    # ---- 开关 / 线路 / 变压器
    switches: list[dict] = []
    links: list[dict] = []          # 连接线路（边）
    trafos: list[dict] = []
    lines: list[dict] = []
    for i in range(nl):
        r = br.iloc[i]
        lid = branch_id(i + 1)
        f, t = int(r.F_BUS), int(r.T_BUS)
        is_tr = bool(topo.is_transformer[i])
        sf, st = f"SW_{lid}_F", f"SW_{lid}_T"
        status = int(r.BR_STATUS > 0)
        switches.append({"mp_id": sf, "node": lid, "end": "F", "bus_mp": f"MP_B{f}", "status": status,
                         "p": float(r.PF), "q": float(r.QF), "kind": "branch"})
        switches.append({"mp_id": st, "node": lid, "end": "T", "bus_mp": f"MP_B{t}", "status": status,
                         "p": float(r.PT), "q": float(r.QT), "kind": "branch"})
        mid = f"TR_{lid}" if is_tr else f"LN_{lid}"
        links.append({"link_id": f"{lid}_a", "from": f"MP_B{f}", "to": sf, "ltype": 2, "role": "连接边"})
        links.append({"link_id": f"{lid}_b", "from": sf, "to": mid if is_tr else st, "ltype": 1, "role": "变压器参数边" if is_tr else "线路边",
                      "r": float(r.BR_R), "x": float(r.BR_X), "b": float(r.BR_B), "rate_a": float(r.RATE_A), "tap": float(r.TAP)})
        if is_tr:
            links.append({"link_id": f"{lid}_c", "from": mid, "to": st, "ltype": 1, "role": "变压器参数边", "r": 0.0, "x": 0.0, "b": 0.0, "rate_a": float(r.RATE_A), "tap": 1.0})
            trafos.append({"mp_id": mid, "node": lid, "kv_hi": float(topo.kv[i]), "tap_ratio": float(r.TAP) if r.TAP != 0 else 1.0,
                           "gear": SENTINEL, "type": 2})
            links.append({"link_id": f"{lid}_d", "from": st, "to": f"MP_B{t}", "ltype": 2, "role": "连接边"})
        else:
            links.append({"link_id": f"{lid}_c", "from": st, "to": f"MP_B{t}", "ltype": 2, "role": "连接边"})
            lines.append({"mp_id": mid, "node": lid})
    # ---- 发电机 / 负荷边界开关
    gens_at: dict[int, list[int]] = {}
    for k in range(len(gen)):
        gens_at.setdefault(int(gen.GEN_BUS.iloc[k]), []).append(k)
    boundary: list[dict] = []
    for b, ks in gens_at.items():
        boundary.append({"mp_id": f"SW_GEN_B{b}", "bus_mp": f"MP_B{b}", "kind": "gen", "status": 1,
                         "p": float(sum(gen.PG.iloc[k] for k in ks)), "q": float(sum(gen.QG.iloc[k] for k in ks)),
                         "gens": [gen_id(k + 1) for k in ks]})
    for i in range(nb):
        pd_, qd_ = float(bus.PD.iloc[i]), float(bus.QD.iloc[i])
        if abs(pd_) > 1e-9 or abs(qd_) > 1e-9:
            b = int(bus.BUS_I.iloc[i])
            boundary.append({"mp_id": f"SW_LOAD_B{b}", "bus_mp": f"MP_B{b}", "kind": "load", "status": 1, "p": pd_, "q": qd_, "gens": []})
    return {"bus_mp": bus_mp, "switches": switches, "boundary": boundary, "links": links, "trafos": trafos, "lines": lines}


def summary(snap: Snapshot, topo: Topology) -> dict[str, Any]:
    m = build_mapping_and_tables(snap, topo)
    n_tr = len(m["trafos"])
    return {
        "bus_mp": len(m["bus_mp"]), "line_switches": len(m["switches"]), "boundary_switches": len(m["boundary"]),
        "boundary_gen": sum(1 for x in m["boundary"] if x["kind"] == "gen"), "boundary_load": sum(1 for x in m["boundary"] if x["kind"] == "load"),
        "trafos": n_tr, "lines": len(m["lines"]), "links": len(m["links"]),
        "switches_total": len(m["switches"]) + len(m["boundary"]),
        "mp_total": len(m["bus_mp"]) + len(m["switches"]) + len(m["boundary"]) + n_tr + len(m["lines"]),
    }


def static_dynamic_tables(snap: Snapshot, topo: Topology, limit: int | None = None) -> dict[str, Any]:
    """静态表（拓扑与参数）+ 动态表（量测与状态），按母线 / 变压器 / 开关 / 连接线路四类对象组织。"""
    m = build_mapping_and_tables(snap, topo)
    cut = (lambda x: x[:limit]) if limit else (lambda x: x)
    static = {
        "母线": cut([{"MP_ID": b["mp_id"], "节点": b["node"], "额定电压kV": b["kv"]} for b in m["bus_mp"]]),
        "变压器": cut([{"MP_ID": t["mp_id"], "节点支路": t["node"], "高压侧kV": t["kv_hi"], "变比": t["tap_ratio"], "档位": t["gear"], "TYPE": t["type"]} for t in m["trafos"]]),
        "开关": cut([{"MP_ID": s["mp_id"], "节点支路": s["node"], "端": s["end"], "连接母线": s["bus_mp"]} for s in m["switches"]]
                  + [{"MP_ID": s["mp_id"], "节点支路": "", "端": "边界", "连接母线": s["bus_mp"], "类型": {"gen": "发电机边界", "load": "负荷边界"}[s["kind"]]} for s in m["boundary"]]),
        "连接线路": cut([{k: v for k, v in l.items()} for l in m["links"]]),
    }
    dynamic = {
        "母线": cut([{"MP_ID": b["mp_id"], "电压VM(p.u.)": round(b["vm"], 6), "相角VA(rad)": round(b["va"], 6)} for b in m["bus_mp"]]),
        "变压器": cut([{"MP_ID": t["mp_id"], "变比": t["tap_ratio"], "档位": t["gear"]} for t in m["trafos"]]),
        "开关": cut([{"MP_ID": s["mp_id"], "P(MW)": round(s["p"], 4), "Q(Mvar)": round(s["q"], 4), "STATUS": s["status"]} for s in m["switches"]]
                  + [{"MP_ID": s["mp_id"], "P(MW)": round(s["p"], 4), "Q(Mvar)": round(s["q"], 4), "STATUS": s["status"]} for s in m["boundary"]]),
        "连接线路": cut([{"link_id": l["link_id"], "STATUS": 1} for l in m["links"]]),
    }
    return {"static": static, "dynamic": dynamic, "summary": summary(snap, topo)}


# ------------------------------------------------------------------------------------------------
# 逆向：测点表 → 节点（Bus / Gen / Branch）
# ------------------------------------------------------------------------------------------------
def reverse_recover(snap: Snapshot, topo: Topology) -> dict[str, Any]:
    """按正向的逆过程，从模拟测点表恢复节点模型，并与原节点数据逐项比对（往返验证）。"""
    m = build_mapping_and_tables(snap, topo)
    bus, br, gen = snap.bus, snap.branch, snap.gen
    # 母线
    rec_bus = {b["node"]: (b["pd"], b["qd"], b["vm"], b["va"], b["kv"]) for b in m["bus_mp"]}
    # 支路：由 开关 + 线路边 参数恢复
    link_by_lid: dict[str, dict] = {}
    for l in m["links"]:
        if l["ltype"] == 1 and "x" in l and l["link_id"].endswith("_b"):
            link_by_lid[l["link_id"][:-2]] = l
    sw_by: dict[tuple[str, str], dict] = {(s["node"], s["end"]): s for s in m["switches"]}
    rec_br = {}
    for lid, l in link_by_lid.items():
        sf, st = sw_by[(lid, "F")], sw_by[(lid, "T")]
        f = int(sf["bus_mp"][4:]); t = int(st["bus_mp"][4:])
        rec_br[lid] = (f, t, l["r"], l["x"], l["b"], l["rate_a"], l["tap"], sf["status"], sf["p"], sf["q"], st["p"], st["q"])
    # 发电机：边界开关只有合计，靠 gens 列表（映射资料）拆回；没有映射就只能得到合计
    gen_total = {}
    for bd in m["boundary"]:
        if bd["kind"] == "gen":
            gen_total[bd["mp_id"][len("SW_GEN_B"):]] = (bd["p"], bd["gens"])
    # 比对
    diffs = {"bus": 0, "branch": 0, "gen_bus_total": 0}
    for i in range(len(bus)):
        b = int(bus.BUS_I.iloc[i]); r = rec_bus[bus_id(b)]
        if not (np.isclose(r[0], bus.PD.iloc[i]) and np.isclose(r[2], bus.VM.iloc[i]) and np.isclose(r[4], bus.BASE_KV.iloc[i])):
            diffs["bus"] += 1
    for i in range(len(br)):
        r = rec_br[branch_id(i + 1)]; o = br.iloc[i]
        if not (r[0] == int(o.F_BUS) and r[1] == int(o.T_BUS) and np.isclose(r[2], o.BR_R) and np.isclose(r[3], o.BR_X) and np.isclose(r[5], o.RATE_A)
                and np.isclose(r[6], o.TAP) and r[7] == int(o.BR_STATUS > 0) and np.isclose(r[8], o.PF)):
            diffs["branch"] += 1
    for b, (ptot, gl) in gen_total.items():
        orig = float(sum(gen.PG.iloc[int(g[1:]) - 1] for g in gl))
        if not np.isclose(ptot, orig):
            diffs["gen_bus_total"] += 1
    # 没有映射时，发电机的分量不可恢复：统计多机母线
    multi = {b: gl for b, (p, gl) in gen_total.items() if len(gl) > 1}
    parallel = {}
    for i in range(len(br)):
        parallel.setdefault(frozenset((int(br.F_BUS.iloc[i]), int(br.T_BUS.iloc[i]))), []).append(branch_id(i + 1))
    par_groups = {tuple(v) for v in parallel.values() if len(v) > 1}
    return {
        "recovered": {"bus": len(rec_bus), "branch": len(rec_br), "gen_buses": len(gen_total)},
        "original": {"bus": len(bus), "branch": len(br), "gen_records": len(gen)},
        "mismatch": diffs,
        "lossless_with_mapping": diffs["bus"] == 0 and diffs["branch"] == 0 and diffs["gen_bus_total"] == 0,
        "ambiguities_without_mapping": {
            "multi_gen_buses": len(multi), "parallel_branch_groups": len(par_groups),
            "note": "没有映射表时：多机组母线只能得到合计出力，平行支路无法按端点区分回路。映射表（源记录键 + 版本）保证可逆。"},
        "example_multi_gen": next(iter(multi.items()), None), "example_parallel": next(iter(par_groups), None),
    }


# ------------------------------------------------------------------------------------------------
# 回写：节点方案 → 测点动作
# ------------------------------------------------------------------------------------------------
def writeback(result: dict | None, outages: dict[str, list[int]] | None = None) -> dict[str, Any]:
    """把求解结果里的支路开断映射成开关动作清单。

    一条支路停运可由首端断、末端断或两端同时断实现，不能唯一反推；这里默认两端同时断开，并在 note 里写明。
    这是“方案的测点侧表示”，不代表现场设备已执行。
    """
    if not result or result.get("status") not in ("optimal", "feasible"):
        return {"actions": [], "note": "没有可回写的求解结果"}
    bs = dict(result.get("branch_status") or {})
    actions = []
    T = int(result.get("periods", 1))
    for lid, arr in sorted(bs.items(), key=lambda kv: int(kv[0][1:])):
        for t in range(T):
            prev = 1 if t == 0 else arr[t - 1]
            if arr[t] != prev:
                kind = "断开" if arr[t] == 0 else "合上"
                for end in ("F", "T"):
                    actions.append({"period": t + 1, "switch": f"SW_{lid}_{end}", "branch": lid, "action": kind, "to_status": arr[t]})
    # 首时段起就处于断开状态的（含检修停运）：也需要动作
    return {
        "actions": actions, "n_branches": len(bs),
        "note": "支路停运默认映射为两端虚拟开关同时断开；单端断开或其他组合同样能使支路退出，需结合现场操作规程确认。该清单是方案的测点侧表示，不代表设备已执行。",
    }

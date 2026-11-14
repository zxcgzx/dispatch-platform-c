"""代码生成：规格 → Pyomo 模块 `build_model(data, spec) -> pyo.ConcreteModel`。

要点：
- 每个块用标记包住：`# >>> [B4] 热稳` … `# <<< [B4]`；`# >>> [dp-1] L155.RATE_A ×0.8` … `# <<< [dp-1]`。
  前端靠这些标记做“规格 ↔ 代码”双向跳转。
- 算子库里有的修改由模板确定性生成；custom_code 原样插入并在标记里加 `custom` 标注（界面标黄待审）。
- **代码页显示的代码就是试构建执行的代码**：`generate_code` 的返回值直接写进 model.py，
  `trial.py` 在子进程里 exec 这同一份文本，不做任何二次拼接。
- 生成的代码读 `spec`（dict）里的 delta_pi / structural，Δπ 逐条作为 dp 块执行；
  数据 `data` 是 rundata.build_data 的输出。
- 求解部分不在这里：这里只构建模型（变量、约束、目标），不调用任何求解器。
"""
from __future__ import annotations

import re

from ..spec.schema import DeltaPi, ModelSpec, StructuralOp
from . import operators as ops
from .describe import dp_title, s_title
from .formulas import fixed_topology
from .rundata import effective_op

MARK_RE = re.compile(r"^# >>> \[(?P<id>[A-Za-z0-9\-]+)\](?P<rest>.*)$")
END_RE = re.compile(r"^# <<< \[(?P<id>[A-Za-z0-9\-]+)\]\s*$")

HEADER = '''"""自动生成：{task} v{ver}。{note}
由规格（ω、Δπ、s、R）+ 算子库模板确定性生成；代码页显示的代码就是试构建执行的代码。
只构建模型（变量 / 约束 / 目标），不调用求解器；B9（N−1）为抽象块，展开形式由求解链定义。
"""
import math

import pyomo.environ as pyo


def _period_list(periods, T):
    """Δπ 的时段（空 = 全部）截到 1..T。"""
    return [t for t in (periods or range(1, T + 1)) if 1 <= t <= T]


def _dp(arr, periods, T, op, val):
    """对 arr（长度 T 的列表）的指定时段执行 scale / set / add。"""
    for t in _period_list(periods, T):
        if op == "scale":
            arr[t - 1] *= val
        elif op == "set":
            arr[t - 1] = val
        elif op == "add":
            arr[t - 1] += val


def build_model(data, spec, with_n1=True):
    """data：rundata.build_data 的输出；spec：ModelSpec.model_dump()。with_n1=False 时跳过 B9（试构建用）。"""
    import copy
    D = copy.deepcopy(data)
    T = D["T"]
    base_mva = D["base_mva"]
    omega = spec["omega"]
    m = pyo.ConcreteModel()
    obj_terms = []
'''


def _wrap(bid: str, title: str, body: str, extra: str = "") -> str:
    head = f"# >>> [{bid}] {title}" + (f"  {extra}" if extra else "")
    return f"{head}\n{body.rstrip()}\n# <<< [{bid}]"


def _indent(code: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join((pad + ln) if ln.strip() else ln for ln in code.splitlines())


# ---------------------------------------------------------------------------------------
# Δπ 块
# ---------------------------------------------------------------------------------------
_ARR = {
    ("bus", "PD"): ("bus", "pd"), ("bus", "QD"): ("bus", "qd"), ("bus", "VMAX"): ("bus", "vmax"), ("bus", "VMIN"): ("bus", "vmin"),
    ("gen", "PMAX"): ("gen", "pmax"), ("gen", "PMIN"): ("gen", "pmin"), ("gen", "GEN_STATUS"): ("gen", "status"),
    ("branch", "RATE_A"): ("branch", "rate"), ("branch", "BR_STATUS"): ("branch", "status"),
}


def _dp_block(dp: DeltaPi, T: int) -> str:
    title = dp_title(dp)
    key = _ARR.get((dp.component, dp.param))
    op = effective_op(dp)
    if key is None:
        body = f"# 参数 {dp.component}.{dp.param} 不在白名单内：未生成修改（校验 E102 会拦截）"
    elif op is None:
        why = "推断项幅度待用户确认，未生效" if dp.source == "inferred" else "缺少 operation 或 value，未生效"
        body = f"# {why}（校验 W109 / E103）\n# 方向：{dp.direction or '—'}"
    else:
        o, v = op
        v = int(v) if dp.param in ("BR_STATUS", "GEN_STATUS") else v
        periods = list(dp.periods)
        body = (f"_dp(D[{key[0]!r}][{dp.target!r}][{key[1]!r}], {periods!r}, T, {o!r}, {v!r})"
                if dp.target else "# 缺少对象")
        if dp.param == "BR_STATUS" and o == "set" and v == 0:
            body += f"\nOUTAGE.add({dp.target!r})  # 停运支路：从可开断集合中移出，z 固定为 0"
    # 对象不存在时不能让构建崩溃：交给校验 E101 报错，这里跳过
    if key is not None and op is not None and dp.target:
        guard = f"if {dp.target!r} in D[{key[0]!r}]:\n" + _indent(body) + f"\nelse:\n    pass  # 对象 {dp.target} 不存在：校验 E101 会拦截，构建时跳过"
        body = guard
    extra = "[待确认]" if dp.source == "inferred" and op is None else ""
    return _wrap(dp.id, title, body, extra)


# ---------------------------------------------------------------------------------------
# 基础模型块
# ---------------------------------------------------------------------------------------
def _sets_block(spec: ModelSpec) -> str:
    rule = spec.omega.switchable_rule
    fixed = fixed_topology(spec)
    body = f'''OUTAGE = set()  # 由 dp 块填入：停运支路
BUSES = list(D["bus"])
GENS = list(D["gen"])
BRANCHES = list(D["branch"])
FIXED_TOPOLOGY = {fixed!r}  # 固定拓扑（AC-OPF）：可开断集合为空
SWITCH_RULE = omega.get("switchable_rule", {rule!r})
'''
    return _wrap("OMEGA", "集合与参数（ω）", body)


def _post_dp_block() -> str:
    body = '''_slack = D["slack"]
SWITCHABLE = [] if FIXED_TOPOLOGY else [l for l in D["switchable"][SWITCH_RULE] if l not in OUTAGE]  # 可开断集合 L^s（停运支路已移出）
z0 = {l: D["branch"][l]["status"][0] for l in BRANCHES}  # 断面状态 z^0
m.N = pyo.Set(initialize=BUSES, ordered=True)
m.G = pyo.Set(initialize=GENS, ordered=True)
m.L = pyo.Set(initialize=BRANCHES, ordered=True)
m.LS = pyo.Set(initialize=SWITCHABLE, ordered=True)
m.T = pyo.RangeSet(1, T)
# 连续变量：电压、相角、机组 P/Q、支路首末端 P/Q
m.v = pyo.Var(m.N, m.T, bounds=lambda m, i, t: (D["bus"][i]["vmin"][t - 1], D["bus"][i]["vmax"][t - 1]), initialize=1.0)
m.theta = pyo.Var(m.N, m.T, initialize=0.0)
m.pg = pyo.Var(m.G, m.T, initialize=0.0)
m.qg = pyo.Var(m.G, m.T, initialize=0.0)
m.pf = pyo.Var(m.L, m.T, initialize=0.0)
m.qf = pyo.Var(m.L, m.T, initialize=0.0)
m.pr = pyo.Var(m.L, m.T, initialize=0.0)
m.qr = pyo.Var(m.L, m.T, initialize=0.0)
# 0-1 变量：仅可开断集合内的支路；其余支路 z 取断面状态（停运支路为 0）
m.z = pyo.Var(m.LS, m.T, within=pyo.Binary, initialize=lambda m, l, t: z0[l])
def z_of(l, t):
    """支路 l 在时段 t 的状态：可开断则为变量，否则取固定值（停运 / 不可开断 = 断面状态）。"""
    if l in OUTAGE:
        return 0
    if l in m.LS:
        return m.z[l, t]
    return D["branch"][l]["status"][t - 1]
# 开关动作 dz = |z_t - z_{t-1}|（线性化），z_0 = 断面状态
m.dz = pyo.Var(m.LS, m.T, within=pyo.NonNegativeReals, initialize=0.0)
def _dz_up(m, l, t):
    prev = z0[l] if t == 1 else m.z[l, t - 1]
    return m.dz[l, t] >= m.z[l, t] - prev
def _dz_dn(m, l, t):
    prev = z0[l] if t == 1 else m.z[l, t - 1]
    return m.dz[l, t] >= prev - m.z[l, t]
m.dz_up = pyo.Constraint(m.LS, m.T, rule=_dz_up)
m.dz_dn = pyo.Constraint(m.LS, m.T, rule=_dz_dn)'''
    return _wrap("VARS", "变量与可开断集合 L^s", body)


def _block_code(bid: str) -> tuple[str, str]:
    """基础模型块的构建代码（Pyomo 表达式）。B1–B9。"""
    if bid == "B1":
        return "有功平衡", '''_gens_at = {}
for g in GENS:
    _gens_at.setdefault(D["gen"][g]["bus"], []).append(g)
_from_at, _to_at = {}, {}
for l in BRANCHES:
    _from_at.setdefault(D["branch"][l]["f"], []).append(l)
    _to_at.setdefault(D["branch"][l]["t"], []).append(l)
def _b1(m, i, t):
    return (sum(m.pg[g, t] for g in _gens_at.get(i, [])) - D["bus"][i]["pd"][t - 1] - D["bus"][i]["gs"] * m.v[i, t] ** 2
            == sum(m.pf[l, t] for l in _from_at.get(i, [])) + sum(m.pr[l, t] for l in _to_at.get(i, [])))
m.b1 = pyo.Constraint(m.N, m.T, rule=_b1)'''
    if bid == "B2":
        return "无功平衡", '''def _b2(m, i, t):
    return (sum(m.qg[g, t] for g in _gens_at.get(i, [])) - D["bus"][i]["qd"][t - 1] + D["bus"][i]["bs"] * m.v[i, t] ** 2
            == sum(m.qf[l, t] for l in _from_at.get(i, [])) + sum(m.qr[l, t] for l in _to_at.get(i, [])))
m.b2 = pyo.Constraint(m.N, m.T, rule=_b2)'''
    if bid == "B3":
        return "支路潮流与开断", '''def _pi_flows(l, t):
    """MATPOWER π 型支路模型（含 TAP、SHIFT）：返回 (p^f, q^f, p^r, q^r) 关于 V、θ 的表达式。"""
    br = D["branch"][l]
    y = 1.0 / complex(br["r"], br["x"])
    g, b = y.real, y.imag
    tau = br["tap"] if br["tap"] != 0 else 1.0
    sh = math.radians(br["shift"])
    vf, vt = m.v[br["f"], t], m.v[br["t"], t]
    d = m.theta[br["f"], t] - m.theta[br["t"], t] - sh
    bc = br["b"]
    pf = (g / tau ** 2) * vf ** 2 - (vf * vt / tau) * (g * pyo.cos(d) + b * pyo.sin(d))
    qf = -(b + bc / 2) / tau ** 2 * vf ** 2 - (vf * vt / tau) * (g * pyo.sin(d) - b * pyo.cos(d))
    pr = g * vt ** 2 - (vf * vt / tau) * (g * pyo.cos(d) - b * pyo.sin(d))
    qr = -(b + bc / 2) * vt ** 2 + (vf * vt / tau) * (g * pyo.sin(d) + b * pyo.cos(d))
    return pf, qf, pr, qr
BIG_M = 10.0  # p.u.，仅示意；真实取值由求解链按支路定
def _b3(m, l, t, k):
    expr = _pi_flows(l, t)[k]
    var = (m.pf, m.qf, m.pr, m.qr)[k][l, t]
    zz = z_of(l, t)
    return pyo.inequality(-BIG_M * (1 - zz), var - expr, BIG_M * (1 - zz))
m.b3 = pyo.Constraint(m.L, m.T, range(4), rule=_b3)
def _b3_off(m, l, t, k):
    var = (m.pf, m.qf, m.pr, m.qr)[k][l, t]
    return pyo.inequality(-BIG_M * z_of(l, t), var, BIG_M * z_of(l, t))
m.b3_off = pyo.Constraint(m.L, m.T, range(4), rule=_b3_off)'''
    if bid == "B4":
        return "热稳", '''def _b4(m, l, t, end):
    rate = D["branch"][l]["rate"][t - 1] / base_mva  # MVA -> p.u.；RATE_A = 0 视为不限，不加该约束
    if rate <= 0:
        return pyo.Constraint.Skip
    p, q = (m.pf[l, t], m.qf[l, t]) if end == 0 else (m.pr[l, t], m.qr[l, t])
    return p ** 2 + q ** 2 <= z_of(l, t) * rate ** 2
m.b4 = pyo.Constraint(m.L, m.T, range(2), rule=_b4)'''
    if bid == "B5":
        return "电压", "# 电压上下限已作为变量 m.v 的边界（VMAX、VMIN，逐时段取值）写入 [VARS]；本块不再重复添加约束。\npass"
    if bid == "B6":
        return "机组", '''def _b6p(m, g, t, side):
    u = D["gen"][g]["status"][t - 1]
    if side == 0:
        return m.pg[g, t] >= u * D["gen"][g]["pmin"][t - 1] / base_mva
    return m.pg[g, t] <= u * D["gen"][g]["pmax"][t - 1] / base_mva
m.b6p = pyo.Constraint(m.G, m.T, range(2), rule=_b6p)
def _b6q(m, g, t, side):
    u = D["gen"][g]["status"][t - 1]
    if side == 0:
        return m.qg[g, t] >= u * D["gen"][g]["qmin"][t - 1] / base_mva
    return m.qg[g, t] <= u * D["gen"][g]["qmax"][t - 1] / base_mva
m.b6q = pyo.Constraint(m.G, m.T, range(2), rule=_b6q)'''
    if bid == "B7":
        return "不可开断支路", '''# z_{l,t} = z^0_l, l ∈ L \\ L^s：不可开断支路（含停运支路，z = 0）的 z 不作为变量，
# 已由 z_of(l, t) 直接取断面状态，所以本块既不产生变量也不产生约束对象。
NON_SWITCHABLE = [l for l in BRANCHES if l not in m.LS]'''
    if bid == "B8":
        return "平衡节点", '''def _b8(m, t):
    return m.theta[_slack, t] == 0
m.b8 = pyo.Constraint(m.T, rule=_b8)'''
    if bid == "B9":
        return "N−1 安全约束（抽象块）", '''# N−1：∀c∈C, t∈T: x^(c)_t ∈ F(z_t − e_c)。事故集 C 取 omega["contingency_rule"]。
# 展开形式由求解链定义，这里只记录事故集，不展开（试构建时跳过本块）。
if with_n1 and omega.get("n_minus_1", True):
    CONTINGENCY = list(D["contingency"][omega.get("contingency_rule", "meshed_in_service")])
    m.n1_contingencies = CONTINGENCY'''
    raise KeyError(bid)


def _objective_block() -> str:
    body = '''# 基础目标：断面里没有发电成本，取“偏离当前方式最小”，P^{G,0}_g 取断面 PG
_pg0 = {g: D["gen"][g]["pg0"] / base_mva for g in GENS}
obj_terms.append(sum((m.pg[g, t] - _pg0[g]) ** 2 for g in m.G for t in m.T))'''
    return _wrap("OBJ", "目标（偏离当前方式最小）", body)


def _final_objective_block() -> str:
    body = '''m.obj = pyo.Objective(expr=sum(obj_terms), sense=pyo.minimize)
return m'''
    return _wrap("OBJ-END", "汇总目标", body)


# ---------------------------------------------------------------------------------------
# 结构算子块
# ---------------------------------------------------------------------------------------
def _s_block(s: StructuralOp) -> str:
    title = s_title(s)
    if s.op_id in ops.operators():
        pf = s.pending_fields
        if pf:
            body = f"# 算子参数未确定：{', '.join(pf)}（校验 E108 会拦截），本块暂不生成约束"
            return _wrap(s.id, title, body, "[待确认]")
        body = ops.render_code(s.op_id, s.params)
        extra = ""
        if s.op_id in ("switching_penalty", "loss_min", "voltage_deviation") and (s.params or {}).get("beta") is None:
            extra = f"[β 未给，用配置默认值 {ops.beta_default():g}]"
        return _wrap(s.id, title, body, extra)
    if s.custom_code:
        return _wrap(s.id, title, s.custom_code, "custom 待审")
    return _wrap(s.id, title, "# 算子不在算子库且没有 custom_code：未生成（校验 E106 会拦截）", "[未知算子]")


# ---------------------------------------------------------------------------------------
# 总装
# ---------------------------------------------------------------------------------------
def generate_code(spec: ModelSpec) -> str:
    """生成 model.py 的完整文本。"""
    T = spec.omega.periods
    note = "含推断项尚未确认的条目只写注释、不生效。" if any(d.source == "inferred" and effective_op(d) is None for d in spec.delta_pi) else ""
    parts: list[str] = [HEADER.format(task=spec.task_id, ver=spec.version, note=note).rstrip("\n")]
    body: list[str] = [_sets_block(spec)]
    for dp in spec.delta_pi:                       # Δπ 先执行：改数据 D 与 OUTAGE
        body.append(_dp_block(dp, T))
    body.append(_post_dp_block())
    for bid in ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"):
        title, code = _block_code(bid)
        body.append(_wrap(bid, title, code))
    if spec.omega.n_minus_1:
        title, code = _block_code("B9")
        body.append(_wrap("B9", title, code))
    body.append(_objective_block())
    for s in spec.structural:
        body.append(_s_block(s))
    body.append(_final_objective_block())
    parts.append(_indent("\n\n".join(body)))
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------------------
# 标记解析（前端据此折叠、跳转；后端用来做行号映射）
# ---------------------------------------------------------------------------------------
def parse_markers(code: str) -> list[dict]:
    """返回 [{id, title, start, end, custom, pending}]，行号从 1 开始，含标记行。"""
    out: list[dict] = []
    stack: dict[str, dict] = {}
    for i, raw in enumerate(code.splitlines(), start=1):
        line = raw.strip()
        m = MARK_RE.match(line)
        if m:
            rest = m.group("rest").strip()
            stack[m.group("id")] = {"id": m.group("id"), "title": rest, "start": i, "custom": "custom" in rest, "pending": "待确认" in rest or "未知算子" in rest}
            continue
        e = END_RE.match(line)
        if e and e.group("id") in stack:
            d = stack.pop(e.group("id"))
            d["end"] = i
            out.append(d)
    out.sort(key=lambda x: x["start"])
    return out

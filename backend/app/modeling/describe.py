"""规格条目的统一描述：标题（代码标记用）、LaTeX（公式页用）、中文回译（第 5 层 I503 用）。

公式页、代码页、校验页共用这一份，三处口径一致。
"""
from __future__ import annotations

from ..spec.schema import BaseModelDef, DeltaPi, StructuralOp
from ..spec.whitelist import COMPONENT_LABEL, DIRECTION_LABEL, param_info
from . import operators as ops
from .rundata import effective_op

# 参数 → 受影响的基础模型块
AFFECTS: dict[tuple[str, str], list[str]] = {
    ("bus", "PD"): ["B1"], ("bus", "QD"): ["B2"], ("bus", "VMAX"): ["B5"], ("bus", "VMIN"): ["B5"],
    ("gen", "PMAX"): ["B6"], ("gen", "PMIN"): ["B6"], ("gen", "GEN_STATUS"): ["B6"],
    ("branch", "RATE_A"): ["B4"], ("branch", "BR_STATUS"): ["B3", "B7"],
}
STRUCT_AFFECTS = {"multi_period_acopf": ["B3", "B7"]}


def periods_text(periods: list[int], n: int) -> str:
    """'第 5–12 时段' / '全部时段' / '第 1、3、5 时段'。"""
    if not periods or sorted(set(periods)) == list(range(1, n + 1)):
        return "全部时段"
    ps = sorted(set(periods))
    if ps == list(range(ps[0], ps[-1] + 1)) and len(ps) > 1:
        return f"第 {ps[0]}–{ps[-1]} 时段"
    return "第 " + "、".join(map(str, ps)) + " 时段"


def periods_latex(periods: list[int], n: int) -> str:
    if not periods or sorted(set(periods)) == list(range(1, n + 1)):
        return r"\forall t\in\mathcal T"
    ps = sorted(set(periods))
    if len(ps) == 1:
        return rf"t={ps[0]}"
    if ps == list(range(ps[0], ps[-1] + 1)):
        return rf"t\in\{{{ps[0]},\dots,{ps[-1]}\}}"
    return r"t\in\{" + ",".join(map(str, ps)) + r"\}"


def _num(x: float) -> str:
    return f"{x:g}"


def _sym(dp: DeltaPi) -> str:
    """带下标的符号，如 \\bar S_{\\mathrm{L155}} / P^{D}_{\\mathrm{B43},t}。"""
    info = param_info(dp.component, dp.param) or {"symbol": dp.param}
    base = info["symbol"]
    tid = rf"\mathrm{{{dp.target}}}"
    if dp.param in ("PD", "QD"):
        return rf"{base}_{{{tid},t}}"
    return rf"{base}_{{{tid}}}"


def dp_title(dp: DeltaPi) -> str:
    """代码标记里的标题，如 'L155.RATE_A ×0.8'。"""
    head = f"{dp.target}.{dp.param}"
    op = effective_op(dp)
    if dp.source == "inferred" and op is None:
        d = {"decrease": "↓ 幅度待确认", "increase": "↑ 幅度待确认", "set_zero": "置 0"}.get(dp.direction or "", "待确认")
        return f"{head} {d}"
    if op is None:
        return f"{head} 缺少操作或数值"
    o, v = op
    if o == "scale":
        return f"{head} ×{_num(v)}"
    if o == "add":
        return f"{head} +{_num(v)}" if v >= 0 else f"{head} {_num(v)}"
    return f"{head} ={_num(v)}"


def dp_latex(dp: DeltaPi, n: int) -> str:
    sym = _sym(dp)
    per = periods_latex(dp.periods, n)
    op = effective_op(dp)
    pending = r"\ \text{（待确认）}"
    if dp.param == "BR_STATUS" and op == ("set", 0.0):
        return rf"z_{{\mathrm{{{dp.target}}},t}}=0,\ {per};\quad \mathcal L^{{s}}\leftarrow\mathcal L^{{s}}\setminus\{{\mathrm{{{dp.target}}}\}}"
    if dp.param == "BR_STATUS":
        return rf"z_{{\mathrm{{{dp.target}}},t}}={_num(op[1]) if op else '?'},\ {per}"
    if dp.param == "GEN_STATUS":
        return rf"u_{{\mathrm{{{dp.target}}}}}={_num(op[1]) if op else '?'},\ {per}"
    if dp.source == "inferred" and op is None:
        if dp.direction == "decrease":
            return rf"{sym}\leftarrow \alpha\,{sym},\ \alpha<1,\ {per}{pending}"
        if dp.direction == "increase":
            return rf"{sym}\leftarrow \alpha\,{sym},\ \alpha>1,\ {per}{pending}"
        return rf"{sym}\leftarrow ?,\ {per}{pending}"
    if op is None:
        return rf"{sym}\leftarrow ?,\ {per}"
    o, v = op
    if o == "scale":
        return rf"{sym}\leftarrow {_num(v)}\,{sym},\ {per}"
    if o == "add":
        return rf"{sym}\leftarrow {sym}{'+' if v >= 0 else '-'}{_num(abs(v))},\ {per}"
    return rf"{sym}\leftarrow {_num(v)},\ {per}"


def dp_zh(dp: DeltaPi, n: int) -> str:
    """第 5 层语义回译：把一条 Δπ 翻回自然语言。"""
    info = param_info(dp.component, dp.param) or {"label": dp.param, "unit": ""}
    comp = COMPONENT_LABEL.get(dp.component, dp.component)
    who = f"{comp} {dp.target}"
    per = periods_text(dp.periods, n)
    op = effective_op(dp)
    if dp.param == "BR_STATUS" and op == ("set", 0.0):
        return f"{who} 在{per}检修停运（z = 0，并移出可开断集合）"
    if dp.param == "GEN_STATUS" and op == ("set", 0.0):
        return f"{who} 在{per}停运（u = 0）"
    if dp.source == "inferred" and op is None:
        d = DIRECTION_LABEL.get(dp.direction or "", "调整")
        return f"{who} 的{info['label']}{d}，幅度待确认，{per}（推断项）"
    if op is None:
        return f"{who} 的{info['label']}：缺少操作或数值"
    o, v = op
    unit = info.get("unit", "")
    if o == "scale":
        return f"{who} 的{info['label']}乘以 {_num(v)}（{'提高' if v > 1 else '降低' if v < 1 else '不变'} {abs(v - 1) * 100:g}%），{per}"
    if o == "add":
        return f"{who} 的{info['label']}增加 {_num(v)} {unit}，{per}"
    return f"{who} 的{info['label']}设为 {_num(v)} {unit}，{per}"


def s_title(op: StructuralOp) -> str:
    o = ops.operators().get(op.op_id)
    name = o["name"] if o else (op.op_id + "（自定义）")
    return f"{op.op_id} · {name}"


def s_latex(op: StructuralOp) -> str:
    if op.op_id not in ops.operators():
        return r"\text{自定义算子（待审）：" + op.op_id.replace("_", r"\_") + "}"
    return ops.render_latex(op.op_id, _filled(op))


def _filled(op: StructuralOp) -> dict:
    """公式里未知参数（如断面限额）保持符号，不编造数值。"""
    p = dict(op.params or {})
    return p


def s_zh(op: StructuralOp) -> str:
    p = op.params or {}
    if op.op_id == "switching_limit_per_period":
        return f"每个时段开关操作不超过 {p.get('k', '?')} 次"
    if op.op_id == "switching_limit_total":
        return f"全部时段开关操作总数不超过 {p.get('K', '?')} 次"
    if op.op_id == "section_limit":
        brs = "、".join(p.get("branches") or []) or "?"
        return f"由 {brs} 组成的断面，有功限额 {p.get('limit_mw', '?')} MW"
    if op.op_id in ("switching_penalty", "loss_min", "voltage_deviation"):
        name = {"switching_penalty": "开关操作惩罚（尽量少动开关）", "loss_min": "网损", "voltage_deviation": "电压偏差"}[op.op_id]
        b = p.get("beta")
        return f"目标中加入{name}，系数 β = {b if b is not None else '未给（用配置默认值）'}"
    if op.op_id == "multi_period_acopf":
        return "固定拓扑（不开断）"
    return f"自定义结构修改 {op.op_id}（待审）"


def omega_zh(om: BaseModelDef) -> str:
    return f"基础模型：{'多时段 AC-OTS' if om.problem == 'multi_period_ac_ots' else '多时段 AC-OPF（固定拓扑）'}，{om.periods} 时段 × {om.step_min} 分钟，" \
           f"{'满足 N−1' if om.n_minus_1 else '不含 N−1'}"

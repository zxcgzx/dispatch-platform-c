"""五层校验（指令第 7 节）与去幻觉。

每条结果：层、代码、级别（error / warn / info）、中文说明、关联的规格条目 id、修改建议。
错误会阻止进入求解，警告需用户确认。任何情况下都不得自动把找不到的对象换成别的对象。

第 5 层用与引擎无关的 modeling/extract.py 独立抽取，才能查出大模型的“遗漏”和“编造”。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from ..config import app_config, settings
from ..data.library import Window, get_snapshot
from ..data.snapshot import Snapshot, parse_id
from ..data.topology import Topology
from ..modeling import operators as ops
from ..modeling.codegen import generate_code
from ..modeling.describe import dp_zh, omega_zh, s_zh
from ..modeling.extract import (
    extract_keywords, extract_kv_mentions, extract_objects, match_switching_limit, object_kv,
)
from ..modeling.formulas import fixed_topology
from ..modeling.rundata import apply_delta_pi, effective_op, get_data, period_list
from ..modeling.scale import estimate
from ..modeling.state import Finding
from ..modeling.trial import custom_code_risks, run_trial, syntax_check
from ..spec.level import compute_level
from ..spec.schema import DeltaPi, ModelSpec, StructuralOp
from ..spec.whitelist import COMPONENT_LABEL, ID_PREFIX, validate_delta_pi

LAYERS = {1: "规格合法", 2: "结构一致", 3: "数据检查", 4: "可执行", 5: "语义回译"}
SWITCH_OPS = {"switching_limit_per_period", "switching_limit_total", "switching_penalty"}


@dataclass
class CheckContext:
    snap: Snapshot
    topo: Topology
    window: Window
    skip_trial: bool = False          # 测评模式批量跑时可跳过试构建（默认也跑，较慢）


def _f(layer: int, code: str, level: str, msg: str, item: str | None = None, sug: str | None = None, data: dict | None = None) -> Finding:
    return Finding(layer=layer, code=code, level=level, message=msg, item_id=item, suggestion=sug, data=data)  # type: ignore[arg-type]


# =====================================================================================
# 第 1 层 规格合法
# =====================================================================================
def _check_target(snap: Snapshot, dp: DeltaPi) -> Finding | None:
    p = parse_id(dp.target or "")
    label = COMPONENT_LABEL.get(dp.component, dp.component)
    if p is None:
        return _f(1, "E101", "error",
                  f"对象“{dp.target}”在数据中找不到（不是有效的{label}编号 {ID_PREFIX.get(dp.component, '?')}+数字，也没有匹配的设备）", dp.id,
                  "核对指令里的编号或端点；系统不会自动替换成别的对象，也不会静默忽略这一条")
    if p[0] != dp.component:
        return _f(1, "E101", "error", f"对象 {dp.target} 与对象类型“{label}”不符", dp.id, "改选正确类型的对象")
    if not snap.has_object(p[0], p[1]):
        extra = ""
        if p[0] == "bus":
            extra = f"（BUS_I 范围 {int(snap.bus.BUS_I.min())}–{int(snap.bus.BUS_I.max())}，共 {len(snap.bus)} 个母线）"
        elif p[0] == "branch":
            extra = f"（共 {len(snap.branch)} 条支路）"
        else:
            extra = f"（共 {len(snap.gen)} 台机组）"
        return _f(1, "E101", "error", f"{label} {dp.target} 在数据中不存在{extra}", dp.id,
                  "请核对编号；系统不会自动替换成别的对象，也不会静默忽略这一条")
    return None


def _positive_int(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v >= 1
    return isinstance(v, float) and v.is_integer() and v >= 1


def layer1(spec: ModelSpec, ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    n = spec.omega.periods
    for dp in spec.delta_pi:
        f = _check_target(ctx.snap, dp)
        if f:
            out.append(f)
        for code, msg in validate_delta_pi(dp):
            out.append(_f(1, code, "error", f"{dp.id}（{dp.target}.{dp.param}）：{msg}", dp.id, "按白名单与数值范围修改（见 config/app.yaml）"))
        bad = sorted(p for p in dp.periods if not 1 <= p <= n)
        if bad:
            out.append(_f(1, "E105", "error", f"{dp.id}：时段 {bad} 超出 1–{n}", dp.id, f"时段应在 1–{n} 内；留空表示全部时段"))
        if dp.source == "inferred" and (not dp.confirmed or dp.value is None):
            why = "幅度未填" if dp.value is None else "尚未经用户确认"
            out.append(_f(1, "W109", "warn", f"{dp.id}（{dp.target}.{dp.param}）是推断项，{why}：不会生效", dp.id, "填写幅度并勾选“确认”后才会进入模型"))
    for s in spec.structural:
        known = s.op_id in ops.operators()
        if not known and not s.custom_code:
            out.append(_f(1, "E106", "error", f"{s.id}：结构算子 {s.op_id} 不在算子库中，且没有 custom_code", s.id,
                          f"改用算子库里的算子：{', '.join(ops.operators())}"))
            continue
        if s.custom_code:
            out.append(_f(1, "W107", "warn", f"{s.id}：含 custom_code（{s.op_id}），待人工审核", s.id, "逐行审阅这段由大模型写的代码后再确认"))
            for sid, msg in custom_code_risks(spec):
                if sid == s.id:
                    out.append(_f(1, "E108", "error", f"{s.id}：{msg}", s.id, "删除不允许的调用，或改用算子库里的算子"))
        if known:
            out.extend(_check_op_params(s, ctx))
        kind = ops.operators()[s.op_id]["kind"] if known else None
        if known and kind != s.kind:
            out.append(_f(1, "E108", "error", f"{s.id}：算子 {s.op_id} 的类别应为 {kind}，实际为 {s.kind}", s.id, f"把类别改成 {kind}"))
    return out


def _check_op_params(s: StructuralOp, ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    p = s.params or {}
    spec_params = ops.operators()[s.op_id].get("params", {})

    def bad(msg: str, sug: str) -> None:
        out.append(_f(1, "E108", "error", f"{s.id}（{s.op_id}）：{msg}", s.id, sug))

    for name in s.pending_fields:
        bad(f"参数 {name} 尚未确定", "补全该参数")
    for name, d in spec_params.items():
        v = p.get(name)
        if name in s.pending_fields:
            continue
        t = d.get("type")
        if v is None:
            if d.get("nullable") or "default" in d:
                if name == "beta":
                    out.append(_f(1, "W110", "warn",
                                  f"{s.id}（{s.op_id}）：β 为空，将使用配置默认值 {ops.beta_default():g}（config/app.yaml）", s.id,
                                  "如需指定，请填写 β（正数）"))
                continue
            bad(f"缺少参数 {name}", "补全该参数")
            continue
        if t == "int" and not _positive_int(v):
            bad(f"{name} 必须是正整数，实际为 {v!r}", f"{name} 取 1, 2, 3 …")
        elif t == "float":
            try:
                fv = float(v)
            except (TypeError, ValueError):
                bad(f"{name} 不是数值：{v!r}", "填写数值")
                continue
            if "min_exclusive" in d and not fv > d["min_exclusive"]:
                bad(f"{name} 必须大于 {d['min_exclusive']:g}，实际为 {fv:g}", "填写正数")
        elif t == "list_branch":
            if not isinstance(v, list) or not v:
                bad("断面支路列表为空", "至少给出一条支路")
                continue
            for b in v:
                pid = parse_id(str(b))
                if pid is None or pid[0] != "branch" or not ctx.snap.has_object("branch", pid[1]):
                    bad(f"断面支路 {b} 不存在", "只能使用数据中存在的支路 L 编号；系统不会替换成别的支路")
            if len(set(map(str, v))) != len(v):
                bad("断面支路列表有重复项", "去掉重复的支路")
        elif t == "str" and "choices" in d and v not in d["choices"]:
            bad(f"{name} 只能取 {d['choices']}，实际为 {v!r}", "改成允许的取值")
    return out


# =====================================================================================
# 第 2 层 结构一致
# =====================================================================================
def _outage_periods(spec: ModelSpec) -> dict[str, set[int]]:
    """支路 → 停运的时段集合（BR_STATUS 置 0 的明确项）。"""
    n = spec.omega.periods
    out: dict[str, set[int]] = {}
    for dp in spec.delta_pi:
        if dp.component == "branch" and dp.param == "BR_STATUS" and effective_op(dp) == ("set", 0.0):
            out.setdefault(dp.target, set()).update(period_list(dp.periods, n))
    return out


def layer2(spec: ModelSpec, ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    n = spec.omega.periods
    # E201：同一对象、同一参数、同一时段被多条 Δπ 修改且结果冲突
    seen: dict[tuple[str, str, int], list[tuple[str, tuple[str, float]]]] = {}
    for dp in spec.delta_pi:
        op = effective_op(dp)
        if op is None:
            continue
        for t in period_list(dp.periods, n):
            seen.setdefault((dp.target, dp.param, t), []).append((dp.id, op))
    reported: set[tuple[str, ...]] = set()
    for (target, param, t), items in seen.items():
        if len(items) > 1 and len({op for _, op in items}) > 1:
            ids = tuple(sorted({i for i, _ in items}))
            if ids in reported:
                continue
            reported.add(ids)
            ps = sorted(tt for (tg, pm, tt), its in seen.items() if tg == target and pm == param and tuple(sorted({i for i, _ in its})) == ids)
            desc = "；".join(f"{i}: {o[0]} {o[1]:g}" for i, o in items)
            out.append(_f(2, "E201", "error", f"{target}.{param} 在时段 {ps[0]}{'–' + str(ps[-1]) if len(ps) > 1 else ''} 被多条修改且结果冲突（{desc}）",
                          ids[0], "保留一条，或让它们的时段不重叠"))
    outage = _outage_periods(spec)
    sec_branches: dict[str, list[str]] = {}
    for s in spec.structural:
        if s.op_id == "section_limit":
            for b in (s.params or {}).get("branches") or []:
                sec_branches.setdefault(str(b), []).append(s.id)
    # W202：已停运支路又被改了 RATE_A，或被放进断面
    for dp in spec.delta_pi:
        if dp.component == "branch" and dp.param == "RATE_A" and dp.target in outage:
            if set(period_list(dp.periods, n)) & outage[dp.target]:
                out.append(_f(2, "W202", "warn", f"{dp.target} 在部分时段已停运，却又修改了 RATE_A（{dp.id}）", dp.id, "停运时段的限额修改不会起作用，可删除或缩短时段"))
    for b, sids in sec_branches.items():
        if b in outage:
            out.append(_f(2, "W202", "warn", f"{b} 已设为停运，却被放进断面（{', '.join(sids)}）", sids[0], "停运支路潮流恒为 0，断面限额对它无意义"))
    # I203：停运支路自动移出可开断集合
    if not fixed_topology(spec) and outage:
        D = get_data(ctx.window)
        inset = set(D["switchable"][spec.omega.switchable_rule])
        for b in sorted(outage):
            if b in inset:
                dpid = next(d.id for d in spec.delta_pi if d.target == b and d.param == "BR_STATUS")
                out.append(_f(2, "I203", "info", f"停运支路 {b} 已自动移出可开断集合（规则：{app_config()['rules']['switchable_rules'].get(spec.omega.switchable_rule, spec.omega.switchable_rule)}）", dpid))
    # E204：修改后 PMIN > PMAX 或 VMIN > VMAX
    D0 = get_data(ctx.window)
    D, _ = apply_delta_pi(D0, [d for d in spec.delta_pi if d.target in D0.get(d.component, {})])
    touched = {(d.component, d.target) for d in spec.delta_pi if d.param in ("PMAX", "PMIN", "VMAX", "VMIN") and d.target in D0.get(d.component, {})}
    for comp, tg in sorted(touched):
        lo_k, hi_k = ("pmin", "pmax") if comp == "gen" else ("vmin", "vmax")
        lo, hi = D[comp][tg][lo_k], D[comp][tg][hi_k]
        ts = [t + 1 for t in range(len(lo)) if lo[t] > hi[t]]
        if ts:
            names = ("PMIN", "PMAX") if comp == "gen" else ("VMIN", "VMAX")
            dpid = next(d.id for d in spec.delta_pi if d.target == tg and d.param in names)
            out.append(_f(2, "E204", "error", f"{tg} 修改后 {names[0]} > {names[1]}（时段 {ts[0]}{'–' + str(ts[-1]) if len(ts) > 1 else ''}）", dpid,
                          f"调整 {names[0]} / {names[1]} 使下限不大于上限"))
    # W205：固定拓扑却有开关类算子
    if fixed_topology(spec):
        for s in spec.structural:
            if s.op_id in SWITCH_OPS:
                out.append(_f(2, "W205", "warn", f"问题类型为固定拓扑，却有开关类算子 {s.op_id}（{s.id}）", s.id, "固定拓扑下没有开断动作，这条约束 / 目标项不起作用"))
    # W206：停运后形成孤岛
    if outage:
        sets_by_t: dict[int, frozenset[str]] = {t: frozenset(b for b, ps in outage.items() if t in ps) for t in range(1, n + 1)}
        groups: dict[frozenset[str], list[int]] = {}
        for t, bs in sets_by_t.items():
            if bs:
                groups.setdefault(bs, []).append(t)
        for bs, ts in groups.items():
            rows = {int(b[1:]) for b in bs if parse_id(b) and ctx.snap.has_object("branch", int(b[1:]))}
            for isl in ctx.topo.outage_islands(rows):
                lab = "、".join(isl.bus_labels[:6]) + ("…" if len(isl.bus_labels) > 6 else "")
                kind = "净注入" if isl.net_injection_mw >= 0 else "净负荷"
                dpid = next(d.id for d in spec.delta_pi if d.target in bs and d.param == "BR_STATUS")
                rng = f"{ts[0]}–{ts[-1]}" if len(ts) > 1 else str(ts[0])
                out.append(_f(2, "W206", "warn",
                              f"{'、'.join(sorted(bs))} 停运后形成孤岛：孤立 {len(isl.buses)} 个母线（{lab}），孤岛内{kind}约 {abs(isl.net_injection_mw):.1f} MW（时段 {rng}）",
                              dpid, "孤岛内的负荷 / 机组将与主网解列，请确认是否可接受，或改选其他检修方式",
                              data={"buses": isl.bus_labels, "net_injection_mw": round(isl.net_injection_mw, 2), "periods": ts}))
    # W207：指令里的电压等级与数据不一致
    objs = extract_objects(spec.instruction, ctx.snap, ctx.topo)
    for kv in extract_kv_mentions(spec.instruction, objs):
        cands = kv.candidates or ([kv.object_id] if kv.object_id else [])
        if not cands:
            continue
        kvs = [object_kv(ctx.snap, ctx.topo, c) for c in cands if parse_id(c) and ctx.snap.object_exists(c)]
        kvs = [k for k in kvs if k is not None]
        if kvs and not any(math.isclose(k, kv.kv or 0.0) for k in kvs):
            real = "、".join(f"{c} 为 {object_kv(ctx.snap, ctx.topo, c):g}kV" for c in cands[:3] if ctx.snap.object_exists(c))
            ref = next((d.id for d in spec.delta_pi if d.target in cands), None)
            out.append(_f(2, "W207", "warn", f"指令写的是 {kv.kv:g}kV，与数据不一致（{real}）", ref, "核对指令里的电压等级与对象编号是否对应"))
    return out


# =====================================================================================
# 第 3 层 数据检查
# =====================================================================================
def layer3(spec: ModelSpec, ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    snaps = [get_snapshot(sid)[0] for sid in dict.fromkeys(spec.snapshot.snapshot_ids or ctx.window.snapshot_ids)]
    for sn in snaps:
        nan = int(sn.bus.isna().sum().sum() + sn.gen.isna().sum().sum() + sn.branch.isna().sum().sum())
        if nan:
            out.append(_f(3, "E301", "error", f"断面 {sn.snapshot_id} 存在 {nan} 个缺失值 / NaN", None, "补全断面数据后重新导入"))
    s0 = snaps[0]
    zero = np.flatnonzero(s0.branch["RATE_A"].to_numpy() == 0)
    if len(zero):
        ids = [f"L{i + 1}" for i in zero][:8]
        out.append(_f(3, "W302", "warn", f"有 {len(zero)} 条支路 RATE_A = 0，视为不限（{'、'.join(ids)}）", None,
                      "这些支路不参与负载率与热稳约束 B4；如实为限额缺失请补充数据"))
    hi = int((s0.bus["VM"] > s0.bus["VMAX"]).sum())
    lo = int((s0.bus["VM"] < s0.bus["VMIN"]).sum())
    gout = int(((s0.gen["PG"] > s0.gen["PMAX"]) | (s0.gen["PG"] < s0.gen["PMIN"])).sum())
    out.append(_f(3, "I303", "info", f"基态电压越限：{hi} 个母线 VM > VMAX，{lo} 个 VM < VMIN；机组出力越界：{gout} 台 PG 不在 [PMIN, PMAX] 内（如实统计，未修正）"))
    if ctx.window.periods == 1:
        out.append(_f(3, "I305", "info", "当前是单时段断面：只有 1 个断面，按 1 个时段建模；导入多个时刻的断面后可组成多时段滚动窗口", None, None))
    return out


# =====================================================================================
# 第 4 层 可执行
# =====================================================================================
def layer4(spec: ModelSpec, ctx: CheckContext, code: str | None = None) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    code = code if code is not None else generate_code(spec)
    err = syntax_check(code)
    if err:
        out.append(_f(4, "E401", "error", f"生成的代码有语法错误：{err}", None, "检查 custom_code 或联系开发"))
        return out, {"status": "skipped", "reason": "语法错误"}
    est = estimate(spec, ctx.window)
    est1 = estimate(spec, ctx.window, T=1, with_n1=False)
    trial: dict = {"status": "skipped", "reason": "未执行"}
    if not ctx.skip_trial:
        sid = (spec.snapshot.snapshot_ids or ctx.window.snapshot_ids)[0]
        trial = run_trial(code, spec, sid)
    if trial["status"] in ("error", "timeout"):
        out.append(_f(4, "E402", "error", f"试构建失败：{trial.get('error', '')}", trial.get("item_id"), "根据异常信息修改规格；custom_code 请逐行审阅"))
    elif trial["status"] == "skipped":
        out.append(_f(4, "W404", "warn", f"试构建已跳过：{trial.get('reason', '')}", None, "安装 Pyomo 后可验证代码能真实构建模型"))
    msg = (f"规模估算（{est['T']} 时段）：变量 {est['vars_total']:,}（其中 0-1 变量 {est['vars_binary']:,}），约束 {est['constraints']:,}（不含 B9）")
    if trial["status"] == "ok":
        match = (trial["vars"] == est1["vars_total"] and trial["binary"] == est1["vars_binary"] and trial["constraints"] == est1["constraints"])
        msg += (f"；试构建（T = 1，不含 N−1）：变量 {trial['vars']:,}、0-1 变量 {trial['binary']:,}、约束 {trial['constraints']:,}，耗时 {trial['build_s']} s"
                f"，{'与模板估算一致' if match else '与模板估算不一致（需排查）'}")
        if not match:
            out.append(_f(4, "W404", "warn", f"试构建计数与模板估算不一致：估算 {est1['vars_total']}/{est1['vars_binary']}/{est1['constraints']}，实际 {trial['vars']}/{trial['binary']}/{trial['constraints']}", None, "联系开发核对计数口径"))
    out.append(_f(4, "I403", "info", msg, data={"estimate": est, "estimate_t1": est1, "trial": trial}))
    return out, {"estimate": est, "trial": trial, "estimate_t1": est1}


# =====================================================================================
# 第 5 层 语义回译
# =====================================================================================
def _spec_item_texts(spec: ModelSpec) -> list[tuple[str, str]]:
    n = spec.omega.periods
    items = [("omega", omega_zh(spec.omega))]
    items += [(d.id, dp_zh(d, n)) for d in spec.delta_pi]
    items += [(s.id, s_zh(s)) for s in spec.structural]
    return items


def layer5(spec: ModelSpec, ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    text = spec.instruction
    # W501：evidence 不在原文（疑似幻觉）
    for it in [*spec.delta_pi, *spec.structural]:
        if (it.origin or "").startswith("negotiation"):      # 协商建议由系统按风险原因生成，没有原文依据，不按“幻觉”查
            continue
        ev = it.evidence or ""
        if not ev.strip():
            out.append(_f(5, "W501", "warn", f"{it.id} 没有原文依据（evidence 为空）：疑似凭空添加", it.id, "补充从指令原文逐字摘出的片段，或删除这一项"))
        elif ev not in text:
            out.append(_f(5, "W501", "warn", f"{it.id} 的原文依据“{ev}”不在指令原文中：疑似幻觉", it.id, "核对这一项是否真是指令要求的；evidence 必须逐字取自原文"))
    # W502：遗漏——独立抽取指令里的对象与要求，检查是否进入规格
    objs = extract_objects(text, ctx.snap, ctx.topo)
    kws = extract_keywords(text)
    in_spec_objs: set[str] = {d.target for d in spec.delta_pi}
    for s in spec.structural:
        in_spec_objs.update(str(b) for b in (s.params or {}).get("branches") or [])
    for o in objs:
        cands = o.candidates if o.status == "ambiguous" else ([o.object_id] if o.object_id else [])
        if cands and not (set(cands) & in_spec_objs):
            out.append(_f(5, "W502", "warn", f"指令里提到“{o.text}”（{'、'.join(cands[:4])}），但没有进入规格：疑似遗漏", None, "补一条对应的修改，或确认它只是背景描述"))
    all_evidence = " ".join((it.evidence or "") for it in [*spec.delta_pi, *spec.structural])
    miss_seen: set[str] = set()

    def miss(kind: str, kwtext: str, hint: str) -> None:
        key = f"{kind}:{kwtext}"
        if key not in miss_seen:
            miss_seen.add(key)
            out.append(_f(5, "W502", "warn", f"指令里的“{kwtext}”（{kind}）没有进入规格：疑似遗漏", None, hint))

    ops_in_spec = {s.op_id for s in spec.structural}
    for k in kws:
        if k.role == "inference":
            if not any(d.source == "inferred" and (k.text in (d.evidence or "")) for d in spec.delta_pi):
                miss("推断类修改", k.text, "补一条推断项，或确认无需建模")
        elif k.role == "outage":
            if not any(d.param in ("BR_STATUS", "GEN_STATUS") and (k.text in (d.evidence or "")) for d in spec.delta_pi):
                miss("检修停运", k.text, "补一条 BR_STATUS / GEN_STATUS 置 0")
        elif k.role == "structural":
            want = {"switching_penalty": "switching_penalty", "loss_min": "loss_min", "voltage_deviation": "voltage_deviation",
                    "section_limit": "section_limit", "fixed_topology": "multi_period_acopf"}.get(k.rule_id or "")
            covered = (want in ops_in_spec) or (want == "multi_period_acopf" and spec.omega.problem == "multi_period_acopf")
            if want and not covered:
                miss("结构要求", k.text, f"补一个结构算子 {want}")
        elif k.rule_id == "n_minus_1_on" and not spec.omega.n_minus_1:
            miss("N−1", k.text, "把 ω 的 N−1 开关打开")
        elif k.rule_id == "n_minus_1_off" and spec.omega.n_minus_1:
            out.append(_f(5, "W502", "warn", f"指令写了“{k.text}”（不要求 N−1），但规格里 N−1 为开启", None, "核对 ω 的 N−1 设置"))
    for m in match_switching_limit(text):
        want = "switching_limit_total" if m["total"] else "switching_limit_per_period"
        if want not in ops_in_spec:
            miss("开关次数限制", m["text"], f"补一个结构算子 {want}")
    # I503：规格逐条翻回中文，与原指令并排
    items = [{"id": i, "text": t} for i, t in _spec_item_texts(spec)]
    out.append(_f(5, "I503", "info", "规格已逐条翻回中文，与原指令并排显示（见下表）", None, None,
                  data={"instruction": text, "items": items}))
    return out


def external_findings(spec: ModelSpec) -> tuple[list[Finding], dict]:
    """去幻觉方法（接口预留）：POST {METHOD_ENDPOINT}/check，响应 findings 合并进第 5 层并注明来源。"""
    ep = settings.method_endpoint
    if not ep:
        return [], {"state": "none", "label": "外部方法：未接入"}
    try:
        r = httpx.post(f"{ep}/check", json={"instruction": spec.instruction, "spec": spec.model_dump()}, timeout=20)
        r.raise_for_status()
        raw = r.json()
        items = raw.get("findings", raw) if isinstance(raw, dict) else raw
        res = []
        for it in items or []:
            lv = it.get("level", "warn")
            lv = {"error": "error", "warn": "warn", "warning": "warn", "info": "info"}.get(lv, "warn")
            res.append(Finding(layer=5, code=str(it.get("code", "X501")), level=lv, message=str(it.get("message", "")),  # type: ignore[arg-type]
                               item_id=it.get("item_id"), suggestion=it.get("suggestion"), source="动态建模与去幻觉方法"))
        return res, {"state": "connected", "label": f"外部方法：已接入（{len(res)} 条）"}
    except Exception as e:  # noqa: BLE001
        return [Finding(layer=5, code="W599", level="warn", message=f"外部去幻觉方法调用失败：{e}", source="动态建模与去幻觉方法")], \
            {"state": "error", "label": "外部方法：调用失败"}


# =====================================================================================
# 总入口
# =====================================================================================
def run_checks(spec: ModelSpec, ctx: CheckContext, code: str | None = None) -> dict:
    f1 = layer1(spec, ctx)
    f2 = layer2(spec, ctx)
    f3 = layer3(spec, ctx)
    f4, build_info = layer4(spec, ctx, code)
    f5 = layer5(spec, ctx)
    ext, ext_state = external_findings(spec)
    f5 += ext
    layers = []
    for no, fs in ((1, f1), (2, f2), (3, f3), (4, f4), (5, f5)):
        status = "red" if any(x.level == "error" for x in fs) else "yellow" if any(x.level == "warn" for x in fs) else "green"
        layers.append({"layer": no, "name": LAYERS[no], "status": status, "findings": [x.model_dump() for x in fs]})
    allf = [x for L in layers for x in L["findings"]]
    return {
        "level": compute_level(spec), "layers": layers,
        "has_error": any(x["level"] == "error" for x in allf),
        "has_warning": any(x["level"] == "warn" for x in allf),
        "counts": {"error": sum(x["level"] == "error" for x in allf), "warn": sum(x["level"] == "warn" for x in allf), "info": sum(x["level"] == "info" for x in allf)},
        "external": ext_state, "build": build_info,
    }

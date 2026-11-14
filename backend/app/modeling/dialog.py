"""对话层：各引擎共用。追问生成、回答应用、层级与 evidence 位置。

规格草稿里还没确定的字段记在每一项的 pending_fields（periods / value / target），
追问列表由它们派生；回答追问就是把值写回条目并移除对应的 pending 字段。
"""
from __future__ import annotations

import re

from ..config import knowledge
from ..data.snapshot import parse_id
from ..spec.level import compute_level_from
from ..spec.schema import DeltaPi, StructuralOp
from ..spec.whitelist import COMPONENT_LABEL, DIRECTION_LABEL, ID_PREFIX, WHITELIST, param_info, validate_delta_pi
from .magnitude import parse_magnitude, parse_periods_answer
from .state import AnswerRecord, ParseContext, ParseResult, PendingIntent, Option, Question

MANUAL = "__manual__"
DEFAULT = "__default__"
ALL_PERIODS = "__all__"


# ---------------------------------------------------------------------------------------
# 派生：未决字段、追问
# ---------------------------------------------------------------------------------------
def default_value_for(component: str, param: str) -> float | None:
    """规程默认值：读 knowledge.yaml 的 default_value（现在全部留空）。"""
    for r in knowledge()["inference_rules"]:
        if r["component"] == component and r["param"] == param:
            return r.get("default_value")
    return None


def pending_unresolved(res: ParseResult) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in res.pending:
        f = ["target"]
        if p.periods_unresolved:
            f.append("periods")
        if p.source == "inferred" and p.value is None:
            f.append("value")
        out[p.id] = f
    for d in res.delta_pi:
        if d.pending_fields:
            out[d.id] = list(d.pending_fields)
    for s in res.structural:
        if s.pending_fields:
            out[s.id] = list(s.pending_fields)
    return out


def _snippet(ev: str, n: int = 24) -> str:
    return ev if len(ev) <= n else ev[:n] + "…"


def period_options(ctx: ParseContext) -> list[Option]:
    w = ctx.window
    opts = [Option(label=f"第{t}时段 {w.period_label(t)}", value=str(t)) for t in range(1, ctx.periods + 1)]
    opts.append(Option(label="全部时段", value=ALL_PERIODS))
    return opts


def build_questions(res: ParseResult, ctx: ParseContext) -> list[Question]:
    """所有未决项对应的追问（不受“是否追问 / 最多轮数”设置影响）。"""
    qs: list[Question] = []
    for p in res.pending:
        who = p.label or f"{COMPONENT_LABEL[p.component]}"
        qs.append(Question(
            id=f"q-{p.id}-target", field="target", item_id=p.id,
            text=f"“{_snippet(p.evidence)}”没有写明具体对象，请指明{COMPONENT_LABEL[p.component]}编号（如 {ID_PREFIX[p.component]}43）",
            options=[Option(label=c, value=c) for c in p.candidates] + ([Option(label=f"全部（{len(p.candidates)} 个）", value="all:" + ",".join(p.candidates))] if len(p.candidates) > 1 else []),
            allow_free_text=True, free_text_hint=f"填写{who}编号，多个用逗号分隔",
            basis="、".join(p.inference_chain) if p.inference_chain else None))
        if p.periods_unresolved:
            qs.append(_period_question(p.id, p.evidence, ctx, None))
        if p.source == "inferred" and p.value is None:
            qs.append(_value_question(p.id, p.component, p.param, p.direction, p.evidence, p.inference_chain, p.label))
    for d in res.delta_pi:
        for f in d.pending_fields:
            if f == "periods":
                qs.append(_period_question(d.id, d.evidence, ctx, d.target))
            elif f == "value":
                qs.append(_value_question(d.id, d.component, d.param, d.direction, d.evidence, d.inference_chain, d.target))
            elif f == "target":
                qs.append(Question(id=f"q-{d.id}-target", field="target", item_id=d.id, text=f"{d.id} 的对象需要确认",
                                   allow_free_text=True, free_text_hint="填写对象编号"))
    for s in res.structural:
        for f in s.pending_fields:
            qs.append(_struct_question(s, f))
    return qs


def _period_question(item_id: str, evidence: str, ctx: ParseContext, target: str | None) -> Question:
    w = ctx.window
    st = w.start.strftime("%m-%d %H:%M") if w.start else "未知"
    who = f"{target} " if target else ""
    return Question(
        id=f"q-{item_id}-periods", field="periods", item_id=item_id, multi=True,
        text=f"“{_snippet(evidence)}”{('（' + who.strip() + '）') if who else ''}对应哪些时段？（起始 {st}，{ctx.periods} 个时段 × {w.step_min} 分钟，可多选）",
        options=period_options(ctx), allow_free_text=True, free_text_hint="也可直接写：5-12 或 19:00-20:00")


def _value_question(item_id: str, component: str, param: str, direction: str | None, evidence: str,
                    chain: list[str] | None, target: str | None) -> Question:
    info = param_info(component, param) or {}
    dv = default_value_for(component, param)
    label = info.get("label", param)
    dlabel = {"increase": "上调", "decrease": "下降"}.get(direction or "", "调整")
    return Question(
        id=f"q-{item_id}-value", field="value", item_id=item_id,
        text=f"{(target + ' 的') if target else ''}{label}{dlabel}幅度按多少考虑？",
        options=[Option(label="按规程默认值", value=DEFAULT, disabled=dv is None, hint=None if dv is not None else "规程默认值未配置"),
                 Option(label="手动输入", value=MANUAL)],
        allow_free_text=True, free_text_hint="例如：降低 20% / 0.8（缩放系数）/ 800 MW",
        basis=" → ".join(chain) if chain else None)


def _struct_question(s: StructuralOp, f: str) -> Question:
    hint = {"limit_mw": ("断面有功限额是多少 MW？", "例如 300"), "branches": ("断面由哪些支路组成？", "例如 L428,L429"),
            "k": ("开关操作次数上限 k 是多少？", "正整数"), "K": ("开关操作总次数上限 K 是多少？", "正整数"),
            "beta": ("目标项系数 β 取多少？", "正数；留空则用配置默认值"),
            "max_switch": ("全部时段机组启停总次数上限是多少？", "正整数"),
            "unit_cost": ("发电成本单价是多少（元/MWh）？断面里没有成本数据，需要你给出", "正数，例如 300"),
            "penalty": ("惩罚 / 代价系数是多少（元/MWh）？", "正数，例如 1000"),
            "ramp_pct": ("爬坡上限是 PMAX 的百分之几 / 时段？", "正数；留空表示不限")}.get(f, (f"请补充参数 {f}", ""))
    return Question(id=f"q-{s.id}-{f}", field="other", item_id=s.id, param=f, text=hint[0], allow_free_text=True,
                    free_text_hint=hint[1], blocking=f not in ("beta", "ramp_pct"))


# ---------------------------------------------------------------------------------------
# 回答
# ---------------------------------------------------------------------------------------
def _find_item(res: ParseResult, item_id: str):
    for d in res.delta_pi:
        if d.id == item_id:
            return d
    for s in res.structural:
        if s.id == item_id:
            return s
    for p in res.pending:
        if p.id == item_id:
            return p
    return None


def _next_dp_id(res: ParseResult) -> str:
    n = max([int(d.id.split("-")[1]) for d in res.delta_pi if re.fullmatch(r"dp-\d+", d.id)] + [0])
    return f"dp-{n + 1}"


def _parse_targets(answer: str, comp: str, ctx: ParseContext) -> list[str]:
    ans = answer.strip()
    if ans.startswith("all:"):
        ans = ans[4:]
    ids = [x.strip().upper() for x in re.split(r"[,，、;；\s]+", ans) if x.strip()]
    if not ids:
        raise ValueError("请填写对象编号")
    out = []
    for i in ids:
        if re.fullmatch(r"\d+", i):  # 只写了数字：按期望的对象类型补前缀
            i = ID_PREFIX[comp] + i
        p = parse_id(i)
        if not p:
            raise ValueError(f"无法识别对象编号“{i}”，格式应为 B43 / L155 / G237")
        if p[0] != comp:
            raise ValueError(f"{i} 是{COMPONENT_LABEL[p[0]]}，这里需要{COMPONENT_LABEL[comp]}编号")
        out.append(i)
    return out


def apply_answer(res: ParseResult, question_id: str, answer: str, ctx: ParseContext) -> ParseResult:
    """把回答写回草稿。校验失败抛 ValueError，不修改状态。"""
    q = next((x for x in build_questions(res, ctx) if x.id == question_id), None)
    if q is None:
        raise ValueError(f"没有这个追问：{question_id}（可能已经回答过）")
    item = _find_item(res, q.item_id or "")
    if item is None:
        raise ValueError(f"追问对应的条目不存在：{q.item_id}")
    shown = answer
    if q.field == "periods":
        ps = parse_periods_answer(ALL_PERIODS if answer == ALL_PERIODS else answer, ctx.window, ctx.periods)
        if isinstance(item, PendingIntent):
            item.periods, item.periods_unresolved = ps, False
        elif isinstance(item, DeltaPi):
            item.periods = ps
            item.pending_fields = [f for f in item.pending_fields if f != "periods"]
        shown = "全部时段" if not ps else "时段 " + ",".join(map(str, ps))
    elif q.field == "value":
        comp, param, direction = item.component, item.param, item.direction  # type: ignore[union-attr]
        if answer == DEFAULT:
            dv = default_value_for(comp, param)
            if dv is None:
                raise ValueError("规程默认值未配置，请手动输入幅度")
            op, val = "scale", float(dv)
            shown = f"按规程默认值 {dv:g}"
        elif answer == MANUAL:
            raise ValueError("请先输入幅度")
        else:
            op, val = parse_magnitude(answer, direction)
        if isinstance(item, PendingIntent):
            item.operation, item.value = op, val  # type: ignore[assignment]
        else:
            trial = item.model_copy(update={"operation": op, "value": val})
            errs = validate_delta_pi(trial)
            if errs:
                raise ValueError(errs[0][1])
            item.operation, item.value = op, val  # type: ignore[assignment]
            item.pending_fields = [f for f in item.pending_fields if f != "value"]
            item.confirmed = True          # 用户亲自给出方向与幅度，即视为确认
    elif q.field == "target":
        if isinstance(item, PendingIntent):
            targets = _parse_targets(answer, item.component, ctx)
            res.pending = [p for p in res.pending if p.id != item.id]
            for t in targets:
                pend = []
                if item.periods_unresolved:
                    pend.append("periods")
                if item.source == "inferred" and item.value is None:
                    pend.append("value")
                res.delta_pi.append(DeltaPi(
                    id=_next_dp_id(res), component=item.component, target=t, param=item.param, operation=item.operation,
                    direction=item.direction, value=item.value, periods=list(item.periods), source=item.source,
                    evidence=item.evidence, inference_chain=item.inference_chain, confirmed=item.source == "inferred" and item.value is not None,
                    pending_fields=pend))
            shown = "、".join(targets)
        elif isinstance(item, DeltaPi):
            targets = _parse_targets(answer, item.component, ctx)
            item.target = targets[0]
            item.pending_fields = [f for f in item.pending_fields if f != "target"]
            shown = targets[0]
    else:  # 算子参数
        assert isinstance(item, StructuralOp) and q.param
        _apply_struct_param(item, q.param, answer, ctx)
        item.pending_fields = [f for f in item.pending_fields if f != q.param]
    res.answers.append(AnswerRecord(question_id=question_id, question=q.text, answer=shown, raw=answer))
    return finalize(res, ctx)


def _apply_struct_param(s: StructuralOp, param: str, answer: str, ctx: ParseContext) -> None:
    a = answer.strip()
    if param in ("k", "K", "max_switch"):
        if not re.fullmatch(r"\d+", a) or int(a) < 1:
            raise ValueError("请输入正整数")
        s.params[param] = int(a)
    elif param in ("unit_cost", "penalty", "ramp_pct"):
        if a == "" and param == "ramp_pct":
            s.params[param] = None
        else:
            m = re.fullmatch(r"\d+(?:\.\d+)?", a)
            if not m or float(a) <= 0:
                raise ValueError("请输入大于 0 的数值")
            s.params[param] = float(a)
    elif param == "limit_mw":
        m = re.search(r"\d+(?:\.\d+)?", a)
        if not m or float(m.group()) <= 0:
            raise ValueError("请输入大于 0 的数值（MW）")
        s.params[param] = float(m.group())
    elif param == "beta":
        if a == "":
            s.params[param] = None
        else:
            m = re.fullmatch(r"\d+(?:\.\d+)?", a)
            if not m or float(a) <= 0:
                raise ValueError("β 需为正数")
            s.params[param] = float(a)
    elif param == "branches":
        ids = [x.strip().upper() for x in re.split(r"[,，、;；\s]+", a) if x.strip()]
        if not ids or any(not re.fullmatch(r"L\d+", i) for i in ids):
            raise ValueError("请填写 L 编号，如 L428,L429")
        s.params[param] = ids
    else:
        s.params[param] = a


# ---------------------------------------------------------------------------------------
# 收尾
# ---------------------------------------------------------------------------------------
def evidence_span(instruction: str, evidence: str) -> list[int] | None:
    if not evidence:
        return None
    i = instruction.find(evidence)
    return [i, i + len(evidence)] if i >= 0 else None


def finalize(res: ParseResult, ctx: ParseContext) -> ParseResult:
    """同步未决字段、判级、生成追问（受设置约束）、计算 evidence 在原文中的位置。"""
    for d in res.delta_pi:
        d.pending_fields = [f for f in d.pending_fields if f in ("periods", "value", "target")]
    res.unresolved = pending_unresolved(res)
    res.level = compute_level_from(res.delta_pi, res.structural)
    for iid, item_ev in [(d.id, d.evidence) for d in res.delta_pi] + [(s.id, s.evidence) for s in res.structural] + [(p.id, p.evidence) for p in res.pending]:
        if iid not in res.evidence_spans:
            sp = evidence_span(res.instruction, item_ev)
            if sp:
                res.evidence_spans[iid] = sp
    live = {d.id for d in res.delta_pi} | {s.id for s in res.structural} | {p.id for p in res.pending}
    res.evidence_spans = {k: v for k, v in res.evidence_spans.items() if k in live}

    allq = build_questions(res, ctx)
    res.suppressed = None
    if allq:
        new_ids = [q.id for q in allq if q.id not in res.asked]
        if new_ids:
            res.rounds += 1
            res.asked.extend(new_ids)
        if not ctx.ask_enabled:
            res.questions, res.suppressed = [], "追问已关闭：待确认项请直接在规格表里补全"
        elif res.rounds > ctx.max_rounds:
            res.questions, res.suppressed = [], f"已达最多追问 {ctx.max_rounds} 轮：余下待确认项请直接在规格表里补全"
        else:
            res.questions = allq
    else:
        res.questions = []
    return res

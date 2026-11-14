"""判级规则（指令 5.1）：由程序从规格推出，不让大模型自报。

- 有推断项：Δπ 中存在 source = inferred。
- 有结构修改：s 非空。ω 的默认设置不算；指令里“满足 N−1”只是确认 ω.n_minus_1，不算结构修改。
- L1：无推断、无结构；L2：有推断、无结构；L3：无推断、有结构；L4：有推断、有结构。
- 没有任何 Δπ 和 s 时，层级显示“待追问”。
- 人工改选只覆盖显示的层级，同时保留程序判出的层级；测评模式按程序判级统计。
"""
from __future__ import annotations

from .schema import DeltaPi, ModelSpec, StructuralOp

PENDING = "待追问"

LEVEL_RULES = {
    "L1": "参数修改全部明确，且不改结构",
    "L2": "含需要从场景推断的参数，不改结构",
    "L3": "参数修改全部明确，另有结构修改",
    "L4": "含推断参数，且有结构修改",
}


def compute_level_from(delta_pi: list[DeltaPi], structural: list[StructuralOp]) -> str:
    if not delta_pi and not structural:
        return PENDING
    has_inferred = any(d.source == "inferred" for d in delta_pi)
    has_struct = bool(structural)
    if has_inferred and has_struct:
        return "L4"
    if has_inferred:
        return "L2"
    if has_struct:
        return "L3"
    return "L1"


def compute_level(spec: ModelSpec) -> str:
    """程序判出的层级（统计用）。"""
    return compute_level_from(spec.delta_pi, spec.structural)


def display_level(spec: ModelSpec) -> str:
    """界面显示的层级：人工改选覆盖显示，程序判级另存。"""
    return spec.level_override.level if spec.level_override else compute_level(spec)


def level_reasons(spec: ModelSpec) -> dict:
    """判级理由，给四宫格下方的说明。"""
    inferred = [d.id for d in spec.delta_pi if d.source == "inferred"]
    structural = [s.id for s in spec.structural]
    lvl = compute_level(spec)
    if lvl == PENDING:
        text = "没有任何参数修改或结构修改，需要追问后才能判级"
    else:
        a = f"推断项 {', '.join(inferred)}" if inferred else "参数修改全部明确"
        b = f"结构修改 {', '.join(structural)}" if structural else "无结构修改"
        text = f"判为 {lvl}：{a}；{b}"
        if spec.omega.n_minus_1:
            text += "（N−1 为 ω 的默认设置，不算结构修改）"
    return {"level": lvl, "display": display_level(spec), "overridden": spec.level_override is not None,
            "inferred": inferred, "structural": structural, "text": text}

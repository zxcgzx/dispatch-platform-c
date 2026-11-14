"""公式页：基础模型 B1–B9 逐块 LaTeX，受影响的块高亮，顶部列出“本版改动”（dp-1、s-1 标签）。"""
from __future__ import annotations

from ..spec.schema import ModelSpec
from . import operators as ops
from .describe import AFFECTS, STRUCT_AFFECTS, dp_latex, s_latex, s_title
from .rundata import effective_op


def fixed_topology(spec: ModelSpec) -> bool:
    """固定拓扑：ω.problem 为 AC-OPF，或 s 里有 multi_period_acopf 算子。"""
    return spec.omega.problem == "multi_period_acopf" or any(s.op_id == "multi_period_acopf" for s in spec.structural)


def build_formulas(spec: ModelSpec) -> dict:
    n = spec.omega.periods
    hl: dict[str, list[str]] = {}
    changes: list[dict] = []
    for dp in spec.delta_pi:
        blocks = AFFECTS.get((dp.component, dp.param), [])
        for b in blocks:
            hl.setdefault(b, []).append(dp.id)
        changes.append({
            "id": dp.id, "kind": "dp", "title": f"{dp.target}.{dp.param}", "latex": dp_latex(dp, n),
            "inferred": dp.source == "inferred", "confirmed": dp.confirmed, "pending": dp.source == "inferred" and effective_op(dp) is None,
            "affects": blocks,
        })
    new_blocks: list[dict] = []
    obj_terms: list[dict] = []
    for s in spec.structural:
        affects = STRUCT_AFFECTS.get(s.op_id, [])
        for b in affects:
            hl.setdefault(b, []).append(s.id)
        known = s.op_id in ops.operators()
        entry = {"id": s.id, "kind": "s", "title": s_title(s), "latex": s_latex(s), "inferred": False, "confirmed": True,
                 "pending": bool(s.pending_fields), "affects": affects, "custom": bool(s.custom_code) or not known,
                 "op_kind": s.kind}
        changes.append(entry)
        if s.kind == "constraint" or s.kind == "problem" or not known:
            new_blocks.append({"id": s.id, "title": s_title(s), "latex": s_latex(s), "custom": entry["custom"], "kind": s.kind})
        elif s.kind == "objective":
            obj_terms.append({"id": s.id, "latex": s_latex(s)})
    base = ops.base_objective()
    obj_latex = base["latex"] + "".join(" " + t["latex"] for t in obj_terms)
    blocks = []
    for b in ops.base_blocks():
        if b.get("condition") == "n_minus_1" and not spec.omega.n_minus_1:
            continue
        blocks.append({
            "id": b["id"], "title": b["title"], "latex": b["latex"], "note": b.get("note"),
            "abstract": bool(b.get("abstract")), "highlight": b["id"] in hl, "changed_by": hl.get(b["id"], []),
        })
    return {
        "objective": {"id": "OBJ", "title": base["title"], "latex": obj_latex, "pending": bool(base.get("pending")),
                      "note": base.get("note"), "terms": obj_terms},
        "changes": changes, "blocks": blocks, "new_blocks": new_blocks, "fixed_topology": fixed_topology(spec),
        "symbols": r"集合：$\mathcal N$ 母线、$\mathcal G$ 机组、$\mathcal L$ 支路、$\mathcal L^{s}$ 可开断集合、$\mathcal T=\{1,\dots,"
                   + str(n) + r"\}$ 时段、$\mathcal C$ 事故集；$P^{f},Q^{f}$ 首端潮流，$P^{r},Q^{r}$ 末端潮流（用 r 避免和时段 t 混淆）；$z_{l,t}$ 为 0-1 变量。",
    }


def to_tex_file(spec: ModelSpec, f: dict) -> str:
    """model.tex：纯 LaTeX 文本，存档用。"""
    lines = [f"% 任务 {spec.task_id} v{spec.version}  自动生成", r"\section*{本版改动}"]
    for c in f["changes"]:
        lines.append(rf"% [{c['id']}] {c['title']}")
        lines.append(r"\[ " + c["latex"] + r" \]")
    lines.append(r"\section*{目标（待确认）}")
    lines.append(r"\[ " + f["objective"]["latex"] + r" \]")
    lines.append(r"\section*{基础模型}")
    for b in f["blocks"]:
        lines.append(rf"% [{b['id']}] {b['title']}" + ("（高亮：" + ",".join(b["changed_by"]) + "）" if b["highlight"] else ""))
        lines.append(r"\[ " + b["latex"] + r" \]")
    for b in f["new_blocks"]:
        lines.append(rf"% [{b['id']}] 新增 {b['title']}")
        lines.append(r"\[ " + b["latex"] + r" \]")
    return "\n".join(lines) + "\n"

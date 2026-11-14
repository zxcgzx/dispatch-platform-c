"""两个版本的规格差异：新增、删除、修改的条目（版本链“点击看差异”）。

Δπ 按 (对象, 参数) 配对（同键多条按出现顺序），s 按 (op_id) 配对；id 在版本间可能变，所以不按 id 配对。
"""
from __future__ import annotations

from typing import Any

DP_FIELDS = ["operation", "direction", "value", "periods", "source", "confirmed", "evidence", "inference_chain"]
S_FIELDS = ["kind", "params", "source", "evidence", "custom_code"]
OMEGA_FIELDS = ["system", "problem", "periods", "step_min", "n_minus_1", "contingency_rule", "switchable_rule"]
R_FIELDS = ["solver", "time_limit_s", "tolerance", "outputs"]


def _keyed(items: list[dict], keyf) -> dict[tuple, dict]:
    seen: dict[tuple, int] = {}
    out: dict[tuple, dict] = {}
    for it in items:
        k = keyf(it)
        n = seen.get(k, 0)
        seen[k] = n + 1
        out[(*k, n)] = it
    return out


def _changes(a: dict, b: dict, fields: list[str]) -> list[dict]:
    return [{"field": f, "a": a.get(f), "b": b.get(f)} for f in fields if a.get(f) != b.get(f)]


def _diff_items(la: list[dict], lb: list[dict], keyf, fields: list[str], label) -> dict[str, list]:
    ka, kb = _keyed(la, keyf), _keyed(lb, keyf)
    added = [{"key": label(kb[k]), "id": kb[k].get("id"), "item": kb[k]} for k in kb if k not in ka]
    removed = [{"key": label(ka[k]), "id": ka[k].get("id"), "item": ka[k]} for k in ka if k not in kb]
    modified = []
    for k in ka:
        if k in kb:
            ch = _changes(ka[k], kb[k], fields)
            if ch:
                modified.append({"key": label(kb[k]), "id_a": ka[k].get("id"), "id_b": kb[k].get("id"), "changes": ch})
    return {"added": added, "removed": removed, "modified": modified}


def spec_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    dp = _diff_items(a.get("delta_pi", []), b.get("delta_pi", []), lambda x: (x["target"], x["param"]), DP_FIELDS,
                     lambda x: f"{x['target']}.{x['param']}")
    st = _diff_items(a.get("structural", []), b.get("structural", []), lambda x: (x["op_id"],), S_FIELDS, lambda x: x["op_id"])
    omega = _changes(a.get("omega", {}), b.get("omega", {}), OMEGA_FIELDS)
    req = _changes(a.get("solver_req", {}), b.get("solver_req", {}), R_FIELDS)
    total = sum(len(v) for v in (*dp.values(), *st.values())) + len(omega) + len(req)
    return {
        "a": a.get("version"), "b": b.get("version"), "delta_pi": dp, "structural": st, "omega": omega, "solver_req": req,
        "instruction_changed": a.get("instruction") != b.get("instruction"),
        "instruction_a": a.get("instruction"), "instruction_b": b.get("instruction"),
        "change_reason_b": b.get("change_reason"), "total": total,
    }

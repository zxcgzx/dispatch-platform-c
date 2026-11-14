"""算子库访问与模板渲染（LaTeX / 代码）。模板里的 {k} {K} {beta} {limit_mw} {branches} 等只替换已知参数名，
避免和 LaTeX 的花括号冲突。"""
from __future__ import annotations

import re
from typing import Any

from ..config import app_config, operators_config

_TOKEN = re.compile(r"\{(k|K|beta|limit_mw|branches|branches_py|dir_lhs|dir_expr|ramp_pct|ramp_pct_py|max_switch|unit_cost|penalty)\}")


def operators() -> dict[str, dict]:
    return operators_config()["operators"]


def operator_json() -> dict[str, dict]:
    """给界面（算子卡片表单）和大模型提示词用的算子库摘要（不含代码模板）。"""
    return {k: {"name": v["name"], "kind": v["kind"], "meaning": v["meaning"], "params": v.get("params", {})} for k, v in operators().items()}


def base_blocks() -> list[dict]:
    return operators_config()["base"]["blocks"]


def base_objective() -> dict:
    return operators_config()["base"]["objective"]


def beta_default() -> float:
    return float(app_config()["objective"]["beta_default"])


def _num(x: Any) -> str:
    if isinstance(x, bool):
        return str(int(x))
    if isinstance(x, (int,)) or (isinstance(x, float) and x.is_integer()):
        return str(int(x))
    return f"{x:g}"


def effective_params(op_id: str, params: dict) -> dict:
    """补默认值：direction 缺省 forward；beta 为空用配置默认值。"""
    p = dict(params or {})
    spec = operators().get(op_id, {}).get("params", {})
    for name, d in spec.items():
        if p.get(name) is None and "default" in d:
            p[name] = d["default"]
    if "beta" in spec and p.get("beta") is None:
        p["beta"] = beta_default()
    return p


def _sub(template: str, mapping: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: mapping.get(m.group(1), m.group(0)), template)


def _mapping(op_id: str, params: dict, latex: bool) -> dict[str, str]:
    p = effective_params(op_id, params)
    m: dict[str, str] = {}
    for key in ("k", "K"):
        if p.get(key) is not None:
            m[key] = _num(p[key])
    if "beta" in p:
        m["beta"] = _num(p["beta"])
    if p.get("limit_mw") is not None:
        m["limit_mw"] = _num(p["limit_mw"])
    for key in ("ramp_pct", "max_switch", "unit_cost", "penalty"):
        if p.get(key) is not None:
            m[key] = _num(p[key])
    m["ramp_pct_py"] = "None" if p.get("ramp_pct") is None else _num(p["ramp_pct"])
    if latex and p.get("ramp_pct") is None:
        m["ramp_pct"] = r"\infty"
    brs = p.get("branches") or []
    m["branches"] = ",".join(brs)
    m["branches_py"] = "[" + ", ".join(repr(b) for b in brs) + "]"
    d = p.get("direction", "forward")
    if latex:
        m["dir_lhs"] = {"forward": r"\sum_{l\in S}P^{f}_{l,t}", "reverse": r"-\sum_{l\in S}P^{f}_{l,t}",
                        "abs": r"\left|\sum_{l\in S}P^{f}_{l,t}\right|"}.get(d, r"\sum_{l\in S}P^{f}_{l,t}")
    else:
        m["dir_expr"] = {"forward": "s <= SECTION_LIMIT", "reverse": "-s <= SECTION_LIMIT",
                         "abs": "pyo.inequality(-SECTION_LIMIT, s, SECTION_LIMIT)"}.get(d, "s <= SECTION_LIMIT")
    return m


def render_latex(op_id: str, params: dict) -> str:
    op = operators()[op_id]
    p = effective_params(op_id, params)
    tex = _sub(op["latex"], _mapping(op_id, params, True))
    if "beta" in op.get("params", {}) and (params or {}).get("beta") is None:
        tex = tex.replace(_num(p["beta"]), r"\beta", 1)  # β 为空：公式里写符号，代码里用默认值
    return tex


def render_code(op_id: str, params: dict) -> str:
    return _sub(operators()[op_id]["code"], _mapping(op_id, params, False)).rstrip("\n")


def needs_dz(ops: list[str]) -> bool:
    return any(o in ("switching_limit_per_period", "switching_limit_total", "switching_penalty") for o in ops)


OBJECTIVE_COEF = {"cost_economic": "unit_cost", "reliability_nm1": "penalty", "renewable_accommodation": "penalty"}

"""课题 3 风险（接口预留，当前本地规则模拟）与协商式调整建议。

- 配置了 RISK_ENDPOINT：POST {task_id, version, metrics, result_summary}，响应 {risk_level: 低|中|高, reasons: [], reward: number|null}。
- 没配置：本地规则——存在 ρ ≥ 100% 或 N−1 筛查不通过为“高”；存在 ρ ≥ 80% 或电压越限为“中”；其他为“低”。
- 协商：按风险原因生成建议，每条建议是一条待确认的 Δπ 或 s；建议中的数值一律留空，由用户填写。
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings


def local_risk(metrics: dict) -> dict:
    """本地规则模拟。metrics 来自 evaluate：{load_rate, voltage, n1}，值可能为 None（调整后 mock 时）。"""
    reasons: list[dict] = []
    level = "低"
    lr, vo, n1 = metrics.get("load_rate"), metrics.get("voltage"), metrics.get("n1")
    if lr and lr.get("n_violation", 0) > 0:
        level = "高"
        reasons.append({"code": "R-RHO100", "text": f"{lr['n_violation']} 条支路负载率 ρ ≥ {lr['violation_threshold']:.0%}", "level": "高"})
    if n1 and n1.get("failed_count", 0) > 0:
        level = "高"
        reasons.append({"code": "R-N1", "text": f"N−1 直流筛查不通过：{n1['failed_count']}/{n1['evaluated']} 个事故有支路越限", "level": "高"})
    if lr and lr.get("n_overload", 0) > 0:
        if level == "低":
            level = "中"
        reasons.append({"code": "R-RHO80", "text": f"{lr['n_overload']} 条支路负载率 ρ ≥ {lr['overload_threshold']:.0%}", "level": "中"})
    if vo and vo.get("n_out", 0) > 0:
        if level == "低":
            level = "中"
        reasons.append({"code": "R-VOLT", "text": f"{vo['n_out']} 个母线电压越出 [VMIN, VMAX]（基态已有 {vo['n_above_vmax']} 个高于上限）", "level": "中"})
    if not reasons:
        reasons.append({"code": "R-OK", "text": "没有支路重载、N−1 筛查全部通过、电压均在范围内", "level": "低"})
    return {"risk_level": level, "reasons": reasons, "reward": None, "source": "课题 3 风险（本地规则）", "mode": "local"}


def assess(task_id: str, version: int, metrics: dict, result_summary: dict) -> dict:
    ep = settings.risk_endpoint
    if not ep:
        return local_risk(metrics)
    try:
        r = httpx.post(ep, timeout=20, json={"task_id": task_id, "version": version, "metrics": metrics, "result_summary": result_summary})
        r.raise_for_status()
        j = r.json()
        lv = j.get("risk_level")
        if lv not in ("低", "中", "高"):
            raise ValueError(f"risk_level 应为 低/中/高，实际为 {lv!r}")
        reasons = [{"code": "EXT", "text": str(x), "level": lv} if not isinstance(x, dict) else x for x in j.get("reasons", [])]
        return {"risk_level": lv, "reasons": reasons, "reward": j.get("reward"), "source": "课题 3 接口", "mode": "endpoint"}
    except Exception as e:  # noqa: BLE001
        out = local_risk(metrics)
        out["source"] = f"课题 3 接口调用失败（{e}），已回落到本地规则模拟"
        out["fallback"] = True
        return out


def suggestions(risk: dict, metrics: dict, spec: dict) -> list[dict]:
    """协商建议：每条是一条待确认的 Δπ 或 s；数值一律留空，由用户填写。

    返回 [{id, from_code, reason, kind: 'dp'|'s', item: {...}, fields_needed: [...]}]。
    """
    out: list[dict] = []
    codes = {r["code"] for r in risk.get("reasons", [])}
    n1 = metrics.get("n1") or {}
    lr = metrics.get("load_rate") or {}
    existing_ops = {s["op_id"] for s in spec.get("structural", [])}

    def add(from_code: str, reason: str, kind: str, item: dict, needed: list[str]) -> None:
        out.append({"id": f"r-{len(out) + 1}", "from_code": from_code, "reason": reason, "kind": kind, "item": item, "fields_needed": needed})

    if "R-N1" in codes:
        freq = [x["id"] for x in n1.get("frequent_violated", [])[:3]]
        if freq and "section_limit" not in existing_ops:
            add("R-N1", f"N−1 筛查中 {', '.join(freq)} 反复越限：把它们组成断面，加断面有功限额",
                "s", {"kind": "constraint", "op_id": "section_limit", "params": {"branches": freq, "limit_mw": None, "direction": "forward"}}, ["limit_mw"])
        if "switching_limit_per_period" not in existing_ops and not spec.get("omega", {}).get("problem") == "multi_period_acopf":
            add("R-N1", "N−1 不通过：追加每时段开关次数上限，限制方式变化幅度",
                "s", {"kind": "constraint", "op_id": "switching_limit_per_period", "params": {"k": None}}, ["k"])
    for b in [x["id"] for x in lr.get("top", []) if x["rho"] >= lr.get("violation_threshold", 1.0)][:3] if "R-RHO100" in codes else []:
        add("R-RHO100", f"{b} 负载率 ≥ 100%：收紧该支路的热稳限额以留出裕度（幅度由你填写）",
            "dp", {"component": "branch", "target": b, "param": "RATE_A", "operation": "scale", "value": None}, ["value"])
    if "R-VOLT" in codes:
        add("R-VOLT", "电压越限：收紧电压上限（取值由你填写，范围 0.8–1.2）",
            "dp", {"component": "bus", "target": None, "param": "VMAX", "operation": "set", "value": None}, ["target", "value"])
    if "R-RHO80" in codes and "R-RHO100" not in codes:
        for b in [x["id"] for x in lr.get("top", [])[:2]]:
            add("R-RHO80", f"{b} 负载率已 ≥ 80%：可收紧限额预留裕度（幅度由你填写）",
                "dp", {"component": "branch", "target": b, "param": "RATE_A", "operation": "scale", "value": None}, ["value"])
    return out

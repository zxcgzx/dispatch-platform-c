"""测评模式（M8）：导入测试集（JSON 或 CSV），选引擎，批量跑“解析 → 判级 → 校验”，默认不求解。

比对规则（规格级）：
  - 层级一致（按程序判级，不按人工改选）；
  - Δπ 按 target、param、operation 或 direction、value（相对误差 ≤ 1%）、periods 匹配；
  - s 按 op_id 和给出的参数匹配；
  - 标了 must_fail 的用例，M4 报出对应错误才算对。
报告：总体与按 L1–L4 分组的准确率、Δπ 的精确率与召回率、疑似幻觉数（W501 加 E101）、平均耗时；可导出 Markdown 和 CSV。
ProOPF 用求解目标值判对错；这里求解是黑盒，先做规格级比对，“目标值比对”等求解接入后再做（待开发）。
"""
from __future__ import annotations

import csv
import io
import json
import time
import uuid
from typing import Any

from ..checks.engine import CheckContext, run_checks
from ..modeling.demo_engine import DemoRuleEngine
from ..modeling.pipeline import make_context, spec_from_parse
from ..modeling.rundata import effective_op
from ..spec.level import compute_level

LEVELS = ["L1", "L2", "L3", "L4", "待追问"]
REL_TOL = 0.01


def parse_testset(raw: bytes | str, filename: str = "") -> dict:
    """JSON：{name, cases:[…]} 或直接 [...]；CSV 列：id,instruction,expected_level,expected_json,must_fail（expected_json 为 JSON 字符串）。"""
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    name = filename or "导入的测试集"
    if filename.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(text)))
        cases = []
        for i, r in enumerate(rows, start=1):
            if not (r.get("instruction") or "").strip():
                continue
            exp = {"delta_pi": [], "structural": []}
            if (r.get("expected_json") or "").strip():
                try:
                    exp = json.loads(r["expected_json"])
                except json.JSONDecodeError as e:
                    raise ValueError(f"CSV 第 {i} 行的 expected_json 不是合法 JSON：{e}")
            cases.append({"id": (r.get("id") or f"C{i}").strip(), "instruction": r["instruction"].strip(), "expected_level": (r.get("expected_level") or "").strip(),
                          "expected": exp, "must_fail": [x.strip() for x in (r.get("must_fail") or "").replace("；", ";").split(";") if x.strip()]})
        return {"name": name, "cases": cases}
    data = json.loads(text)
    cases = data["cases"] if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("测试集里没有用例")
    for c in cases:
        if "instruction" not in c or "expected_level" not in c:
            raise ValueError(f"用例 {c.get('id', '?')} 缺少 instruction 或 expected_level")
    return {"name": (data.get("name") if isinstance(data, dict) else None) or name, "cases": cases}


def _num_close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    if b == 0:
        return abs(a) < 1e-9
    return abs(a - b) / abs(b) <= REL_TOL


def _dp_match(got, exp: dict) -> bool:
    if got.target != exp["target"] or got.param != exp["param"]:
        return False
    if "direction" in exp and exp["direction"]:
        if got.source != "inferred" or got.direction != exp["direction"]:
            return False
    else:
        op = effective_op(got) if got.source == "explicit" else None
        if exp.get("operation") and (op is None or op[0] != exp["operation"]):
            return False
        if "value" in exp and not _num_close(op[1] if op else None, float(exp["value"]) if exp["value"] is not None else None):
            return False
    if "periods" in exp and sorted(got.periods) != sorted(exp["periods"]):
        return False
    return True


def _s_match(got, exp: dict) -> bool:
    if got.op_id != exp["op_id"]:
        return False
    for k, v in (exp.get("params") or {}).items():
        g = (got.params or {}).get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if not _num_close(float(g) if g is not None else None, float(v)):
                return False
        elif isinstance(v, list):
            if sorted(map(str, g or [])) != sorted(map(str, v)):
                return False
        elif g != v:
            return False
    return True


def compare(case: dict, spec, program_level: str, report: dict) -> dict:
    exp = case.get("expected") or {"delta_pi": [], "structural": []}
    exp_dp, exp_s = exp.get("delta_pi", []), exp.get("structural", [])
    level_ok = program_level == case["expected_level"]
    used: set[int] = set()
    tp = 0
    missing_dp = []
    for e in exp_dp:
        hit = next((i for i, g in enumerate(spec.delta_pi) if i not in used and _dp_match(g, e)), None)
        if hit is None:
            missing_dp.append(e)
        else:
            used.add(hit)
            tp += 1
    extra_dp = [g for i, g in enumerate(spec.delta_pi) if i not in used]
    used_s: set[int] = set()
    missing_s = []
    for e in exp_s:
        hit = next((i for i, g in enumerate(spec.structural) if i not in used_s and _s_match(g, e)), None)
        if hit is None:
            missing_s.append(e)
        else:
            used_s.add(hit)
    extra_s = [g for i, g in enumerate(spec.structural) if i not in used_s]
    codes = {f["code"] for L in report["layers"] for f in L["findings"] if f["level"] == "error"}
    allcodes = {f["code"] for L in report["layers"] for f in L["findings"]}
    must_fail = case.get("must_fail") or []
    fail_ok = all(c in codes for c in must_fail) if must_fail else True
    exp_find = [c for c in case.get("expected_findings", []) if c not in allcodes]
    forb_find = [c for c in case.get("forbidden_findings", []) if c in allcodes]
    spec_ok = not missing_dp and not extra_dp and not missing_s and not extra_s
    ok = level_ok and spec_ok and fail_ok and not exp_find and not forb_find
    return {
        "ok": ok, "level_ok": level_ok, "spec_ok": spec_ok, "must_fail_ok": fail_ok,
        "dp": {"expected": len(exp_dp), "got": len(spec.delta_pi), "tp": tp, "missing": missing_dp,
               "extra": [{"target": g.target, "param": g.param} for g in extra_dp]},
        "s": {"expected": len(exp_s), "got": len(spec.structural), "missing": missing_s, "extra": [g.op_id for g in extra_s]},
        "missing_findings": exp_find, "forbidden_findings": forb_find,
    }


def run_case(case: dict, engine_id: str, snapshot_id: str | None = None, skip_trial: bool = True) -> dict:
    t0 = time.perf_counter()
    out: dict[str, Any] = {"id": case.get("id"), "instruction": case["instruction"], "expected_level": case["expected_level"]}
    try:
        ctx = make_context(snapshot_id, ask_enabled=True)
        if engine_id == "demo":
            res = DemoRuleEngine().parse(case["instruction"], ctx)
        elif engine_id == "openai":
            from ..modeling.openai_engine import parse_with_fallback
            res = parse_with_fallback(case["instruction"], ctx)
        elif engine_id == "external":
            from ..modeling.external_engine import parse_with_fallback as ext
            res = ext(case["instruction"], ctx)
        else:
            raise ValueError(f"引擎 {engine_id} 不可用")
        spec = spec_from_parse("test", 1, res, ctx)
        report = run_checks(spec, CheckContext(ctx.snap, ctx.topo, ctx.window, skip_trial=skip_trial))
        level = compute_level(spec)
        cmp = compare(case, spec, level, report)
        allf = [f for L in report["layers"] for f in L["findings"]]
        out.update({
            "level": level, "engine": res.engine_name, "fallback": res.fallback_note, "questions": len(res.questions),
            "spec": spec.model_dump(), "check_counts": report["counts"],
            "findings": [{"code": f["code"], "level": f["level"], "message": f["message"], "item_id": f["item_id"]} for f in allf if f["level"] != "info" or f["code"] in ("I203",)],
            "hallucination": sum(1 for f in allf if f["code"] in ("W501", "E101")),
            **cmp,
        })
    except Exception as e:  # noqa: BLE001
        out.update({"ok": False, "error": f"{type(e).__name__}: {e}", "level": None, "level_ok": False, "spec_ok": False, "hallucination": 0,
                    "dp": {"expected": len((case.get("expected") or {}).get("delta_pi", [])), "got": 0, "tp": 0, "missing": [], "extra": []}})
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def build_report(name: str, engine_id: str, results: list[dict]) -> dict:
    n = len(results)
    by_level: dict[str, dict] = {}
    for lv in LEVELS:
        rs = [r for r in results if r["expected_level"] == lv]
        if rs:
            by_level[lv] = {"total": len(rs), "level_ok": sum(1 for r in rs if r.get("level_ok")), "ok": sum(1 for r in rs if r.get("ok")),
                            "level_acc": sum(1 for r in rs if r.get("level_ok")) / len(rs), "acc": sum(1 for r in rs if r.get("ok")) / len(rs)}
    tp = sum(r["dp"]["tp"] for r in results)
    got = sum(r["dp"]["got"] for r in results)
    exp = sum(r["dp"]["expected"] for r in results)
    return {
        "name": name, "engine": engine_id, "total": n, "passed": sum(1 for r in results if r.get("ok")),
        "accuracy": (sum(1 for r in results if r.get("ok")) / n) if n else None,
        "level_accuracy": (sum(1 for r in results if r.get("level_ok")) / n) if n else None,
        "by_level": by_level,
        "dp_precision": tp / got if got else None, "dp_recall": tp / exp if exp else None, "dp_tp": tp, "dp_got": got, "dp_expected": exp,
        "hallucinations": sum(r.get("hallucination", 0) for r in results),
        "avg_ms": (sum(r["elapsed_ms"] for r in results) / n) if n else None,
        "errors": sum(1 for r in results if r.get("error")),
        "objective_compare": "待开发：目标值比对等求解接入后再做（ProOPF 用求解目标值判对错）",
        "rules": "层级按程序判级；Δπ 按 target / param / operation 或 direction / value（相对误差 ≤ 1%）/ periods 匹配；s 按 op_id 与参数匹配；must_fail 要报出对应错误",
    }


# ------------------------------------------------------------------------------------------------
RUNS: dict[str, dict] = {}


def run_testset(ts: dict, engine_id: str, skip_trial: bool = True, snapshot_id: str | None = None) -> dict:
    rid = uuid.uuid4().hex[:8]
    results = [run_case(c, engine_id, snapshot_id, skip_trial) for c in ts["cases"]]
    rep = build_report(ts["name"], engine_id, results)
    run = {"id": rid, "report": rep, "results": results, "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    RUNS[rid] = run
    return run


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def to_markdown(run: dict) -> str:
    r = run["report"]
    L = [f"# 测评报告：{r['name']}", "", f"- 引擎：{r['engine']}　用例数：{r['total']}　完成时间：{run['finished']}",
         f"- 规格级通过：**{r['passed']}/{r['total']}（{pct(r['accuracy'])}）**；层级准确率：{pct(r['level_accuracy'])}",
         f"- Δπ 精确率：{pct(r['dp_precision'])}（{r['dp_tp']}/{r['dp_got']}）；召回率：{pct(r['dp_recall'])}（{r['dp_tp']}/{r['dp_expected']}）",
         f"- 疑似幻觉数（W501 + E101）：{r['hallucinations']}；平均耗时：{r['avg_ms']:.0f} ms",
         f"- 比对规则：{r['rules']}", f"- 目标值比对：{r['objective_compare']}", "", "## 按层级", "", "| 层级 | 用例数 | 层级正确 | 规格级通过 | 准确率 |", "| --- | --- | --- | --- | --- |"]
    for lv, d in r["by_level"].items():
        L.append(f"| {lv} | {d['total']} | {d['level_ok']} | {d['ok']} | {pct(d['acc'])} |")
    L += ["", "## 逐条用例", "", "| 编号 | 期望层级 | 判级 | 结果 | 校验（错/警） | 说明 |", "| --- | --- | --- | --- | --- | --- |"]
    for x in run["results"]:
        note = x.get("error") or "；".join(filter(None, [
            "" if x.get("level_ok") else "层级不符", "" if x.get("spec_ok") else "规格不符", "" if x.get("must_fail_ok", True) else "must_fail 未报出",
            ("缺 " + ",".join(x.get("missing_findings", []))) if x.get("missing_findings") else "", ("不应出现 " + ",".join(x.get("forbidden_findings", []))) if x.get("forbidden_findings") else ""]))
        cc = x.get("check_counts") or {}
        L.append(f"| {x['id']} | {x['expected_level']} | {x.get('level')} | {'通过' if x.get('ok') else '未通过'} | {cc.get('error', '—')}/{cc.get('warn', '—')} | {note} |")
    return "\n".join(L) + "\n"


def to_csv(run: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "instruction", "expected_level", "level", "ok", "level_ok", "spec_ok", "must_fail_ok", "dp_expected", "dp_got", "dp_tp", "hallucination", "errors", "warnings", "elapsed_ms", "error"])
    for x in run["results"]:
        cc = x.get("check_counts") or {}
        w.writerow([x["id"], x["instruction"], x["expected_level"], x.get("level"), x.get("ok"), x.get("level_ok"), x.get("spec_ok"), x.get("must_fail_ok"),
                    x["dp"]["expected"], x["dp"]["got"], x["dp"]["tp"], x.get("hallucination"), cc.get("error"), cc.get("warn"), x["elapsed_ms"], x.get("error", "")])
    return "﻿" + buf.getvalue()

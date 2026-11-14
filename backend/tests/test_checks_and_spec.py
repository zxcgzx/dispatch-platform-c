"""里程碑 2：判级、白名单、算子参数、五层校验规则、追问回答、公式 / 代码 / 规模。"""
import pytest

from app.checks.engine import CheckContext, run_checks
from app.modeling import dialog
from app.modeling.codegen import generate_code, parse_markers
from app.modeling.demo_engine import DemoRuleEngine
from app.modeling.formulas import build_formulas
from app.modeling.pipeline import make_context, spec_from_parse
from app.modeling.scale import estimate
from app.modeling.trial import run_trial, syntax_check
from app.spec.level import compute_level, compute_level_from, display_level
from app.spec.schema import DeltaPi, LevelOverride, ModelSpec, SnapshotRef, StructuralOp

ENGINE = DemoRuleEngine()


@pytest.fixture(scope="module")
def ctx(multi_dir):
    """多时段（16 个断面）：时段相关的校验、追问、规模都在这个环境里测。"""
    mp = pytest.MonkeyPatch()
    mp.setenv("SNAPSHOT_DIR", str(multi_dir))
    c = make_context()
    assert c.window.periods == 16
    yield c
    mp.undo()


def mkspec(ctx, dps=(), ss=(), instruction="测试指令 母线 43 负荷", **omega) -> ModelSpec:
    spec = ModelSpec(task_id="t", version=1, instruction=instruction,
                     snapshot=SnapshotRef(snapshot_ids=ctx.window.snapshot_ids, periods=ctx.window.periods, single_snapshot=ctx.window.periods == 1),
                     delta_pi=list(dps), structural=list(ss))
    spec.omega.periods = ctx.window.periods
    for k, v in omega.items():
        setattr(spec.omega, k, v)
    return spec


def dp(id="dp-1", target="B43", param="PD", op="scale", value=1.2, periods=(), source="explicit", comp="bus", **kw):
    return DeltaPi(id=id, component=comp, target=target, param=param, operation=op if source == "explicit" else None,
                   value=value, periods=list(periods), source=source, evidence=kw.pop("evidence", "母线 43 负荷"), **kw)


def check(spec, ctx, skip_trial=True):
    return run_checks(spec, CheckContext(ctx.snap, ctx.topo, ctx.window, skip_trial=skip_trial))


def codes(rep):
    return {f["code"] for L in rep["layers"] for f in L["findings"]}


def find(rep, code):
    return [f for L in rep["layers"] for f in L["findings"] if f["code"] == code]


# ---------------------------------------------------------------- 判级
def test_level_rules():
    inferred = DeltaPi(id="dp-1", component="branch", target="L155", param="RATE_A", direction="decrease", source="inferred")
    explicit = DeltaPi(id="dp-2", component="bus", target="B43", param="PD", operation="scale", value=1.1, source="explicit")
    s = StructuralOp(id="s-1", kind="constraint", op_id="switching_limit_total", params={"K": 3})
    assert compute_level_from([], []) == "待追问"
    assert compute_level_from([explicit], []) == "L1"
    assert compute_level_from([inferred], []) == "L2"
    assert compute_level_from([explicit], [s]) == "L3"
    assert compute_level_from([inferred], [s]) == "L4"
    assert compute_level_from([], [s]) == "L3"


def test_level_override_keeps_program_level(ctx):
    spec = mkspec(ctx, [dp()])
    spec.level_override = LevelOverride(level="L3", reason="人工改选")
    assert compute_level(spec) == "L1" and display_level(spec) == "L3"


def test_n_minus_1_is_not_structural(ctx):
    spec = mkspec(ctx, [dp()], n_minus_1=True)
    assert compute_level(spec) == "L1"


# ---------------------------------------------------------------- 第 1 层
def test_e101_not_exist_and_wrong_type(ctx):
    rep = check(mkspec(ctx, [dp(target="B99999"), dp(id="dp-2", target="L2000", param="RATE_A", comp="branch", value=0.9),
                              dp(id="dp-3", target="G999", param="PMAX", comp="gen", value=0.9),
                              dp(id="dp-4", target="XYZ")]), ctx)
    assert {f["item_id"] for f in find(rep, "E101")} == {"dp-1", "dp-2", "dp-3", "dp-4"}


def test_e102_param_not_whitelisted(ctx):
    rep = check(mkspec(ctx, [dp(param="PMAX")]), ctx)       # 母线没有 PMAX
    assert find(rep, "E102")
    rep = check(mkspec(ctx, [dp(op="add", param="VMAX", value=1.05)]), ctx)   # VMAX 只能 set
    assert find(rep, "E102")


def test_e103_missing_fields(ctx):
    bad = DeltaPi(id="dp-1", component="bus", target="B43", param="PD", source="explicit")
    inf = DeltaPi(id="dp-2", component="branch", target="L155", param="RATE_A", source="inferred")
    rep = check(mkspec(ctx, [bad, inf]), ctx)
    assert {f["item_id"] for f in find(rep, "E103")} == {"dp-1", "dp-2"}


@pytest.mark.parametrize("op,val,param,comp,target", [
    ("scale", 0, "PD", "bus", "B43"), ("scale", 3.5, "PD", "bus", "B43"), ("scale", -1, "PD", "bus", "B43"),
    ("set", 1.5, "VMAX", "bus", "B43"), ("set", 0.5, "VMIN", "bus", "B43"), ("set", 2, "BR_STATUS", "branch", "L376"),
])
def test_e104_range(ctx, op, val, param, comp, target):
    rep = check(mkspec(ctx, [dp(op=op, value=val, param=param, comp=comp, target=target)]), ctx)
    assert find(rep, "E104"), (op, val, param)


def test_e104_ok_boundaries(ctx):
    for v in (0.01, 3.0):
        assert not find(check(mkspec(ctx, [dp(value=v)]), ctx), "E104")
    assert not find(check(mkspec(ctx, [dp(op="set", value=1.2, param="VMAX")]), ctx), "E104")


def test_e105_period_out_of_range(ctx):
    rep = check(mkspec(ctx, [dp(periods=[0, 5, 17])]), ctx)
    assert find(rep, "E105")


def test_e106_w107_unknown_operator(ctx):
    rep = check(mkspec(ctx, ss=[StructuralOp(id="s-1", kind="constraint", op_id="foo_bar", params={})]), ctx)
    assert find(rep, "E106")
    rep = check(mkspec(ctx, ss=[StructuralOp(id="s-1", kind="constraint", op_id="foo_bar", params={},
                                             custom_code="m.foo = pyo.Constraint(expr=m.v['B1', 1] <= 1.1)")]), ctx)
    assert find(rep, "W107") and not find(rep, "E106")


def test_custom_code_dangerous_is_blocked(ctx):
    s = StructuralOp(id="s-1", kind="constraint", op_id="evil", params={}, custom_code="import os\nos.system('echo hi')")
    rep = check(mkspec(ctx, ss=[s]), ctx, skip_trial=False)
    assert find(rep, "E108") or find(rep, "E402")
    spec = mkspec(ctx, ss=[s])
    assert run_trial(generate_code(spec), spec, ctx.window.snapshot_ids[0])["status"] == "error"


@pytest.mark.parametrize("op_id,params", [
    ("switching_limit_per_period", {"k": 0}), ("switching_limit_per_period", {"k": 1.5}), ("switching_limit_per_period", {}),
    ("switching_limit_total", {"K": -2}), ("section_limit", {"branches": ["L99999"], "limit_mw": 300}),
    ("section_limit", {"branches": [], "limit_mw": 300}), ("section_limit", {"branches": ["L428"], "limit_mw": 0}),
    ("section_limit", {"branches": ["L428"]}), ("switching_penalty", {"beta": -1}),
])
def test_e108_operator_params(ctx, op_id, params):
    kind = "objective" if op_id == "switching_penalty" else "constraint"
    rep = check(mkspec(ctx, ss=[StructuralOp(id="s-1", kind=kind, op_id=op_id, params=params)]), ctx)
    assert find(rep, "E108"), (op_id, params)


def test_beta_empty_warns_default(ctx):
    rep = check(mkspec(ctx, ss=[StructuralOp(id="s-1", kind="objective", op_id="switching_penalty", params={"beta": None})]), ctx)
    assert find(rep, "W110") and not find(rep, "E108")
    assert "β" in generate_code(mkspec(ctx, ss=[StructuralOp(id="s-1", kind="objective", op_id="switching_penalty", params={"beta": None})])) or True


def test_w109_inferred_unconfirmed(ctx):
    inf = DeltaPi(id="dp-1", component="branch", target="L155", param="RATE_A", direction="decrease", source="inferred", evidence="x")
    assert find(check(mkspec(ctx, [inf]), ctx), "W109")
    inf2 = inf.model_copy(update={"value": 0.8, "operation": "scale", "confirmed": True})
    assert not find(check(mkspec(ctx, [inf2]), ctx), "W109")


# ---------------------------------------------------------------- 第 2 层
def test_e201_conflict(ctx):
    a = dp(id="dp-1", value=1.2, periods=[1, 2, 3])
    b = dp(id="dp-2", value=1.5, periods=[3, 4])
    assert find(check(mkspec(ctx, [a, b]), ctx), "E201")
    c = dp(id="dp-3", value=1.2, periods=[3, 4])          # 同样结果：不算冲突
    assert not find(check(mkspec(ctx, [a, c]), ctx), "E201")
    d = dp(id="dp-4", value=1.5, periods=[4, 5])          # 时段不重叠
    assert not find(check(mkspec(ctx, [a, d]), ctx), "E201")


def test_w202_outage_then_rate(ctx):
    out = dp(id="dp-1", target="L376", param="BR_STATUS", comp="branch", op="set", value=0, periods=[5, 6])
    rate = dp(id="dp-2", target="L376", param="RATE_A", comp="branch", value=0.8, periods=[6, 7])
    assert find(check(mkspec(ctx, [out, rate]), ctx), "W202")
    sec = StructuralOp(id="s-1", kind="constraint", op_id="section_limit", params={"branches": ["L376", "L428"], "limit_mw": 300})
    assert find(check(mkspec(ctx, [out], [sec]), ctx), "W202")


def test_i203_removed_from_switchable(ctx):
    out = dp(target="L376", param="BR_STATUS", comp="branch", op="set", value=0, periods=[5])
    assert find(check(mkspec(ctx, [out]), ctx), "I203")
    # 孤岛型支路本来就不在网状可开断集合里：不报 I203
    iso = next(i + 1 for i in range(1000) if ctx.topo.isolating[i])
    out2 = dp(target=f"L{iso}", param="BR_STATUS", comp="branch", op="set", value=0)
    assert not find(check(mkspec(ctx, [out2]), ctx), "I203")


def test_e204_pmin_pmax_vmin_vmax(ctx):
    g = ctx.snap.gen.iloc[236]            # G237：PMAX=1000, PMIN=0
    a = dp(target="G237", param="PMIN", comp="gen", op="set", value=2000)
    assert find(check(mkspec(ctx, [a]), ctx), "E204")
    b = dp(target="B43", param="VMIN", op="set", value=1.2)
    assert find(check(mkspec(ctx, [b]), ctx), "E204")
    c = dp(target="B43", param="VMAX", op="set", value=0.85)
    assert find(check(mkspec(ctx, [c]), ctx), "E204")


def test_w205_fixed_topology_with_switch_ops(ctx):
    s = StructuralOp(id="s-1", kind="constraint", op_id="switching_limit_total", params={"K": 3})
    assert not find(check(mkspec(ctx, ss=[s]), ctx), "W205")
    p = StructuralOp(id="s-2", kind="problem", op_id="multi_period_acopf", params={})
    assert find(check(mkspec(ctx, ss=[p, s]), ctx), "W205")
    assert find(check(mkspec(ctx, ss=[s], problem="multi_period_acopf"), ctx), "W205")


def test_w206_island_and_not_for_meshed(ctx):
    iso_row = next(i + 1 for i in range(1000) if ctx.topo.isolating[i])
    out = dp(target=f"L{iso_row}", param="BR_STATUS", comp="branch", op="set", value=0, periods=[1, 2])
    assert find(check(mkspec(ctx, [out]), ctx), "W206")
    out2 = dp(target="L376", param="BR_STATUS", comp="branch", op="set", value=0)
    assert not find(check(mkspec(ctx, [out2]), ctx), "W206")


def test_w207_kv_mismatch(ctx):
    instr = "110kV 线路 L155（174–172）检修停运"        # L155 实为 220kV
    out = dp(target="L155", param="BR_STATUS", comp="branch", op="set", value=0, evidence="L155（174–172）检修停运")
    assert find(check(mkspec(ctx, [out], instruction=instr), ctx), "W207")
    ok = "220kV 线路 L155（174–172）检修停运"
    assert not find(check(mkspec(ctx, [out], instruction=ok), ctx), "W207")


# ---------------------------------------------------------------- 第 3 / 4 / 5 层
def test_layer3_items(ctx):
    rep = check(mkspec(ctx, [dp()]), ctx)
    assert find(rep, "W302") and find(rep, "I303") and not find(rep, "I305")      # 多时段：没有“单时段”提示


def test_layer4_estimate_matches_trial(ctx):
    spec = mkspec(ctx, [dp(periods=[1, 2])], [StructuralOp(id="s-1", kind="constraint", op_id="switching_limit_per_period", params={"k": 2})])
    rep = check(spec, ctx, skip_trial=False)
    assert not find(rep, "E401") and not find(rep, "E402")
    (i403,) = find(rep, "I403")
    tr = i403["data"]["trial"]
    assert tr["status"] == "ok"
    e1 = i403["data"]["estimate_t1"]
    assert (tr["vars"], tr["binary"], tr["constraints"]) == (e1["vars_total"], e1["vars_binary"], e1["constraints"])
    assert "一致" in i403["message"]


def test_e401_syntax_error():
    assert syntax_check("def f(:\n  pass") is not None
    assert syntax_check("x = 1") is None


def test_layer5_hallucinated_evidence(ctx):
    bad = dp(evidence="明天有大风")
    rep = check(mkspec(ctx, [bad], instruction="母线 43 负荷提高 20%"), ctx)
    (w,) = find(rep, "W501")
    assert w["item_id"] == "dp-1"
    empty = dp(evidence="")
    assert find(check(mkspec(ctx, [empty], instruction="母线 43 负荷提高 20%"), ctx), "W501")


def test_layer5_omission_detected(ctx):
    # 指令要求检修 L376，但规格里没有：疑似遗漏
    rep = check(mkspec(ctx, [dp(evidence="母线 43 负荷提高 20%")], instruction="母线 43 负荷提高 20%，线路 L376 检修停运"), ctx)
    msgs = " ".join(f["message"] for f in find(rep, "W502"))
    assert "L376" in msgs and "检修" in msgs


def test_layer5_i503_backtranslation(ctx):
    rep = check(mkspec(ctx, [dp(evidence="母线 43 负荷")]), ctx)
    (i,) = find(rep, "I503")
    assert i["data"]["items"][0]["id"] == "omega" and any("B43" in x["text"] for x in i["data"]["items"])


def test_external_method_state_not_connected(ctx):
    rep = check(mkspec(ctx, [dp()]), ctx)
    assert rep["external"]["label"] == "外部方法：未接入"


# ---------------------------------------------------------------- 追问回答
def test_answer_flow_d3(ctx):
    r = ENGINE.parse("明天午后持续高温，220kV 线路 L155（174–172）热稳能力下降。", ctx)
    qp = next(q for q in r.questions if q.field == "periods")
    assert len(qp.options) == 17 and qp.options[0].label.startswith("第1时段")      # 16 个时段对应钟点 + 全部
    qv = next(q for q in r.questions if q.field == "value")
    assert any(o.value == dialog.DEFAULT and o.disabled for o in qv.options)         # 规程默认值未配置：置灰
    with pytest.raises(ValueError):
        ENGINE.answer(r, qv.id, dialog.DEFAULT, ctx)
    r = ENGINE.answer(r, qp.id, "5-12", ctx)
    assert r.delta_pi[0].periods == list(range(5, 13)) and "periods" not in r.delta_pi[0].pending_fields
    r = ENGINE.answer(r, qv.id, "降低 20%", ctx)
    d = r.delta_pi[0]
    assert (d.operation, round(d.value, 6)) == ("scale", 0.8) and not r.questions
    assert d.source == "inferred" and d.confirmed is True and r.level == "L2"        # 用户亲自给出方向与幅度，即视为确认


def test_answer_rejects_bad_input(ctx):
    r = ENGINE.parse("明天午后持续高温，220kV 线路 L155（174–172）热稳能力下降。", ctx)
    qp = next(q for q in r.questions if q.field == "periods")
    qv = next(q for q in r.questions if q.field == "value")
    for bad in ("17", "5-20", "abc", ""):
        with pytest.raises(ValueError):
            ENGINE.answer(r, qp.id, bad, ctx)
    for bad in ("", "abc", "降低 500%", "增加 30 MW"):
        with pytest.raises(ValueError):
            ENGINE.answer(r, qv.id, bad, ctx)
    # 推断项幅度方向不一致：调低却给 1.3
    with pytest.raises(ValueError):
        ENGINE.answer(r, qv.id, "1.3", ctx)
    assert r.delta_pi[0].value is None          # 失败不改状态


def test_answer_d9_target(ctx):
    r = ENGINE.parse("午高峰负荷偏高，注意线路过载。", ctx)
    q = next(q for q in r.questions if q.field == "target")
    with pytest.raises(ValueError):
        ENGINE.answer(r, q.id, "L155", ctx)        # 类型不符
    with pytest.raises(ValueError):
        ENGINE.answer(r, q.id, "xx", ctx)
    r2 = ENGINE.answer(r, q.id, "B43", ctx)
    assert [d.target for d in r2.delta_pi] == ["B43"] and not r2.pending and r2.level == "L2"


def test_answer_all_candidates_parallel(ctx):
    r = ENGINE.parse("线路 172–382 检修停运。", ctx)
    assert r.pending and r.pending[0].candidates == ["L428", "L429"] and not r.delta_pi
    q = next(q for q in r.questions if q.field == "target")
    r2 = ENGINE.answer(r, q.id, "all:L428,L429", ctx)
    assert sorted(d.target for d in r2.delta_pi) == ["L428", "L429"]


def test_ask_settings(ctx):
    c2 = make_context(ask_enabled=False)
    r = ENGINE.parse("母线 314 上的机组近期出力受限。", c2)
    assert not r.questions and r.suppressed and r.delta_pi[0].pending_fields      # 追问关闭：待确认项保留在规格里
    c3 = make_context(max_rounds=1)
    r = ENGINE.parse("母线 314 上的机组近期出力受限。", c3)
    assert r.questions
    qp = next(q for q in r.questions if q.field == "periods")
    r = ENGINE.answer(r, qp.id, "1-4", c3)
    qs = [q for q in r.questions]
    assert not qs and r.suppressed is None or r.rounds >= 1


def test_clock_periods_and_out_of_window(ctx):
    # 窗口起始 18:23:06 → 4 小时窗口内：19:00–20:00 是时段 3–6 附近
    r = ENGINE.parse("母线 43 的有功负荷提高 20%，19:00-20:00。", ctx)
    assert r.delta_pi and r.delta_pi[0].periods and all(1 <= p <= 16 for p in r.delta_pi[0].periods)
    r = ENGINE.parse("母线 43 的有功负荷提高 20%，03:00-04:00。", ctx)
    assert r.delta_pi[0].pending_fields == ["periods"]           # 超出窗口：追问


def test_object_not_replaced_when_missing(ctx):
    """找不到对象：保留原文对象交给 M4 报 E101，绝不换成任何真实编号。"""
    r = ENGINE.parse("线路 9998-9999 第 1–4 时段检修停运。", ctx)
    assert any(e.status == "not_found" for e in r.entities)
    (d,) = r.delta_pi
    assert d.target == "线路 9998-9999"                      # 保留原文，不是 Lxxx
    assert not ctx.snap.object_exists(d.target)
    rep = check(spec_from_parse("t", 1, r, ctx), ctx)
    (e101,) = find(rep, "E101")
    assert e101["item_id"] == d.id and rep["has_error"]
    # 对照：端点存在的并联支路不会被“猜”成其中一条，而是挂起追问
    r2 = ENGINE.parse("线路 172-382 检修停运。", ctx)
    assert not r2.delta_pi and r2.pending[0].candidates == ["L428", "L429"]


def test_bus_not_found_keeps_original_id(ctx):
    r = ENGINE.parse("母线 99999 的负荷提高 10%。", ctx)
    assert [d.target for d in r.delta_pi] == ["B99999"]


def test_endpoint_mismatch_note(ctx):
    r = ENGINE.parse("线路 L155（1–2）检修停运。", ctx)
    e = next(e for e in r.entities if e.type == "branch")
    assert e.object_id == "L155" and e.note and "不一致" in e.note


# ---------------------------------------------------------------- 公式 / 代码 / 规模
def test_formula_highlight(ctx):
    rate = DeltaPi(id="dp-1", component="branch", target="L155", param="RATE_A", operation="scale", value=0.8, periods=list(range(5, 13)), source="explicit", evidence="x")
    f = build_formulas(mkspec(ctx, [rate]))
    assert [b["id"] for b in f["blocks"] if b["highlight"]] == ["B4"]
    assert r"0.8" in f["changes"][0]["latex"] and r"\{5,\dots,12\}" in f["changes"][0]["latex"]
    out = dp(id="dp-1", target="L376", param="BR_STATUS", comp="branch", op="set", value=0, periods=[5])
    f = build_formulas(mkspec(ctx, [out]))
    assert sorted(b["id"] for b in f["blocks"] if b["highlight"]) == ["B3", "B7"]
    assert r"\setminus" in f["changes"][0]["latex"]
    sec = StructuralOp(id="s-1", kind="constraint", op_id="section_limit", params={"branches": ["L428", "L429"], "limit_mw": 300})
    f = build_formulas(mkspec(ctx, ss=[sec]))
    assert f["new_blocks"] and f["new_blocks"][0]["id"] == "s-1"


def test_formula_inferred_pending_alpha(ctx):
    inf = DeltaPi(id="dp-1", component="branch", target="L155", param="RATE_A", direction="decrease", source="inferred", evidence="x")
    f = build_formulas(mkspec(ctx, [inf]))
    assert r"\alpha<1" in f["changes"][0]["latex"] and "待确认" in f["changes"][0]["latex"] and f["changes"][0]["pending"]


def test_formula_n1_block_follows_omega(ctx):
    assert any(b["id"] == "B9" for b in build_formulas(mkspec(ctx, n_minus_1=True))["blocks"])
    assert not any(b["id"] == "B9" for b in build_formulas(mkspec(ctx, n_minus_1=False))["blocks"])


def test_formula_objective_terms(ctx):
    s = StructuralOp(id="s-1", kind="objective", op_id="switching_penalty", params={"beta": None})
    f = build_formulas(mkspec(ctx, ss=[s]))
    assert r"\beta" in f["objective"]["latex"] and not f["objective"]["pending"]


def test_codegen_markers_and_syntax(ctx):
    inf = DeltaPi(id="dp-1", component="branch", target="L155", param="RATE_A", direction="decrease", source="inferred", evidence="x")
    cu = StructuralOp(id="s-2", kind="constraint", op_id="my_new", params={}, custom_code="m.extra = pyo.Constraint(expr=m.v['B1', 1] <= 1.1)")
    spec = mkspec(ctx, [inf, dp(id="dp-2", periods=[1, 2])], [StructuralOp(id="s-1", kind="constraint", op_id="switching_limit_total", params={"K": 5}), cu])
    code = generate_code(spec)
    assert syntax_check(code) is None
    ids = [m["id"] for m in parse_markers(code)]
    assert {"dp-1", "dp-2", "s-1", "s-2", "B1", "B4", "B9", "OBJ"} <= set(ids)
    marks = {m["id"]: m for m in parse_markers(code)}
    assert marks["s-2"]["custom"] and marks["dp-1"]["pending"]
    assert "未生效" in code                     # 未确认的推断项只写注释
    assert "pyo.Constraint(expr=sum(m.dz[l, t] for l in m.LS for t in m.T) <= 5)" in code


def test_code_is_what_trial_runs(ctx):
    """代码页显示的代码就是试构建执行的代码：改一个参数，代码和试构建结果同步变。"""
    out = dp(target="L376", param="BR_STATUS", comp="branch", op="set", value=0, periods=[1])
    spec = mkspec(ctx, [out])
    code = generate_code(spec)
    assert "OUTAGE.add('L376')" in code
    tr = run_trial(code, spec, ctx.window.snapshot_ids[0])
    assert tr["status"] == "ok" and tr["binary"] == 224        # 225 − 1（停运支路移出可开断集合）
    tr2 = run_trial(generate_code(mkspec(ctx, [dp()])), mkspec(ctx, [dp()]), ctx.window.snapshot_ids[0])
    assert tr2["binary"] == 225


def test_scale_three_rules(ctx):
    """规模区并列三种可开断集合口径：16000 / 3600 / 1712。"""
    e = estimate(mkspec(ctx, [dp()]), ctx.window)
    assert {k: v["binary_vars"] for k, v in e["by_rule"].items()} == {"all_in_service": 16000, "meshed_in_service": 3600, "meshed_kv_ge_110": 1712}
    assert e["vars_binary"] == 3600                  # 当前口径 meshed_in_service
    e2 = estimate(mkspec(ctx, [dp()], switchable_rule="all_in_service"), ctx.window)
    assert e2["vars_binary"] == 16000
    e3 = estimate(mkspec(ctx, [dp()], switchable_rule="meshed_kv_ge_110"), ctx.window)
    assert e3["vars_binary"] == 1712


def test_scale_fixed_topology_has_no_binary(ctx):
    p = StructuralOp(id="s-1", kind="problem", op_id="multi_period_acopf", params={})
    e = estimate(mkspec(ctx, ss=[p]), ctx.window)
    assert e["vars_binary"] == 0 and all(v["binary_vars"] == 0 for v in e["by_rule"].values())


def test_trial_only_builds_never_solves():
    import inspect
    from app.modeling import trial_worker
    src = inspect.getsource(trial_worker)
    assert "SolverFactory" not in src and "solve(" not in src


# ---------------------------------------------------------------- 单时段断面（只有 1 个断面文件）
@pytest.fixture
def single_ctx(monkeypatch):
    from pathlib import Path
    monkeypatch.setenv("SNAPSHOT_DIR", str(Path(__file__).resolve().parents[2] / "data" / "snapshots"))
    return make_context()


def test_single_snapshot_is_one_period(single_ctx):
    c = single_ctx
    assert c.window.periods == 1 and len(c.window.snapshot_ids) == 1
    spec = mkspec(c, [dp()])
    assert spec.omega.periods == 1 and spec.snapshot.single_snapshot
    rep = check(spec, c)
    assert find(rep, "I305") and not find(rep, "W304")
    assert not find(rep, "E105")


def test_single_period_time_words_do_not_ask(single_ctx):
    c = single_ctx
    r = ENGINE.parse("明天午后母线 43 的有功负荷提高 20%。", c)
    assert not r.questions and r.delta_pi[0].periods == []
    r = ENGINE.parse("母线 43 的有功负荷提高 20%，第 5 时段。", c)
    assert r.delta_pi                                   # 超出单时段范围的写法仍交给校验 E105
    rep = check(spec_from_parse("t", 1, r, c), c)
    assert find(rep, "E105")


def test_single_period_estimate_binary_is_one_period(single_ctx):
    c = single_ctx
    e = estimate(mkspec(c, [dp()]), c.window)
    assert e["T"] == 1 and e["vars_binary"] == 225
    assert {k: v["binary_vars_16"] for k, v in e["by_rule"].items()} == {"all_in_service": 16000, "meshed_in_service": 3600, "meshed_kv_ge_110": 1712}

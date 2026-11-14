"""新增功能：机组算子、无解诊断、CMDP、聚合与分解、RATE_A 口径。"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis.cmdp import build as cmdp_build
from app.analysis.decompose import classify, partition
from app.analysis.infeasibility import diagnose
from app.main import app
from app.modeling.codegen import generate_code
from app.modeling.demo_engine import DemoRuleEngine
from app.modeling.pipeline import make_context, spec_from_parse
from app.modeling.scale import estimate
from app.solver.dcots import solve_spec
from app.spec.schema import DeltaPi

client = TestClient(app)


@pytest.fixture(scope="module")
def ctx():
    return make_context()


def spec_of(ctx, text):
    return spec_from_parse("T", 1, DemoRuleEngine().parse(text, ctx), ctx)


def test_rate_a_is_current_in_amps(snap):
    r = snap.rate_mva()
    i = 874                                                    # L875：500kV
    assert r[i] == pytest.approx(np.sqrt(3) * 500 * snap.branch.RATE_A[i] / 1000)
    assert (r == 0).sum() == 5


def test_unit_commitment_parsed_and_solved(ctx):
    s = spec_of(ctx, "母线 43 的有功负荷提高 20%，机组启停不超过 3 次。")
    assert [o.op_id for o in s.structural] == ["unit_commitment"] and s.structural[0].params["max_switch"] == 3
    assert estimate(s, ctx.window)["vars_binary"] > 225        # 机组 0-1 变量计入
    assert "m.u = pyo.Var" in generate_code(s)
    out = solve_spec(s, ctx.window, 60)
    assert out["status"] in ("optimal", "feasible") and "gen_u" in out


def test_objective_operators_need_coefficient(ctx):
    r = DemoRuleEngine().parse("母线 43 的有功负荷提高 20%，考虑发电成本。", ctx)
    o = r.structural[0]
    assert o.op_id == "cost_economic" and o.pending_fields == ["unit_cost"]
    assert any(q.param == "unit_cost" for q in r.questions)


def test_redispatch_and_renewable_parse(ctx):
    r = DemoRuleEngine().parse("线路 L376 检修停运，机组出力调整，考虑新能源消纳。", ctx)
    assert {s.op_id for s in r.structural} == {"generator_redispatch", "renewable_accommodation"}


def test_diagnose_finds_conflict(ctx):
    s = spec_of(ctx, "母线 43 的有功负荷提高 20%。")
    assert diagnose(s, ctx.window, 10)["status"] == "feasible"
    s.delta_pi.append(DeltaPi(id="dp-9", component="branch", target="L942", param="RATE_A", operation="set", value=1.0, source="explicit", evidence="x"))
    d = diagnose(s, ctx.window, 10)
    assert d["status"] == "infeasible" and [c["id"] for c in d["conflicts"]] == ["dp-9"]


def test_cmdp_describes_actions(ctx):
    s = spec_of(ctx, "线路 L875 热稳限额设为 17 MVA，开关操作不超过 2 次。")
    c = cmdp_build(s, ctx.window)
    assert c["action"]["binary"] == 225 and any("开关" in x["name"] for x in c["costs"])


def test_partition_and_classify(ctx):
    p = partition(ctx.window)
    assert p["n_regions"] == 12 and sum(r["buses"] for r in p["regions"]) == 905
    assert p["node_aggregation"]["after"] < 905 and p["time_aggregation"]["after"] >= 1
    assert "AC-OTS" in classify(spec_of(ctx, "母线 43 的有功负荷提高 20%。"))["types"][0]


def test_pre_overloaded_not_counted_as_n1_failure(snap, topo):
    from app.metrics import indicators as ind
    r = ind.n1_screening(snap, topo)
    assert [x["id"] for x in r["pre_overloaded"]] == ["L942"]
    assert all("L942" not in f["violated"] for f in r["failed"])


def test_new_routes():
    r = client.get("/api/decompose/partition")
    assert r.status_code == 200 and r.json()["n_regions"] == 12
    f = client.get("/api/features").json()
    assert {x["id"] for x in f["features"]} >= {"m4.iis", "m10.cmdp", "m9.partition", "x.t2", "x.t3"}

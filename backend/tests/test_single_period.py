"""单断面 = 单时段；内置求解器；测点转换；地理落点。"""
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.solver.dcots import solve_spec

client = TestClient(app)


def test_window_follows_snapshot_count(snap):
    from app.data.library import build_window

    w = build_window()
    assert w.periods == 1 and w.snapshot_ids == [snap.snapshot_id] and w.single_snapshot


def test_api_window_single_period():
    w = client.get("/api/window").json()
    assert w["periods"] == 1 and len(w["labels"]) == 1


def test_task_single_period_flow_no_period_questions():
    tid = client.post("/api/tasks", json={"instruction": "明天午后母线 43 的有功负荷提高 20%。"}).json()["task"]["id"]
    st = client.post(f"/api/tasks/{tid}/parse", json={}).json()
    assert st["spec"]["omega"]["periods"] == 1 and st["parse"]["questions"] == []
    assert client.post(f"/api/tasks/{tid}/confirm", json={}).status_code == 200


def _spec(instr, **omega):
    from app.modeling.demo_engine import DemoRuleEngine
    from app.modeling.pipeline import make_context, spec_from_parse

    c = make_context()
    r = DemoRuleEngine().parse(instr, c)
    sp = spec_from_parse("t", 1, r, c)
    for k, v in omega.items():
        setattr(sp.omega, k, v)
    return sp, c


def _tight(sp, c, frac=0.1, lid="L875"):
    from app.spec.schema import DeltaPi

    i = int(lid[1:]) - 1
    pf = abs(float(c.snap.branch.PF.iloc[i]))
    sp.delta_pi.append(DeltaPi(id="dp-9", component="branch", target=lid, param="RATE_A", operation="set", value=pf * frac,
                               periods=[], source="explicit", evidence="x"))
    return pf * frac


def test_builtin_solver_load_up_dispatches_real_plan():
    sp, c = _spec("母线 43 的有功负荷提高 20%。")
    out = solve_spec(sp, c.window)
    assert out["status"] == "optimal" and out["periods"] == 1
    assert out["gen_p"], "负荷变化后应有机组出力调整"
    base_pg = {f"G{i + 1}": float(v) for i, v in enumerate(c.snap.gen.PG)}
    d = sum(v[0] - base_pg[g] for g, v in out["gen_p"].items())
    assert d == pytest.approx(91.8647 * 0.2, abs=0.05)         # 总出力增加量 = B43 增加的负荷
    assert all(len(v) == 1 for v in out["gen_p"].values()) and out["branch_flow"]


def test_builtin_solver_outage_enters_plan():
    sp, c = _spec("110kV 线路 L376（54–359）检修停运。")
    out = solve_spec(sp, c.window)
    assert out["status"] == "optimal" and out["branch_status"]["L376"] == [0]
    assert out["branch_flow"].get("L376", {"pf": [0.0]})["pf"] == [0.0]


def test_builtin_solver_switches_when_limit_tight():
    sp, c = _spec("母线 43 的有功负荷提高 20%。")
    lim = _tight(sp, c)
    out = solve_spec(sp, c.window)
    assert out["status"] == "optimal" and out["branch_status"], "限额很紧时应有开断动作"
    rate = c.snap.branch.RATE_A.to_numpy()
    for lid, f in out["branch_flow"].items():
        i = int(lid[1:]) - 1
        limit = lim if lid == "L875" else rate[i]
        if limit > 0:
            assert abs(f["pf"][0]) <= limit + 1e-3, lid


def test_builtin_solver_switch_limit_respected():
    sp, c = _spec("母线 43 负荷提高 10%，开关操作不超过 2 次。")
    _tight(sp, c)
    out = solve_spec(sp, c.window)
    opened = [l for l, a in out["branch_status"].items() if a == [0]]
    assert out["status"] == "optimal" and len(opened) <= 2


def test_builtin_solver_infeasible_reported_honestly():
    from app.spec.schema import StructuralOp

    sp, c = _spec("母线 43 的有功负荷提高 20%。")
    sp.structural = [StructuralOp(id="s-1", kind="constraint", op_id="section_limit",
                                  params={"branches": ["L428", "L429"], "limit_mw": 0.001, "direction": "abs"})]
    out = solve_spec(sp, c.window)
    assert out["status"] in ("infeasible", "optimal")
    if out["status"] == "infeasible":
        assert "没有找到可行方案" in out["messages"][0] and not out.get("branch_status")


def test_builtin_solver_is_default_and_evaluates():
    tid = client.post("/api/tasks", json={"instruction": "母线 43 的有功负荷提高 20%。"}).json()["task"]["id"]
    client.post(f"/api/tasks/{tid}/parse", json={})
    client.post(f"/api/tasks/{tid}/confirm", json={})
    t0 = time.time()
    j = client.post(f"/api/tasks/{tid}/solve", json={}).json()
    assert j["mode"] == "builtin" and j["status"] == "done" and j["result"]["status"] == "optimal"
    assert time.time() - t0 < 20
    r = client.get(f"/api/tasks/{tid}/results").json()["result"]
    assert r["gen_p"] and r["timings_s"]["solve"] is not None
    e = client.post(f"/api/tasks/{tid}/evaluate").json()
    assert e["metrics"]["after"] is not None and e["metrics"]["after"]["n1"]["evaluated"] > 0


def test_no_solver_acceleration_code():
    import inspect

    from app.solver import dcots

    src = inspect.getsource(dcots).lower()
    for w in ("presolve", "tune", "warm_start", "warmstart", "hotstart"):
        assert w not in src


# ---------------------------------------------------------------- 测点转换
def test_measure_summary_counts(snap, topo):
    s = client.get("/api/measure/summary").json()
    assert s["bus_mp"] == 905 and s["line_switches"] == 2000            # 每条支路两端各一个虚拟开关
    assert s["trafos"] == int(topo.is_transformer.sum()) and s["lines"] + s["trafos"] == 1000
    assert s["boundary_gen"] == snap.gen.GEN_BUS.nunique() and s["boundary_load"] > 0
    assert s["switches_total"] == s["line_switches"] + s["boundary_switches"]


def test_measure_tables_structure():
    t = client.get("/api/measure/tables?limit=5").json()
    assert set(t["static"]) == set(t["dynamic"]) == {"母线", "变压器", "开关", "连接线路"}
    assert all(len(v) <= 5 for v in t["static"].values())
    assert "STATUS" in t["dynamic"]["开关"][0]


def test_measure_roundtrip_lossless_with_mapping():
    r = client.get("/api/measure/roundtrip").json()
    assert r["lossless_with_mapping"] and r["mismatch"] == {"bus": 0, "branch": 0, "gen_bus_total": 0}
    assert r["ambiguities_without_mapping"]["multi_gen_buses"] == 61
    assert r["ambiguities_without_mapping"]["parallel_branch_groups"] == 67


def test_writeback_default_both_ends():
    from app.measure.convert import writeback

    w = writeback({"status": "optimal", "periods": 3, "branch_status": {"L376": [1, 0, 1]}})
    assert [(a["period"], a["switch"], a["action"]) for a in w["actions"]] == [
        (2, "SW_L376_F", "断开"), (2, "SW_L376_T", "断开"), (3, "SW_L376_F", "合上"), (3, "SW_L376_T", "合上")]
    assert "两端" in w["note"]
    assert writeback({"status": "mock", "periods": 1})["actions"] == []


def test_task_writeback_endpoint():
    tid = client.post("/api/tasks", json={"instruction": "110kV 线路 L376（54–359）检修停运。"}).json()["task"]["id"]
    client.post(f"/api/tasks/{tid}/parse", json={})
    client.post(f"/api/tasks/{tid}/confirm", json={})
    client.post(f"/api/tasks/{tid}/solve", json={})
    w = client.get(f"/api/tasks/{tid}/writeback").json()
    assert w["actions"] and w["actions"][0]["branch"] == "L376"


# ---------------------------------------------------------------- 地理
def test_geo_all_buses_inside_dali():
    g = client.get("/api/geo").json()
    assert len(g["pos"]) == 905
    xs = [p[0] for p in g["pos"].values()]
    ys = [p[1] for p in g["pos"].values()]
    assert 98.8 < min(xs) and max(xs) < 101.1 and 24.6 < min(ys) and max(ys) < 26.8
    assert sum(g["county_counts"].values()) == 905 and len(g["county_counts"]) >= 10
    assert "示意" in g["note"]


def test_geo_polygon_membership():
    from app.data.geo import GEO_FILE, _inside, _rings

    geo = json.loads(GEO_FILE.read_text(encoding="utf-8"))
    g = client.get("/api/geo").json()
    pts = np.array(list(g["pos"].values()))
    ok = np.zeros(len(pts), dtype=bool)
    for f in geo["features"]:
        for r in _rings(f):
            ok |= _inside(r, pts[:, 0], pts[:, 1])
    assert ok.all(), f"{(~ok).sum()} 个节点落在行政区划之外"

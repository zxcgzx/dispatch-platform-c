"""里程碑 4：求解黑盒、结果导入、评估与风险、协商调整。"""
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.solver import blackbox

client = TestClient(app)


@pytest.fixture(autouse=True)
def _sixteen_snapshots(multi_env):
    """这个文件测多时段（16 个断面）流程；单时段见 test_single_period.py。"""
    yield
D1 = "第 1–8 时段，母线 43 的有功负荷提高 20%。"


def make_version(instr=D1):
    tid = client.post("/api/tasks", json={"instruction": instr}).json()["task"]["id"]
    client.post(f"/api/tasks/{tid}/parse", json={})
    assert client.post(f"/api/tasks/{tid}/confirm", json={}).status_code == 200
    return tid


def wait_job(jid, n=80):
    for _ in range(n):
        st = client.get(f"/api/jobs/{jid}").json()
        if st["status"] != "running":
            return st
        time.sleep(0.2)
    return st


def good_result(**kw):
    r = {"status": "optimal", "solver": "ipopt", "objective": 1.5, "periods": 16,
         "timings_s": {"read": 0.1, "build": 0.2, "solve": 3.0, "n1_check": 0.4},
         "branch_status": {"L155": [1] * 8 + [0] * 8}, "gen_p": {"G237": [79.8] * 16}, "bus_vm": {"B43": [1.01] * 16},
         "branch_flow": {"L155": {"pf": [90.0] * 16, "qf": [5.0] * 16, "pt": [-90.0] * 16, "qt": [-4.0] * 16}}, "messages": []}
    r.update(kw)
    return r


def tight_result():
    """让 L155 负载率远超 100% 的结果，触发高风险与协商建议。"""
    return good_result(branch_status={}, branch_flow={"L155": {"pf": [900.0] * 16, "qf": [10.0] * 16, "pt": [-900.0] * 16, "qt": [-9.0] * 16}})


def test_mock_solve_has_no_fake_results():
    tid = make_version()
    j = client.post(f"/api/tasks/{tid}/solve", json={"mode": "mock"}).json()
    assert j["status"] == "done" and j["result"]["status"] == "mock"
    r = client.get(f"/api/tasks/{tid}/results").json()["result"]
    assert r["status"] == "mock"
    for k in ("branch_status", "gen_p", "bus_vm", "branch_flow"):
        assert not r.get(k), k                              # 不得有任何伪造的开断方案或曲线
    assert r["objective"] is None
    assert "黑盒占位" in r["messages"][0]


def test_mock_result_with_plan_is_rejected():
    with pytest.raises(blackbox.ResultError):
        blackbox.validate_result({"status": "mock", "periods": 16, "branch_status": {"L155": [1] * 16}})


def test_import_valid_then_read():
    tid = make_version()
    assert client.post(f"/api/tasks/{tid}/results/import", json=good_result()).status_code == 200
    got = client.get(f"/api/tasks/{tid}/results").json()["result"]
    assert got["branch_status"]["L155"][8] == 0 and got["solver"] == "ipopt"


@pytest.mark.parametrize("patch", [
    {"status": "weird"}, {"periods": 8}, {"gen_p": {"G237": [1.0] * 5}}, {"gen_p": {"G99999": [1.0] * 16}},
    {"branch_status": {"L155": [2] * 16}}, {"bus_vm": {"X1": [1.0] * 16}}, {"periods": "x"},
])
def test_import_invalid_rejected(patch):
    tid = make_version()
    r = client.post(f"/api/tasks/{tid}/results/import", json=good_result(**patch))
    assert r.status_code == 400 and r.json()["detail"]


def test_solve_blocked_by_check_errors():
    tid = client.post("/api/tasks", json={"instruction": "母线 99999 的负荷提高 10%。"}).json()["task"]["id"]
    client.post(f"/api/tasks/{tid}/parse", json={})
    client.post(f"/api/tasks/{tid}/confirm", json={})
    assert client.post(f"/api/tasks/{tid}/solve", json={"mode": "mock"}).status_code == 409


def test_external_mode_runs_command_and_streams_log(monkeypatch, tmp_path):
    script = tmp_path / "fake_solver.py"
    script.write_text(
        "import sys, json\n"
        "a = dict(zip(sys.argv[1::2], sys.argv[2::2]))\n"
        "print('reading', a['--spec']); sys.stdout.flush()\n"
        "json.dump({'status':'feasible','solver':'fake','objective':2.0,'periods':16,'branch_status':{'L376':[1]*16},'messages':[]}, open(a['--out'],'w'))\n"
        "print('done')\n", encoding="utf-8")
    monkeypatch.setenv("SOLVER_CMD", f'"{sys.executable}" "{script}" --spec {{spec}} --snapshots {{dir}} --out {{out}}')
    tid = make_version()
    j = client.post(f"/api/tasks/{tid}/solve", json={"mode": "external"}).json()
    st = wait_job(j["id"])
    assert st["status"] == "done", st
    assert any("reading" in ln for ln in st["log"])
    assert client.get(f"/api/tasks/{tid}/results").json()["result"]["solver"] == "fake"
    sse = client.get(f"/api/jobs/{j['id']}/log").text
    assert "reading" in sse and "event: end" in sse


def test_external_without_cmd_fails(monkeypatch):
    monkeypatch.setenv("SOLVER_CMD", "")
    tid = make_version()
    j = client.post(f"/api/tasks/{tid}/solve", json={"mode": "external"}).json()
    assert j["status"] == "failed" and "SOLVER_CMD" in j["error"]


def test_external_timeout(monkeypatch, tmp_path):
    from app.config import app_config
    from app.storage import db

    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(30)\n", encoding="utf-8")
    monkeypatch.setenv("SOLVER_CMD", f'"{sys.executable}" "{slow}"')
    monkeypatch.setitem(app_config()["solver"], "external_margin_s", 0)
    tid = make_version()
    spec = json.loads(db.get_version(tid, 1).spec_json)
    spec["solver_req"]["time_limit_s"] = 1
    db.update_version(tid, 1, spec_json=json.dumps(spec))
    j = client.post(f"/api/tasks/{tid}/solve", json={"mode": "external"}).json()
    assert wait_job(j["id"])["status"] == "timeout"


def test_external_bad_output_json(monkeypatch, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import sys\nopen(sys.argv[1], 'w').write('{not json')\n", encoding="utf-8")
    monkeypatch.setenv("SOLVER_CMD", f'"{sys.executable}" "{bad}" {{out}}')
    tid = make_version()
    st = wait_job(client.post(f"/api/tasks/{tid}/solve", json={"mode": "external"}).json()["id"])
    assert st["status"] == "failed" and "JSON" in st["error"]


def test_evaluate_before_is_real_data_after_is_none_in_mock():
    tid = make_version()
    client.post(f"/api/tasks/{tid}/solve", json={"mode": "mock"})
    e = client.post(f"/api/tasks/{tid}/evaluate").json()
    m = e["metrics"]
    assert m["after"] is None and "—" in m["after_note"]
    b = m["before"]
    assert b["load_rate"]["n_evaluated"] == 995 and b["voltage"]["n_above_vmax"] == 231
    assert "非交流" in b["n1"]["method"]
    assert m["unimplemented"]["vsm"].startswith("待开发") and "暂不计算" in m["unimplemented"]["renewable"]
    assert e["risk"]["mode"] == "local" and "本地规则" in e["risk"]["source"]
    assert e["risk"]["risk_level"] == "中"          # 基态 ρ 最大 0.42（<0.8），但 231 个母线电压高于上限 → 中
    assert e["risk"]["based_on"].startswith("调整前")


def test_local_risk_rules():
    from app.metrics.risk import local_risk

    base = {"load_rate": {"n_violation": 0, "n_overload": 0, "violation_threshold": 1.0, "overload_threshold": 0.8},
            "voltage": {"n_out": 0, "n_above_vmax": 0}, "n1": {"failed_count": 0, "evaluated": 10}}
    assert local_risk(base)["risk_level"] == "低"
    assert local_risk({**base, "voltage": {"n_out": 3, "n_above_vmax": 3}})["risk_level"] == "中"
    assert local_risk({**base, "load_rate": {**base["load_rate"], "n_overload": 2}})["risk_level"] == "中"
    assert local_risk({**base, "load_rate": {**base["load_rate"], "n_violation": 1, "n_overload": 1}})["risk_level"] == "高"
    assert local_risk({**base, "n1": {"failed_count": 2, "evaluated": 10}})["risk_level"] == "高"


def test_risk_endpoint_used_and_fallback(monkeypatch):
    import httpx

    from app.metrics import risk

    m = {"load_rate": {"n_violation": 0, "n_overload": 0}, "voltage": {"n_out": 0}, "n1": {"failed_count": 0, "evaluated": 1}}
    monkeypatch.setenv("RISK_ENDPOINT", "http://127.0.0.1:9/risk")
    out = risk.assess("T", 1, m, {})
    assert out.get("fallback") and out["risk_level"] == "低" and "回落" in out["source"]

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"risk_level": "高", "reasons": ["x"], "reward": 0.3}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    out = risk.assess("T", 1, m, {})
    assert out["risk_level"] == "高" and out["reward"] == 0.3 and out["mode"] == "endpoint"


def test_negotiation_creates_new_version_with_reason():
    tid = make_version()
    client.post(f"/api/tasks/{tid}/results/import", json=tight_result())
    e = client.post(f"/api/tasks/{tid}/evaluate").json()
    assert e["risk"]["risk_level"] == "高" and e["metrics"]["after"] is not None
    sug = e["suggestions"]
    pick = next(s for s in sug if s["kind"] == "dp")
    # 数值必须由用户填：不填被拒；一条都不勾也被拒
    assert client.post(f"/api/tasks/{tid}/adjust", json={"picks": [{"id": pick["id"], "values": {}}]}).status_code == 400
    assert client.post(f"/api/tasks/{tid}/adjust", json={"picks": []}).status_code == 400
    r = client.post(f"/api/tasks/{tid}/adjust", json={"picks": [{"id": pick["id"], "values": {"value": 0.9}}]})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["spec"]["version"] == 2 and st["spec"]["parent_version"] == 1
    assert "协商调整" in st["spec"]["change_reason"] and "v1" in st["spec"]["change_reason"]
    new = [d for d in st["spec"]["delta_pi"] if d["origin"]]
    assert new and new[0]["origin"].startswith("negotiation") and new[0]["value"] == 0.9
    assert client.post(f"/api/tasks/{tid}/confirm", json={}).status_code == 200
    vs = client.get(f"/api/tasks/{tid}/versions").json()["versions"]
    assert [(v["version"], v["parent_version"]) for v in vs] == [(1, None), (2, 1)]
    d = client.get(f"/api/tasks/{tid}/diff", params={"a": "1", "b": "2"}).json()
    assert d["delta_pi"]["added"] and "协商调整" in d["change_reason_b"]
    rep = client.post(f"/api/tasks/{tid}/check", json={"version": 2}).json()
    assert not [f for L in rep["layers"] for f in L["findings"] if f["code"] == "W501"]   # 协商建议没有原文依据，不按幻觉查


def test_negotiation_structural_suggestions_leave_numbers_blank():
    tid = make_version()
    client.post(f"/api/tasks/{tid}/results/import", json=tight_result())
    e = client.post(f"/api/tasks/{tid}/evaluate").json()
    for x in (s for s in e["suggestions"] if s["kind"] == "s"):
        assert all(x["item"]["params"].get(f) is None for f in x["fields_needed"])


def test_feedback_mode_and_reward_reserved():
    tid = make_version()
    assert client.post(f"/api/tasks/{tid}/feedback-mode", json={"mode": "reward"}).json()["feedback_mode"] == "reward"
    assert client.post(f"/api/tasks/{tid}/feedback-mode", json={"mode": "x"}).status_code == 400


def test_adjust_requires_evaluation():
    tid = make_version()
    assert client.post(f"/api/tasks/{tid}/adjust", json={"picks": [{"id": "r-1", "values": {}}]}).status_code == 400

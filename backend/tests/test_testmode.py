"""里程碑 5：测评模式——内置 D1–D10 全部通过、能抓出错误期望、CSV 导入、报告导出。"""
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def run_builtin():
    r = client.post("/api/testsets/builtin/run", json={"engine": "demo"})
    assert r.status_code == 200, r.text
    return r.json()


def test_builtin_d1_d10_all_pass_and_report_by_level():
    out = run_builtin()
    rep = out["report"]
    bad = [(x["id"], x.get("error"), x.get("level"), x.get("missing_findings"), x["dp"]) for x in out["results"] if not x["ok"]]
    assert rep["total"] == 10 and rep["passed"] == 10, bad
    assert rep["accuracy"] == 1.0 and rep["level_accuracy"] == 1.0
    assert set(rep["by_level"]) == {"L1", "L2", "L3", "L4", "待追问"}
    assert rep["by_level"]["L1"]["total"] == 4 and rep["by_level"]["L2"]["total"] == 2
    assert rep["by_level"]["L3"]["total"] == 2 and rep["by_level"]["L4"]["total"] == 1
    assert rep["dp_precision"] == 1.0 and rep["dp_recall"] == 1.0
    assert rep["hallucinations"] == 1                       # D8 的 E101（疑似幻觉计数 = W501 + E101）
    assert "待开发" in rep["objective_compare"]


def test_report_exports():
    out = run_builtin()
    sid = "builtin"
    md = client.get(f"/api/testsets/{sid}/report.md", params={"run": out["id"]})
    assert md.status_code == 200 and "按层级" in md.text and "| D7 |" in md.text and "疑似幻觉数" in md.text
    csv_ = client.get(f"/api/testsets/{sid}/report.csv", params={"run": out["id"]})
    assert csv_.status_code == 200 and csv_.text.count("\n") >= 11 and "D10" in csv_.text


def test_d8_must_fail_is_checked():
    out = run_builtin()
    d8 = next(x for x in out["results"] if x["id"] == "D8")
    assert d8["must_fail_ok"] and any(f["code"] == "E101" for f in d8["findings"])


def test_wrong_expectation_is_caught():
    """故意给错期望：层级写错、数值写错、漏写一条 Δπ——必须判为未通过，不能放水。"""
    ts = {"name": "错误期望", "cases": [
        {"id": "X1", "instruction": "第 1–8 时段，母线 43 的有功负荷提高 20%。", "expected_level": "L2",
         "expected": {"delta_pi": [{"target": "B43", "param": "PD", "operation": "scale", "value": 1.2, "periods": list(range(1, 9))}], "structural": []}},
        {"id": "X2", "instruction": "第 1–8 时段，母线 43 的有功负荷提高 20%。", "expected_level": "L1",
         "expected": {"delta_pi": [{"target": "B43", "param": "PD", "operation": "scale", "value": 1.3, "periods": list(range(1, 9))}], "structural": []}},
        {"id": "X3", "instruction": "第 1–8 时段，母线 43 的有功负荷提高 20%。", "expected_level": "L1",
         "expected": {"delta_pi": [], "structural": []}},
        {"id": "X4", "instruction": "母线 99999 的负荷提高 10%。", "expected_level": "L1", "must_fail": ["E999"],
         "expected": {"delta_pi": [{"target": "B99999", "param": "PD", "operation": "scale", "value": 1.1, "periods": []}], "structural": []}},
        {"id": "OK", "instruction": "第 1–8 时段，母线 43 的有功负荷提高 20.5%。", "expected_level": "L1",
         "expected": {"delta_pi": [{"target": "B43", "param": "PD", "operation": "scale", "value": 1.2, "periods": list(range(1, 9))}], "structural": []}},
    ]}
    files = {"file": ("bad.json", json.dumps(ts, ensure_ascii=False).encode("utf-8"), "application/json")}
    sid = client.post("/api/testsets", files=files).json()["id"]
    out = client.post(f"/api/testsets/{sid}/run", json={"engine": "demo"}).json()
    res = {x["id"]: x for x in out["results"]}
    assert not res["X1"]["ok"] and not res["X1"]["level_ok"]
    assert not res["X2"]["ok"] and res["X2"]["dp"]["missing"]
    assert not res["X3"]["ok"] and res["X3"]["dp"]["extra"]
    assert not res["X4"]["ok"] and not res["X4"]["must_fail_ok"]
    assert res["OK"]["ok"]                       # 1.205 与 1.2 相对误差 0.42% ≤ 1%
    assert out["report"]["passed"] == 1


def test_csv_import():
    csv_text = ("id,instruction,expected_level,expected_json,must_fail\n"
                'C1,"第 1–8 时段，母线 43 的有功负荷提高 20%。",L1,"{""delta_pi"":[{""target"":""B43"",""param"":""PD"",""operation"":""scale"",""value"":1.2,""periods"":[1,2,3,4,5,6,7,8]}],""structural"":[]}",\n'
                'C2,"母线 99999 的负荷提高 10%。",L1,"{""delta_pi"":[{""target"":""B99999"",""param"":""PD"",""operation"":""scale"",""value"":1.1,""periods"":[]}],""structural"":[]}",E101\n')
    r = client.post("/api/testsets", files={"file": ("t.csv", csv_text.encode("utf-8"), "text/csv")})
    assert r.status_code == 200 and r.json()["cases"] == 2
    out = client.post(f"/api/testsets/{r.json()['id']}/run", json={"engine": "demo"}).json()
    assert out["report"]["passed"] == 2


def test_import_invalid_and_unselectable_engine():
    assert client.post("/api/testsets", files={"file": ("x.json", b"{not json", "application/json")}).status_code == 400
    assert client.post("/api/testsets", files={"file": ("x.json", b'{"cases": []}', "application/json")}).status_code == 400
    assert client.post("/api/testsets/builtin/run", json={"engine": "external"}).status_code == 400
    assert client.get("/api/testsets/nope/report").status_code == 404


def test_testmode_never_solves():
    import inspect
    from app.testmode import runner
    assert "solve" not in inspect.getsource(runner.run_case).lower().replace("solver", "")

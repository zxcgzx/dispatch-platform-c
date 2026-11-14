"""里程碑 3 后端：任务 API——新建、解析、追问、草稿编辑、确认出版本、校验定位、差异、版本链。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _sixteen_snapshots(multi_env):
    """这个文件测多时段（16 个断面）流程；单时段见 test_single_period.py。"""
    yield


def new(instr, **kw):
    r = client.post("/api/tasks", json={"instruction": instr, **kw})
    assert r.status_code == 200, r.text
    return r.json()["task"]["id"]


def parse(tid, **kw):
    r = client.post(f"/api/tasks/{tid}/parse", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def answer(tid, qid, a):
    return client.post(f"/api/tasks/{tid}/answer", json={"question_id": qid, "answer": a})


def confirm(tid, **kw):
    return client.post(f"/api/tasks/{tid}/confirm", json=kw)


def findings(rep, code):
    return [f for L in rep["layers"] for f in L["findings"] if f["code"] == code]


def test_meta_and_engines():
    m = client.get("/api/meta").json()
    ids = {e["id"]: e for e in m["engines"]}
    assert ids["demo"]["selectable"]
    assert not ids["external"]["selectable"] and not ids["proopf"]["selectable"] and not ids["t2llm"]["selectable"]
    assert "接口预留" in ids["external"]["label"]
    assert {t["label"] for t in m["templates"]} == {"检修", "高温限额下降", "负荷增长", "开关次数限制", "断面限额"}
    assert m["whitelist"]["branch"]["RATE_A"]["ops"] == ["scale", "set"]


def test_unselectable_engine_rejected():
    r = client.post("/api/tasks", json={"instruction": "x", "engine": "external"})
    assert r.status_code == 400 and "不可选" in r.json()["detail"]


def test_d1_flow_confirm_creates_version_and_artifacts():
    tid = new("第 1–8 时段，母线 43 的有功负荷提高 20%。")
    st = parse(tid)
    assert st["level"]["level"] == "L1" and st["confirm_blockers"] == []
    r = confirm(tid)
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    assert v["version"] == 1 and v["level"] == "L1" and v["checked"] and not v["has_error"]
    from app.config import settings

    d = settings.runs_dir / tid / "v1"
    assert {p.name for p in d.iterdir()} >= {"spec.json", "model.tex", "model.py", "check.json", "log.txt"}
    assert client.get(f"/api/tasks/{tid}/versions/1/code").json()["markers"]
    lx = client.get(f"/api/tasks/{tid}/versions/1/latex").json()
    assert [b["id"] for b in lx["formulas"]["blocks"] if b["highlight"]] == ["B1"]
    assert confirm(tid).status_code == 409          # 同内容不能重复确认


def test_d3_inferred_confirmed_by_answering():
    tid = new("明天午后持续高温，220kV 线路 L155（174–172）热稳能力下降。")
    st = parse(tid)
    assert st["level"]["level"] == "L2"
    assert confirm(tid).status_code == 409          # 幅度没给：不能生成代码
    qs = {q["field"]: q for q in st["parse"]["questions"]}
    assert answer(tid, qs["periods"]["id"], "5-12").status_code == 200
    st = answer(tid, qs["value"]["id"], "降低 20%").json()
    d = st["spec"]["delta_pi"][0]
    assert d["value"] == pytest.approx(0.8) and d["confirmed"] is True     # 用户亲自给出方向与幅度，即视为确认
    assert st["confirm_blockers"] == []
    assert confirm(tid).status_code == 200
    code = client.get(f"/api/tasks/{tid}/versions/1/code").json()["code"]
    assert "_dp(D['branch']['L155']['rate'], [5, 6, 7, 8, 9, 10, 11, 12], T, 'scale', 0.8)" in code


def test_inferred_edited_in_table_needs_checkbox():
    """在规格表里直接填幅度：仍要勾选确认（手填没有“回答追问”这一步）。"""
    tid = new("母线 314 上的机组近期出力受限。", ask_enabled=False)
    st = parse(tid)
    spec = st["spec"]
    spec["delta_pi"][0].update({"value": 0.5, "periods": [1, 2], "pending_fields": []})
    st = client.put(f"/api/tasks/{tid}/spec", json=spec).json()
    assert confirm(tid).status_code == 409
    spec = st["spec"]
    spec["delta_pi"][0]["confirmed"] = True
    client.put(f"/api/tasks/{tid}/spec", json=spec)
    assert confirm(tid).status_code == 200


def test_d8_check_locates_e101():
    tid = new("母线 99999 的负荷提高 10%。")
    parse(tid)
    assert confirm(tid).status_code == 200
    rep = client.post(f"/api/tasks/{tid}/check").json()
    e = findings(rep, "E101")
    assert len(e) == 1 and e[0]["item_id"] == "dp-1" and rep["has_error"]
    assert rep["layers"][0]["status"] == "red"


def test_d9_only_asks_and_never_invents():
    tid = new("午高峰负荷偏高，注意线路过载。")
    st = parse(tid)
    assert st["level"]["level"] == "待追问"
    assert st["spec"]["delta_pi"] == [] and st["spec"]["structural"] == []
    assert confirm(tid).status_code == 409
    q = next(q for q in st["parse"]["questions"] if q["field"] == "target")
    r = answer(tid, q["id"], "B43")
    assert r.status_code == 200 and r.json()["spec"]["delta_pi"][0]["target"] == "B43"


def test_d10_island_warning_in_check():
    tid = new("220kV 线路 L442（28–774）第 1–16 时段检修停运。")
    parse(tid)
    confirm(tid)
    rep = client.post(f"/api/tasks/{tid}/check").json()
    w = findings(rep, "W206")
    assert len(w) == 1 and "B774" in w[0]["message"] and "135.5" in w[0]["message"]


def test_bad_answer_returns_400_and_keeps_state():
    tid = new("母线 314 上的机组近期出力受限。")
    st = parse(tid)
    qp = next(q for q in st["parse"]["questions"] if q["field"] == "periods")
    assert answer(tid, qp["id"], "99").status_code == 400
    assert client.get(f"/api/tasks/{tid}").json()["spec"]["delta_pi"][0]["pending_fields"]


def test_spec_edit_and_version_chain_and_diff():
    tid = new("第 1–8 时段，母线 43 的有功负荷提高 20%。")
    parse(tid)
    confirm(tid)
    spec = client.get(f"/api/tasks/{tid}/spec").json()
    assert spec["version"] == 2 and spec["parent_version"] == 1
    spec["delta_pi"][0]["value"] = 1.5
    spec["delta_pi"][0]["periods"] = [1, 2, 3]
    assert client.put(f"/api/tasks/{tid}/spec", json=spec).status_code == 200
    d = client.get(f"/api/tasks/{tid}/diff", params={"a": "1", "b": "draft"}).json()
    assert d["delta_pi"]["modified"]
    assert {c["field"] for c in d["delta_pi"]["modified"][0]["changes"]} == {"value", "periods"}
    assert confirm(tid, change_reason="用户把负荷增幅改为 50%").status_code == 200
    vs = client.get(f"/api/tasks/{tid}/versions").json()["versions"]
    assert [(v["version"], v["parent_version"]) for v in vs] == [(1, None), (2, 1)]
    assert vs[1]["change_reason"] == "用户把负荷增幅改为 50%"
    d12 = client.get(f"/api/tasks/{tid}/diff", params={"a": "1", "b": "2"}).json()
    assert d12["total"] == 1                                           # total = 变动的条目数
    assert {c["field"] for c in d12["delta_pi"]["modified"][0]["changes"]} == {"value", "periods"}
    assert d12["change_reason_b"] == "用户把负荷增幅改为 50%"
    assert d12["delta_pi"]["added"] == [] and d12["delta_pi"]["removed"] == []


def test_put_spec_rejects_bad_schema():
    tid = new("母线 43 负荷提高 20%")
    parse(tid)
    r = client.put(f"/api/tasks/{tid}/spec", json={"instruction": "x", "snapshot": {}, "delta_pi": [{"id": "dp-1"}]})
    assert r.status_code == 422


def test_supplement_replays_answers():
    tid = new("母线 314 上的机组近期出力受限。")
    st = parse(tid)
    qv = next(q for q in st["parse"]["questions"] if q["field"] == "value")
    answer(tid, qv["id"], "降低 30%")
    st = parse(tid, instruction="第 3–6 时段", supplement=True)
    assert "第 3–6 时段" in st["task"]["instruction"]
    assert st["spec"]["delta_pi"][0]["value"] == pytest.approx(0.7)       # 之前的回答被回放，不用重答


def test_ask_disabled_keeps_pending_in_spec():
    tid = new("母线 314 上的机组近期出力受限。", ask_enabled=False)
    st = parse(tid)
    assert st["parse"]["questions"] == [] and st["parse"]["suppressed"]
    assert sorted(st["spec"]["delta_pi"][0]["pending_fields"]) == ["periods", "value"]
    assert confirm(tid).status_code == 409


def test_unknown_task_and_version_404():
    assert client.get("/api/tasks/T9999").status_code == 404
    tid = new("母线 43 负荷提高 20%")
    assert client.get(f"/api/tasks/{tid}/versions/9/code").status_code == 404


def test_log_endpoint():
    tid = new("第 1–8 时段，母线 43 的有功负荷提高 20%。")
    parse(tid)
    txt = client.get(f"/api/tasks/{tid}/log").text
    assert "新建任务" in txt and "解析指令" in txt


def test_openai_engine_falls_back_when_unreachable(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")      # 不可达端口
    tid = new("第 1–8 时段，母线 43 的有功负荷提高 20%。", engine="openai")
    st = parse(tid)
    assert st["parse"]["fallback_note"] and "回落" in st["parse"]["fallback_note"]
    assert st["parse"]["engine"] == "demo" and st["level"]["level"] == "L1"

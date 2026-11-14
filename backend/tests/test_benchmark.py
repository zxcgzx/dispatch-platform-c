from fastapi.testclient import TestClient

from app.main import app


def test_benchmark_ots905():
    d = TestClient(app).get("/api/benchmark/ots905").json()
    assert d["periods_n"] == 16 and len(d["periods"]) == 16
    assert d["opened"] == ["L151"] and d["branch_status"]["L151"] == [0] * 16
    assert len(d["speed"]) == 5 and d["summary"]["ac_opf_runs"] == 240

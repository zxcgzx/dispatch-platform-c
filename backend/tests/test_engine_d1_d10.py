"""里程碑 2：D1–D10 的期望输出（指令 10.2），经 解析 → 判级 → 校验。"""
import json
from pathlib import Path

import pytest

from app.checks.engine import CheckContext, run_checks
from app.modeling.demo_engine import DemoRuleEngine
from app.modeling.pipeline import make_context, spec_from_parse
from app.spec.level import compute_level

ROOT = Path(__file__).resolve().parents[2]
CASES = {c["id"]: c for c in json.loads((ROOT / "data/testsets/demo_cases_multiperiod.json").read_text(encoding="utf-8"))["cases"]}
ENGINE = DemoRuleEngine()


@pytest.fixture(scope="module")
def ctx(multi_dir):
    """多时段：断面库有 16 个断面 → 16 时段窗口（D1–D10 的多时段写法）。"""
    mp = pytest.MonkeyPatch()
    mp.setenv("SNAPSHOT_DIR", str(multi_dir))
    c = make_context()
    assert c.window.periods == 16
    yield c
    mp.undo()


def parse(cid, ctx):
    return ENGINE.parse(CASES[cid]["instruction"], ctx)


def codes(report):
    return {f["code"] for L in report["layers"] for f in L["findings"]}


def findings(report, code):
    return [f for L in report["layers"] for f in L["findings"] if f["code"] == code]


@pytest.fixture(scope="module")
def reports(ctx):
    out = {}
    for cid in CASES:
        r = parse(cid, ctx)
        spec = spec_from_parse("t", 1, r, ctx)
        out[cid] = (r, spec, run_checks(spec, CheckContext(ctx.snap, ctx.topo, ctx.window, skip_trial=True)))
    return out


def test_d1(ctx):
    r = parse("D1", ctx)
    assert r.level == "L1" and not r.questions and not r.structural
    (d,) = r.delta_pi
    assert (d.target, d.param, d.operation, d.value, d.source) == ("B43", "PD", "scale", 1.2, "explicit")
    assert d.periods == list(range(1, 9))
    assert d.evidence in CASES["D1"]["instruction"]


def test_d2(reports):
    r, spec, rep = reports["D2"]
    assert r.level == "L1"
    (d,) = r.delta_pi
    assert (d.target, d.param, d.operation, d.value, d.source) == ("L376", "BR_STATUS", "set", 0, "explicit")
    assert d.periods == list(range(5, 13))
    assert "I203" in codes(rep)          # 移出可开断集合
    assert "W206" not in codes(rep)      # 不应出现孤岛警告
    assert not rep["has_error"]


def test_d3(ctx, reports):
    r, spec, rep = reports["D3"]
    assert r.level == "L2"
    (d,) = r.delta_pi
    assert (d.target, d.param, d.direction, d.source, d.value) == ("L155", "RATE_A", "decrease", "inferred", None)
    assert d.inference_chain == ["高温", "热稳裕度下降", "调低 RATE_A"]
    assert {q.field for q in r.questions} == {"periods", "value"}     # 追问时段和幅度
    assert not d.confirmed
    assert "W109" in codes(rep)


def test_d4(reports):
    r, spec, rep = reports["D4"]
    assert r.level == "L2"
    (d,) = r.delta_pi
    assert (d.target, d.param, d.direction, d.source) == ("G237", "PMAX", "decrease", "inferred")
    assert {q.field for q in r.questions} == {"periods", "value"}


def test_d5(reports):
    r, spec, rep = reports["D5"]
    assert r.level == "L3"
    (d,) = r.delta_pi
    assert (d.target, d.param, d.operation, d.value, d.periods) == ("B43", "PD", "scale", 1.1, [])   # 全部时段
    (s,) = r.structural
    assert (s.op_id, s.kind, s.params) == ("switching_limit_per_period", "constraint", {"k": 2})
    assert not rep["has_error"]


def test_d6(reports):
    r, spec, rep = reports["D6"]
    assert r.level == "L3" and not r.delta_pi
    (s,) = r.structural
    assert s.op_id == "section_limit"
    assert s.params["branches"] == ["L428", "L429"] and s.params["limit_mw"] == 300
    assert not rep["has_error"]


def test_d7(reports):
    r, spec, rep = reports["D7"]
    assert r.level == "L4"
    (d,) = r.delta_pi
    assert (d.target, d.param, d.direction, d.source) == ("L155", "RATE_A", "decrease", "inferred")
    assert r.omega_confirm == {"n_minus_1": True, "evidence": "满足 N−1"}
    assert [s.op_id for s in r.structural] == ["switching_penalty"]       # N−1 不算结构修改
    assert r.structural[0].params == {"beta": None}
    assert spec.omega.n_minus_1 is True
    assert {q.field for q in r.questions} == {"periods", "value"}         # 追问“午高峰”对应的时段和幅度
    assert any(f["code"] == "W110" for L in rep["layers"] for f in L["findings"])   # beta 为空：告警


def test_d8(reports):
    r, spec, rep = reports["D8"]
    assert r.level == "L1"
    (d,) = r.delta_pi
    assert d.target == "B99999"          # 不得替换成其他母线
    e101 = findings(rep, "E101")
    assert len(e101) == 1 and e101[0]["item_id"] == d.id    # 定位到该条
    assert rep["has_error"]


def test_d9(reports):
    r, spec, rep = reports["D9"]
    assert r.level == "待追问"
    assert not r.delta_pi and not r.structural          # 规格中不得出现编造的对象
    assert r.pending and r.pending[0].candidates == []
    assert "target" in {q.field for q in r.questions}


def test_d10(reports):
    r, spec, rep = reports["D10"]
    assert r.level == "L1"
    (d,) = r.delta_pi
    assert (d.target, d.param) == ("L442", "BR_STATUS") and d.periods == list(range(1, 17))
    (w,) = findings(rep, "W206")
    assert "孤立 1 个母线" in w["message"] and "B774" in w["message"]
    assert abs(w["data"]["net_injection_mw"] - 135.5) < 0.1


def test_evidence_is_verbatim_for_all(reports):
    """去幻觉核心：所有条目的 evidence 都是原文子串。"""
    for cid, (r, spec, rep) in reports.items():
        for it in [*spec.delta_pi, *spec.structural]:
            assert it.evidence in spec.instruction, (cid, it.id, it.evidence)
        assert "W501" not in codes(rep), cid


def test_omission_check(reports):
    """第 5 层遗漏检查：D9 没有对象，“负荷偏高”没进规格，必须报 W502；其余用例不得误报。"""
    for cid, (r, spec, rep) in reports.items():
        if cid == "D9":
            assert "W502" in codes(rep)
        else:
            assert "W502" not in codes(rep), (cid, [f["message"] for f in findings(rep, "W502")])


def test_levels_match_expected(reports):
    for cid, c in CASES.items():
        assert reports[cid][0].level == c["expected_level"], cid
        assert compute_level(reports[cid][1]) == c["expected_level"] or cid in ("D9",), cid

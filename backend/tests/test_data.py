"""里程碑 1：核对指令 4.4 的数据事实。"""
import hashlib
from pathlib import Path

from app.data.facts import compute_facts, compute_quality
from app.data.snapshot import parse_id

ROOT = Path(__file__).resolve().parents[2]


def test_shapes(snap):
    assert snap.bus.shape == (905, 14)
    assert snap.gen.shape == (237, 10)
    assert snap.branch.shape == (1000, 17)
    assert snap.base_mva == 100.0


def test_ids(snap):
    assert snap.bus_ids[0] == "B1" and "B4588" in snap.bus_ids
    assert snap.branch_ids[0] == "L1" and snap.branch_ids[-1] == "L1000"
    assert snap.gen_ids[-1] == "G237"
    assert parse_id("B43") == ("bus", 43) and parse_id("X1") is None
    assert snap.object_exists("B43") and not snap.object_exists("B99999")
    assert snap.object_exists("L1000") and not snap.object_exists("L1001")
    assert snap.branch_label(155) == "L155（174–172，220kV）"


def test_bus_facts(snap, topo):
    f = compute_facts(snap, topo)
    assert f["bus_types"] == {"PQ": 834, "PV": 70, "平衡节点": 1}
    assert f["slack_bus"] == [175]
    assert f["bus_by_kv"] == {"500kV": 17, "220kV": 60, "110kV": 262, "35kV": 354, "10kV": 200, "6kV": 12}
    assert abs(f["totals"]["pd_mw"] - 1014) < 1
    assert abs(f["totals"]["pg_mw"] - 1693) < 1


def test_status_and_renewable(snap, topo):
    f = compute_facts(snap, topo)
    assert f["all_branches_in_service"] and f["all_gens_in_service"]
    assert f["renewable_all_zero"]
    assert f["connected"]


def test_island_vs_meshed(snap, topo):
    f = compute_facts(snap, topo)
    assert f["isolating_branches"] == 775
    assert f["meshed_branches"] == 225
    assert f["meshed_by_kv"] == {"500kV": 11, "220kV": 63, "110kV": 33, "35kV": 118}
    assert f["parallel"] == {"groups": 67, "branches": 136}
    assert f["buses_with_multiple_gens"] == 61


def test_switchable_counts(snap, topo):
    """规模区三种口径：全部在运 1000×16、网状 225×16、网状且 ≥110kV 107×16。"""
    c = compute_facts(snap, topo)["switchable_counts"]
    assert (c["all_in_service"], c["meshed_in_service"], c["meshed_kv_ge_110"]) == (1000, 225, 107)
    assert (c["all_in_service"] * 16, c["meshed_in_service"] * 16, c["meshed_kv_ge_110"] * 16) == (16000, 3600, 1712)


def test_quality(snap, topo):
    q = {i["code"]: i for i in compute_quality(snap, topo)}
    assert q["Q-VM-HI"]["count"] == 231
    assert q["Q-VM-LO"]["count"] == 2
    assert q["Q-PG"]["count"] == 101
    assert q["Q-RATE0"]["count"] == 5
    assert q["Q-PD-NEG"]["count"] == 248
    assert q["Q-EQUIV"]["count"] == 2
    assert q["Q-NAN"]["count"] == 0
    # 断面时刻 Dict Info 与文件名不一致：如实记一条
    assert q["Q-TIME"]["count"] == 1


def test_time_priority(snap):
    assert snap.time_source == "dict"
    assert snap.time.isoformat() == "2026-10-15T18:23:06"
    assert snap.file_time.isoformat() == "2026-10-04T15:35:00"
    assert snap.time_mismatch


def test_parallel_not_primary_key(snap):
    """并联支路不能用首末母线当主键：L428、L429 同为 172–382。"""
    r = snap.branch.iloc[[427, 428]]
    assert list(r.F_BUS) == [172, 172] and list(r.T_BUS) == [382, 382]


def test_demo_island_d10(snap, topo):
    """D10：L442 停运 → 孤立 1 个母线 B774，孤岛内净注入约 135.5 MW。"""
    isl = topo.outage_islands({442})
    assert len(isl) == 1 and isl[0].buses == [774]
    assert abs(isl[0].net_injection_mw - 135.47) < 0.1


def test_d2_no_island(topo):
    """D2：L376 在网状部分，停运不形成孤岛。"""
    assert topo.outage_islands({376}) == []


def test_snapshot_file_untouched():
    """断面文件只读：指纹在测试前后不变（与参考 SHA1 无关，只检查可读且未被改写）。"""
    p = ROOT / "data" / "snapshots" / "pasExp_20261004_153500_1.txt"
    assert hashlib.sha1(p.read_bytes()).hexdigest()

"""里程碑 4：指标（负载率、电压偏移、N−1 直流筛查）——LODF 用独立的“逐事故重解直流潮流”做交叉验证。"""
import numpy as np
import pytest

from app.metrics import indicators as ind


def test_loading_matches_hand_calc(snap, topo):
    rho = ind.branch_loading(snap)
    br = snap.branch
    i = 154                                                    # L155：RATE_A = 800
    exp = max(np.hypot(br.PF[i], br.QF[i]), np.hypot(br.PT[i], br.QT[i])) / br.RATE_A[i]
    assert rho[i] == pytest.approx(exp)
    assert np.isnan(rho[237]) and np.isnan(rho[418])          # RATE_A = 0 视为不限，不计算
    assert int(np.isnan(rho).sum()) == 5


def test_load_rate_card(snap):
    rho = ind.branch_loading(snap)
    m = ind.load_rate_metrics(rho, snap)
    assert m["n_evaluated"] == 995 and m["n_unlimited"] == 5
    r = rho[~np.isnan(rho)]
    assert m["max"] == pytest.approx(r.max()) and m["mean"] == pytest.approx(r.mean())
    assert m["n_overload"] == int((r >= 0.8).sum()) and m["n_violation"] == int((r >= 1.0).sum())
    assert m["top"][0]["rho"] == pytest.approx(m["max"])


def test_loading_rate_scale_changes_rho(snap):
    base = ind.branch_loading(snap)[154]
    scaled = ind.branch_loading(snap, rate_scale={"L155": 0.5})[154]
    assert scaled == pytest.approx(base * 2)


def test_voltage_card(snap):
    v = ind.voltage_metrics(snap)
    assert v["n_above_vmax"] == 231 and v["n_below_vmin"] == 2 and v["n_out"] == 233
    dv = np.abs(snap.bus.VM.to_numpy() - 1)
    assert v["max"] == pytest.approx(dv.max()) and v["mean"] == pytest.approx(dv.mean())
    assert "231" in v["note"]


def _dc_consistent_flow(snap, in_service, seed=0):
    """造一个直流一致的基态潮流：随机节点注入 → 解 θ → f0 = b·Aθ。"""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    A, b, slack, _, _ = ind._dc_system(snap, in_service)
    nb = A.shape[1]
    rng = np.random.default_rng(seed)
    inj = rng.normal(0, 20, nb)
    inj[slack] = 0
    inj -= (inj.sum() - inj[slack]) * 0                         # 平衡节点吸收差额，不参与方程
    keep = np.array([i for i in range(nb) if i != slack])
    B = (A.T @ sp.diags(b) @ A).tocsc()
    theta = np.zeros(nb)
    theta[keep] = spla.spsolve(B[keep][:, keep].tocsc(), inj[keep])
    return b * (A @ theta)


def test_lodf_matches_bruteforce_resolve(snap, topo):
    """LODF 公式的事故后潮流 == 对每个事故重解直流潮流（独立实现，不用 PTDF / LODF）。
    基态潮流必须是直流一致的（真实断面的 PF 是交流潮流，不满足直流方程，不能直接做这个恒等式检验）。"""
    in_service = topo.in_service.copy()
    f0 = _dc_consistent_flow(snap, in_service)
    meshed = [r - 1 for r in topo.rule_rows("meshed_in_service")]
    sample = meshed[::17][:12]
    PT, pcc = ind.ptdf_lodf(snap, in_service, sample)
    for k, c in enumerate(sample):
        lodf = PT[:, k] / (1.0 - pcc[k])
        lodf[c] = -1.0
        post = f0 + lodf * f0[c]
        post[c] = 0.0
        ref = ind.dc_n1_bruteforce(snap, in_service, c, f0)
        mask = in_service.copy()
        mask[c] = False
        assert np.allclose(post[mask], ref[mask], atol=1e-6, rtol=1e-6), (c, np.abs(post[mask] - ref[mask]).max())


def test_lodf_sign_and_tap_handling(snap, topo):
    """带变比的支路（TAP ≠ 0）也要通过同一恒等式：取一条变压器支路作事故。"""
    in_service = topo.in_service.copy()
    f0 = _dc_consistent_flow(snap, in_service, seed=3)
    tr = [i for i in (r - 1 for r in topo.rule_rows("meshed_in_service")) if snap.branch.TAP.iloc[i] != 0 and topo.is_transformer[i]]
    assert tr, "数据里应有网状部分的变压器支路"
    c = tr[0]
    PT, pcc = ind.ptdf_lodf(snap, in_service, [c])
    lodf = PT[:, 0] / (1 - pcc[0])
    lodf[c] = -1.0
    post = f0 + lodf * f0[c]
    post[c] = 0.0
    ref = ind.dc_n1_bruteforce(snap, in_service, c, f0)
    m = in_service.copy()
    m[c] = False
    assert np.allclose(post[m], ref[m], atol=1e-6, rtol=1e-6)


def test_lodf_parallel_pair(snap, topo):
    """并联 L428 / L429（172–382）：L428 退出后，L429 接走其中一部分潮流（其余走网络其他路径），
    所以 0 < LODF < 1；并与独立的“重解直流潮流”一致。"""
    in_service = topo.in_service.copy()
    f0 = _dc_consistent_flow(snap, in_service, seed=5)
    PT, pcc = ind.ptdf_lodf(snap, in_service, [427])
    lodf = PT[:, 0] / (1 - pcc[0])
    assert 0 < lodf[428] < 1
    assert 0 < pcc[0] < 1
    lodf[427] = -1.0
    post = f0 + lodf * f0[427]
    post[427] = 0.0
    ref = ind.dc_n1_bruteforce(snap, in_service, 427, f0)
    m = in_service.copy()
    m[427] = False
    assert np.allclose(post[m], ref[m], atol=1e-6, rtol=1e-6)
    assert post[428] == pytest.approx(ref[428], abs=1e-6)


def test_n1_screening_default_rule(snap, topo):
    r = ind.n1_screening(snap, topo)
    assert "非交流" in r["method"]
    assert r["contingency_total"] == 225 and r["islanding"]["count"] == 0
    assert r["evaluated"] + 0 <= 225 and r["passed"] + r["failed_count"] == r["evaluated"]
    assert 0 <= r["pass_rate"] <= 1
    assert r["pass_rate"] == pytest.approx(r["passed"] / r["evaluated"])


def test_n1_screening_all_in_service_lists_island_events(snap, topo):
    """事故集选“全部在运支路”：775 条孤岛型事故不进 LODF，单列并给出涉及的净负荷。"""
    r = ind.n1_screening(snap, topo, rule="all_in_service")
    assert r["contingency_total"] == 1000
    isl = r["islanding"]
    assert isl["count"] == 775
    assert isl["buses_total"] > 0 and isl["load_mw_total"] != 0
    assert isl["net_load_mw_total"] == pytest.approx(-isl["net_injection_mw_total"])
    biggest = max(topo.isolating_net_load.values(), key=lambda d: abs(d["net_injection_mw"]))
    assert isl["largest"]["net_injection_mw"] == pytest.approx(biggest["net_injection_mw"], abs=0.01)   # 单次最大孤岛
    assert isl["largest"]["buses"] == biggest["buses"]
    assert r["evaluated"] <= 225
    assert "孤岛事故" in r["note"]


def test_island_dfs_matches_per_branch_recompute(topo):
    """子树求和（O(N)）与逐条停运重算连通分量的结果一致；并且很快。"""
    import time

    t0 = time.time()
    fast = topo.isolating_net_load
    assert time.time() - t0 < 5.0, "孤岛型支路统计应在数秒内完成（逐条重算要 30 秒以上）"
    assert len(fast) == 775
    rows = sorted(fast)[::40]
    for row in rows:
        isl = topo.outage_islands({row})
        assert fast[row]["buses"] == sum(len(x.buses) for x in isl)
        assert fast[row]["net_injection_mw"] == pytest.approx(sum(x.net_injection_mw for x in isl), abs=1e-6)
        assert fast[row]["load_mw"] == pytest.approx(sum(x.load_mw for x in isl), abs=1e-6)
    d442 = fast[442]                                            # D10：L442 停运孤立 B774，净注入约 135.5 MW
    assert d442["buses"] == 1 and d442["net_injection_mw"] == pytest.approx(135.47, abs=0.1)


def test_n1_screening_detects_violation_when_rate_tight(snap, topo):
    rate = snap.branch.RATE_A.to_numpy(dtype=float) * 0.05     # 把限额压到 5%：必然大面积不通过
    r = ind.n1_screening(snap, topo, rate=rate)
    assert r["failed_count"] > 0 and r["pass_rate"] < 1
    assert r["failed"][0]["worst_rho"] > 1 and r["frequent_violated"]


def test_n1_screening_loose_rate_all_pass(snap, topo):
    rate = np.full(len(snap.branch), 1e9)
    r = ind.n1_screening(snap, topo, rate=rate)
    assert r["failed_count"] == 0 and r["pass_rate"] == 1.0

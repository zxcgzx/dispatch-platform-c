"""基础路由：features / snapshots / topology / integrations / config。"""
from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import app_config, knowledge, operators_config, settings
from ..data import layout as layout_mod
from ..data.library import build_window, default_snapshot_id, get_snapshot, list_snapshots, snapshot_summary
from ..data.snapshot import bus_id, branch_id
from ..features import feature_response
from ..integrations.registry import integrations

router = APIRouter()


@router.get("/features")
def get_features():
    return feature_response()


@router.get("/snapshots")
def get_snapshots():
    return {"default": default_snapshot_id(), "snapshots": list_snapshots()}


@router.get("/snapshots/{sid}/summary")
def get_summary(sid: str):
    try:
        return snapshot_summary(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.get("/window")
def get_window(start: str | None = None, snapshot: str | None = None):
    """选起始时刻 → 16 时段窗口（断面 id 列表、是否单断面演示模式）。"""
    try:
        st = datetime.fromisoformat(start) if start else None
        w = build_window(st, snapshot)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {
        "start": w.start.isoformat(timespec="minutes") if w.start else None,
        "periods": w.periods, "step_min": w.step_min, "single_snapshot": w.single_snapshot,
        "snapshot_ids": w.snapshot_ids, "notes": w.notes,
        "labels": [w.period_label(t) for t in range(1, w.periods + 1)],
    }


@router.get("/topology")
def get_topology(snapshot: str | None = None):
    sid = snapshot or default_snapshot_id()
    if not sid:
        raise HTTPException(404, "断面库为空")
    snap, topo = get_snapshot(sid)
    pos = layout_mod.get_layout(snap)
    br = snap.branch
    kvmap = snap.bus_kv()
    nodes = [
        {"id": bus_id(b), "bus_i": int(b), "kv": float(k), "type": int(t), "pd": round(float(pd), 3), "vm": round(float(vm), 4),
         "x": pos[bus_id(b)][0], "y": pos[bus_id(b)][1]}
        for b, k, t, pd, vm in zip(snap.bus["BUS_I"], snap.bus["BASE_KV"], snap.bus["BUS_TYPE"], snap.bus["PD"], snap.bus["VM"])
    ]
    branches = []
    for i in range(len(br)):
        r = br.iloc[i]
        rate = float(r.RATE_A)
        s_from = (float(r.PF) ** 2 + float(r.QF) ** 2) ** 0.5
        s_to = (float(r.PT) ** 2 + float(r.QT) ** 2) ** 0.5
        branches.append({
            "id": branch_id(i + 1), "row": i + 1, "from": bus_id(r.F_BUS), "to": bus_id(r.T_BUS),
            "kv": float(topo.kv[i]), "transformer": bool(topo.is_transformer[i]),
            "isolating": bool(topo.isolating[i]), "in_service": bool(topo.in_service[i]),
            "parallel": int(topo.parallel_group[i]), "rate_a": rate,
            "pf": round(float(r.PF), 3), "qf": round(float(r.QF), 3),
            "load_ratio": round(max(s_from, s_to) / rate, 4) if rate > 0 else None,
        })
    return {"snapshot": sid, "nodes": nodes, "branches": branches, "kv_levels": sorted({n["kv"] for n in nodes}, reverse=True)}


@router.get("/geo/boundary")
def get_geo_boundary():
    """大理州行政区划底图（GeoJSON，12 个县市）。由后端提供，前端不再依赖单独的静态文件。"""
    import json as _json

    from ..data import geo as geo_mod

    return _json.loads(geo_mod.GEO_FILE.read_text(encoding="utf-8"))


@router.get("/gen-base")
def get_gen_base(snapshot: str | None = None):
    """各机组断面出力（MW），结果页算“调整前 → 调整后”用。"""
    sid = snapshot or default_snapshot_id()
    snap, _ = get_snapshot(sid)
    return {"pg": {f"G{i + 1}": round(float(v), 4) for i, v in enumerate(snap.gen["PG"])}}


@router.get("/geo")
def get_geo(snapshot: str | None = None):
    """地理地图：节点落点（经纬度，示意）与所属县域。底图 GeoJSON 在 /geo/dali.json。"""
    from ..data import geo as geo_mod

    sid = snapshot or default_snapshot_id()
    if not sid:
        raise HTTPException(404, "断面库为空")
    snap, _ = get_snapshot(sid)
    d = geo_mod.get_positions(snap, layout_mod.get_layout(snap))
    counts: dict[str, int] = {}
    for c in d["county"].values():
        counts[c] = counts.get(c, 0) + 1
    return {"pos": d["pos"], "county": d["county"], "county_counts": counts,
            "note": "节点位置按拓扑落在各县范围内，是示意，不是真实站址；有大理真实经纬度后替换即可。"}


@router.get("/objects")
def get_objects(snapshot: str | None = None):
    """对象选择器用：B / L / G 编号与显示名。"""
    sid = snapshot or default_snapshot_id()
    snap, topo = get_snapshot(sid)
    br = snap.branch
    return {
        "bus": [{"id": bus_id(b), "label": f"{bus_id(b)}（{k:g}kV）"} for b, k in zip(snap.bus["BUS_I"], snap.bus["BASE_KV"])],
        "branch": [{"id": branch_id(i + 1), "label": snap.branch_label(i + 1), "meshed": bool(topo.meshed[i]),
                    "isolating": bool(topo.isolating[i])} for i in range(len(br))],
        "gen": [{"id": f"G{i + 1}", "label": f"G{i + 1}（母线 {int(g)}）"} for i, g in enumerate(snap.gen["GEN_BUS"])],
    }


@router.get("/integrations")
def get_integrations():
    return {"integrations": integrations()}


@router.get("/config")
def get_config():
    """配置与知识表（只读展示）。"""
    ops = operators_config()
    return {
        "app": app_config(),
        "knowledge": knowledge(),
        "operators": {k: {kk: vv for kk, vv in v.items() if kk != "code"} for k, v in ops.get("operators", {}).items()},
        "env": {
            "llm_mode": settings.llm_mode, "llm_base_url": settings.llm_base_url, "llm_model": settings.llm_model,
            "method_endpoint": settings.method_endpoint, "risk_endpoint": settings.risk_endpoint,
            "solver_mode": settings.solver_mode, "snapshot_dir": str(settings.snapshot_dir),
        },
    }


@router.post("/measurements/preview")
async def preview_measurements(file: UploadFile = File(...)):
    """课题 2 测点数据：只做 XLSX / CSV 预览，“测点→节点转换”待开发。"""
    import pandas as pd

    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(raw))
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(raw), encoding="gbk")
            sheets = {"(csv)": df}
        elif name.endswith((".xlsx", ".xlsm")):
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
        else:
            raise HTTPException(400, "只支持 XLSX / CSV")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"读取失败：{e}")
    out = []
    for sn, df in sheets.items():
        out.append({"sheet": sn, "rows": int(len(df)), "columns": [str(c) for c in df.columns],
                    "head": df.head(20).astype(object).where(df.head(20).notna(), None).values.tolist()})
    return {"filename": file.filename, "sheets": out, "conversion": "待开发：测点 → 节点转换需要课题 2 提供映射"}


@router.get("/name-registry")
def get_name_registry():
    """名称 ↔ 编号登记表（data/name_registry.csv，现为空，课题 2 后续提供）。"""
    import pandas as pd

    from ..config import DATA_DIR

    p = DATA_DIR / "name_registry.csv"
    if not p.exists():
        return {"columns": [], "rows": []}
    df = pd.read_csv(p, dtype=str).fillna("")
    return {"columns": list(df.columns), "rows": df.values.tolist()}


@router.get("/benchmark/ots905")
def get_benchmark_ots905():
    """MATLAB 16 时段完整交流 OTS 基准结果（只读展示，由 scripts/import_matlab_benchmark.py 生成）。"""
    import json as _json
    from pathlib import Path as _P

    f = _P(__file__).resolve().parents[1] / "data" / "benchmarks" / "ots905_v1.3.json"
    if not f.exists():
        raise HTTPException(404, "基准结果文件不存在，请先运行 scripts/import_matlab_benchmark.py")
    return _json.loads(f.read_text(encoding="utf-8"))

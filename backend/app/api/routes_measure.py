"""课题 2 测点接口：节点 ↔ 测点转换、测点表预览、方案回写（开关动作）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..data.library import default_snapshot_id, get_snapshot
from ..measure import convert
from ..storage import db
from .routes_tasks import _ver

router = APIRouter()


def _snap(sid: str | None):
    sid = sid or default_snapshot_id()
    if not sid:
        raise HTTPException(404, "断面库为空")
    return get_snapshot(sid)


@router.get("/measure/summary")
def measure_summary(snapshot: str | None = None):
    snap, topo = _snap(snapshot)
    return convert.summary(snap, topo)


@router.get("/measure/tables")
def measure_tables(snapshot: str | None = None, limit: int = 12):
    snap, topo = _snap(snapshot)
    return convert.static_dynamic_tables(snap, topo, limit=max(1, min(limit, 200)))


@router.get("/measure/roundtrip")
def measure_roundtrip(snapshot: str | None = None):
    snap, topo = _snap(snapshot)
    return convert.reverse_recover(snap, topo)


@router.get("/tasks/{tid}/writeback")
def task_writeback(tid: str, version: int | None = None):
    row = _ver(tid, version) if version else db.latest_version(tid)
    if row is None:
        raise HTTPException(404, "还没有已确认的版本")
    res = json.loads(row.result_json) if row.result_json else None
    return {"version": row.version, **convert.writeback(res)}

"""测评模式路由：POST /testsets、POST /testsets/{id}/run、GET /testsets/{id}/report（+ 导出）。"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..config import DATA_DIR
from ..modeling.pipeline import engine_options
from ..testmode import runner

router = APIRouter()
SETS: dict[str, dict] = {}
LATEST: dict[str, str] = {}          # testset id -> 最近一次 run id


def _builtin() -> dict:
    d = json.loads((DATA_DIR / "testsets" / "demo_cases.json").read_text(encoding="utf-8"))
    return {"name": d["name"], "cases": d["cases"]}


def _get(sid: str) -> dict:
    if sid == "builtin":
        return _builtin()
    if sid not in SETS:
        raise HTTPException(404, "测试集不存在")
    return SETS[sid]


class RunBody(BaseModel):
    engine: str = "demo"
    skip_trial: bool = True


@router.get("/testsets")
def list_sets():
    b = _builtin()
    return {"testsets": [{"id": "builtin", "name": b["name"], "cases": len(b["cases"]), "builtin": True}] +
            [{"id": k, "name": v["name"], "cases": len(v["cases"]), "builtin": False} for k, v in SETS.items()]}


@router.get("/testsets/{sid}")
def get_set(sid: str):
    return _get(sid)


@router.post("/testsets")
async def import_set(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        ts = runner.parse_testset(raw, file.filename or "")
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"测试集不合法：{e}")
    sid = uuid.uuid4().hex[:8]
    SETS[sid] = ts
    return {"id": sid, "name": ts["name"], "cases": len(ts["cases"])}


@router.post("/testsets/{sid}/run")
def run(sid: str, body: RunBody | None = None):
    body = body or RunBody()
    ts = _get(sid)
    opts = {o["id"]: o for o in engine_options()}
    if body.engine not in opts or not opts[body.engine]["selectable"]:
        raise HTTPException(400, f"引擎 {body.engine} 不可选")
    out = runner.run_testset(ts, body.engine, body.skip_trial)
    LATEST[sid] = out["id"]
    return out


def _run(sid: str, run_id: str | None) -> dict:
    rid = run_id or LATEST.get(sid)
    if not rid or rid not in runner.RUNS:
        raise HTTPException(404, "还没有运行记录：先运行测试集")
    return runner.RUNS[rid]


@router.get("/testsets/{sid}/report")
def report(sid: str, run: str | None = None):
    return _run(sid, run)


@router.get("/testsets/{sid}/report.md", response_class=PlainTextResponse)
def report_md(sid: str, run: str | None = None):
    return PlainTextResponse(runner.to_markdown(_run(sid, run)), headers={"Content-Disposition": 'attachment; filename="report.md"'})


@router.get("/testsets/{sid}/report.csv", response_class=PlainTextResponse)
def report_csv(sid: str, run: str | None = None):
    return PlainTextResponse(runner.to_csv(_run(sid, run)), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="report.csv"'})

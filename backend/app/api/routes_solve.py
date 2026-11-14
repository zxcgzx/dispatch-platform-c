"""求解黑盒 / 结果 / 评估 / 协商调整路由。"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..metrics.evaluate import evaluate
from ..solver import blackbox
from ..spec.schema import DeltaPi, ModelSpec, StructuralOp
from ..storage import db
from .routes_tasks import _load_draft, _load_parse, _save, _task, _ver, task_state, window_of

router = APIRouter()


class SolveBody(BaseModel):
    version: int | None = None
    mode: str | None = None


class FeedbackBody(BaseModel):
    mode: str


class AdjustPick(BaseModel):
    id: str
    values: dict = {}


class AdjustBody(BaseModel):
    version: int | None = None
    picks: list[AdjustPick]


def _version(tid: str, v: int | None) -> db.Version:
    _task(tid)
    row = db.get_version(tid, v) if v else db.latest_version(tid)
    if row is None:
        raise HTTPException(404, "还没有已确认的版本，先确认规格")
    return row


def _job_json(j: blackbox.Job) -> dict:
    return {"id": j.id, "task_id": j.task_id, "version": j.version, "mode": j.mode, "status": j.status, "elapsed_s": round(j.elapsed, 2),
            "error": j.error, "result": j.result, "lines": len(j.lines)}


@router.get("/solver/info")
def solver_info():
    return {"mode": settings.solver_mode, "mode_label": blackbox.MODE_LABEL[settings.solver_mode], "cmd": settings.solver_cmd,
            "modes": [{"id": m, "label": blackbox.MODE_LABEL[m]} for m in blackbox.MODES], "blackbox": True}


@router.get("/solver/result-schema")
def result_schema():
    return blackbox.result_schema()


@router.post("/tasks/{tid}/solve")
def solve(tid: str, body: SolveBody | None = None):
    body = body or SolveBody()
    row = _version(tid, body.version)
    if row.check_json and json.loads(row.check_json)["has_error"]:
        raise HTTPException(409, "校验有错误，不能进入求解：请先回到规格确认修正（警告可以带着继续）")
    mode = body.mode or settings.solver_mode
    if mode not in blackbox.MODES:
        raise HTTPException(400, f"未知求解模式：{mode}")
    if mode == "import":
        raise HTTPException(400, "import 模式请用 POST /tasks/{id}/results/import 上传结果 JSON")
    spec = ModelSpec.model_validate_json(row.spec_json)
    spec_path = db.version_dir(tid, row.version) / "spec.json"
    job = blackbox.start_solve(tid, row.version, spec_path, window_of(spec), mode, spec.solver_req.time_limit_s)
    return _job_json(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    j = blackbox.get_job(job_id)
    if j is None:
        raise HTTPException(404, "作业不存在")
    return {**_job_json(j), "log": list(j.lines)}


@router.get("/jobs/{job_id}/log")
def job_log(job_id: str):
    """SSE：实时推送求解日志；作业结束后发送 event: end。"""
    j = blackbox.get_job(job_id)
    if j is None:
        raise HTTPException(404, "作业不存在")

    def gen():
        sent = 0
        while True:
            with j.lock:
                new = j.lines[sent:]
            for ln in new:
                yield "data: " + json.dumps(ln, ensure_ascii=False) + "\n\n"
            sent += len(new)
            if j.status != "running" and sent >= len(j.lines):
                yield "event: end\ndata: " + json.dumps({"status": j.status, "error": j.error, "elapsed_s": round(j.elapsed, 2)}, ensure_ascii=False) + "\n\n"
                return
            time.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/tasks/{tid}/results/import")
def import_results(tid: str, body: dict, version: int | None = None):
    row = _version(tid, version)
    spec = ModelSpec.model_validate_json(row.spec_json)
    try:
        res = blackbox.import_result(tid, row.version, body, window_of(spec))
    except blackbox.ResultError as e:
        raise HTTPException(400, str(e))
    return {"version": row.version, "result": res}


@router.get("/tasks/{tid}/results")
def get_results(tid: str, version: int | None = None):
    row = _version(tid, version)
    return {"version": row.version, "result": json.loads(row.result_json) if row.result_json else None,
            "mode": settings.solver_mode, "blackbox": True}


@router.post("/tasks/{tid}/evaluate")
def evaluate_task(tid: str, version: int | None = None):
    row = _version(tid, version)
    spec = ModelSpec.model_validate_json(row.spec_json)
    res = json.loads(row.result_json) if row.result_json else None
    out = evaluate(tid, row.version, spec, window_of(spec), res)
    db.update_version(tid, row.version, metrics_json=json.dumps(out["metrics"], ensure_ascii=False), risk_json=json.dumps({"risk": out["risk"], "suggestions": out["suggestions"]}, ensure_ascii=False))
    db.write_artifact(tid, row.version, "metrics.json", out)
    db.log(tid, f"v{row.version} 评估：风险 {out['risk']['risk_level']}（{out['risk']['source']}），建议 {len(out['suggestions'])} 条", version=row.version)
    return {"version": row.version, **out}


@router.get("/tasks/{tid}/evaluation")
def get_evaluation(tid: str, version: int | None = None):
    row = _version(tid, version)
    if not row.metrics_json:
        return {"version": row.version, "evaluated": False}
    rk = json.loads(row.risk_json) if row.risk_json else {}
    return {"version": row.version, "evaluated": True, "metrics": json.loads(row.metrics_json), **rk}


@router.post("/tasks/{tid}/feedback-mode")
def feedback_mode(tid: str, body: FeedbackBody):
    t = _task(tid)
    if body.mode not in ("negotiate", "reward"):
        raise HTTPException(400, "反馈方式只能是 negotiate（协商）或 reward")
    t.feedback_mode = body.mode
    db.save_task(t)
    return {"feedback_mode": t.feedback_mode}


def _num(v):
    if v is None or v == "":
        return None
    return float(v)


@router.post("/tasks/{tid}/adjust")
def adjust(tid: str, body: AdjustBody):
    """协商：把用户勾选并填好数值的建议生成新版本草稿（parent_version、change_reason 写明来自哪条风险），随后回到步骤 3。"""
    t = _task(tid)
    row = _version(tid, body.version)
    if not row.risk_json:
        raise HTTPException(400, "该版本还没有评估，先做风险评估")
    sugg = {s["id"]: s for s in json.loads(row.risk_json)["suggestions"]}
    if not body.picks:
        raise HTTPException(400, "请至少勾选一条建议")
    spec = ModelSpec.model_validate_json(row.spec_json)
    new = spec.model_copy(deep=True, update={"version": row.version + 1, "parent_version": row.version})
    reasons: list[str] = []
    for pk in body.picks:
        s = sugg.get(pk.id)
        if s is None:
            raise HTTPException(400, f"没有这条建议：{pk.id}")
        item = dict(s["item"])
        vals = pk.values or {}
        for f in s["fields_needed"]:                          # 建议里的数值一律留空，必须由用户填写
            v = vals.get(f)
            if v is None or v == "" or v == []:
                raise HTTPException(400, f"建议 {pk.id} 的“{f}”需要你填写（系统不替你定数值）")
        n_dp = max([int(d.id.split("-")[1]) for d in new.delta_pi] + [0]) + 1
        n_s = max([int(x.id.split("-")[1]) for x in new.structural] + [0]) + 1
        origin = f"negotiation:{pk.id}"
        try:
            if s["kind"] == "dp":
                target = vals.get("target") or item["target"]
                new.delta_pi.append(DeltaPi(id=f"dp-{n_dp}", component=item["component"], target=str(target), param=item["param"], operation=item["operation"],
                                            value=_num(vals.get("value")), periods=list(vals.get("periods") or []), source="explicit", evidence="", origin=origin))
            else:
                params = dict(item["params"])
                for f in s["fields_needed"]:
                    params[f] = int(vals[f]) if f in ("k", "K") else _num(vals[f])
                if item["op_id"] == "section_limit" and vals.get("branches"):
                    params["branches"] = [x.strip().upper() for x in str(vals["branches"]).replace("，", ",").split(",") if x.strip()]
                new.structural.append(StructuralOp(id=f"s-{n_s}", kind=item["kind"], op_id=item["op_id"], params=params, source="explicit", evidence="", origin=origin))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"建议 {pk.id} 的取值不合法：{e}")
        reasons.append(f"{s['from_code']}：{s['reason']}")
    new.change_reason = f"协商调整（来自 v{row.version} 的风险评估）：" + "；".join(reasons)
    parse = _load_parse(t)
    if parse is not None:
        parse.delta_pi = [x.model_copy(deep=True) for x in new.delta_pi]
        parse.structural = [x.model_copy(deep=True) for x in new.structural]
    _save(t, parse, new)
    db.log(tid, f"协商调整：由 v{row.version} 生成 v{new.version} 草稿（{len(body.picks)} 条建议）")
    return task_state(tid)

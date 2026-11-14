"""任务路由：新建 / 解析 / 追问回答 / 规格草稿 / 确认出版本 / 版本与产物 / 差异 / 校验 / 日志。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ValidationError

from ..checks.engine import CheckContext, run_checks
from ..data.library import Window, build_window, default_snapshot_id
from ..modeling import dialog
from ..modeling.codegen import generate_code, parse_markers
from ..modeling.demo_engine import DemoRuleEngine
from ..modeling.formulas import build_formulas, to_tex_file
from ..modeling.pipeline import engine_options, make_context, spec_from_parse
from ..modeling.scale import estimate
from ..modeling.state import ParseContext, ParseResult
from ..spec.diff import spec_diff
from ..spec.level import level_reasons
from ..spec.schema import ModelSpec
from ..spec.whitelist import whitelist_json
from ..modeling import operators as ops
from ..storage import db

router = APIRouter()


# ------------------------------------------------------------------------------------------------
# 请求体
# ------------------------------------------------------------------------------------------------
class TaskCreate(BaseModel):
    instruction: str = ""
    snapshot: str | None = None
    start: str | None = None
    engine: str = "demo"
    ask_enabled: bool = True
    max_rounds: int | None = None


class ParseBody(BaseModel):
    instruction: str | None = None
    supplement: bool = False                  # True：把 instruction 追加到原指令后重新解析，并回放此前的回答
    engine: str | None = None
    ask_enabled: bool | None = None
    max_rounds: int | None = None


class AnswerBody(BaseModel):
    question_id: str
    answer: str


class ConfirmBody(BaseModel):
    change_reason: str | None = None


class CheckBody(BaseModel):
    version: int | None = None
    draft: bool = False


# ------------------------------------------------------------------------------------------------
# 工具
# ------------------------------------------------------------------------------------------------
def _task(tid: str) -> db.Task:
    t = db.get_task(tid)
    if t is None:
        raise HTTPException(404, f"任务不存在：{tid}")
    return t


def ctx_of(t: db.Task) -> ParseContext:
    start = datetime.fromisoformat(t.start) if t.start else None
    return make_context(t.snapshot_id, start, t.ask_enabled, t.max_rounds)


def window_of(spec: ModelSpec) -> Window:
    s = spec.snapshot
    start = datetime.fromisoformat(s.start) if s.start else None
    ids = list(s.snapshot_ids)
    return Window(start, len(ids) or s.periods, s.step_min, ids, len(ids) == 1, [])


def check_ctx(spec: ModelSpec, skip_trial: bool = False) -> CheckContext:
    from ..data.library import get_snapshot

    win = window_of(spec)
    snap, topo = get_snapshot(win.snapshot_ids[0])
    return CheckContext(snap, topo, win, skip_trial=skip_trial)


def _load_parse(t: db.Task) -> ParseResult | None:
    return ParseResult.model_validate_json(t.parse_json) if t.parse_json else None


def _load_draft(t: db.Task) -> ModelSpec | None:
    return ModelSpec.model_validate_json(t.draft_json) if t.draft_json else None


def _save(t: db.Task, parse: ParseResult | None = None, draft: ModelSpec | None = None) -> None:
    if parse is not None:
        t.parse_json = parse.model_dump_json()
    if draft is not None:
        t.draft_json = draft.model_dump_json()
    db.save_task(t)


def _next_version_no(tid: str) -> int:
    lv = db.latest_version(tid)
    return (lv.version if lv else 0) + 1


def _sync_draft_from_parse(draft: ModelSpec, res: ParseResult) -> ModelSpec:
    d = draft.model_copy(deep=True)
    d.delta_pi = [x.model_copy(deep=True) for x in res.delta_pi]
    d.structural = [x.model_copy(deep=True) for x in res.structural]
    return d


def confirm_blockers(spec: ModelSpec, parse: ParseResult | None) -> list[str]:
    """“确认并生成代码”的前置条件：推断项必须确认、待补字段必须补全、不能没有任何修改。"""
    b: list[str] = []
    if parse is not None and parse.pending:
        b.append("还有未指明对象的修改意图，请先回答追问（系统不会猜对象）")
    if not spec.delta_pi and not spec.structural:
        b.append("没有任何参数修改或结构修改（层级：待追问）")
    for d in spec.delta_pi:
        if d.pending_fields:
            b.append(f"{d.id}（{d.target}.{d.param}）还有待补充项：{'、'.join({'periods': '时段', 'value': '幅度', 'target': '对象'}.get(f, f) for f in d.pending_fields)}")
        if d.source == "inferred":
            if d.value is None and "value" not in d.pending_fields:
                b.append(f"{d.id}（{d.target}.{d.param}）是推断项，幅度未填")
            elif not d.confirmed:
                b.append(f"{d.id}（{d.target}.{d.param}）是推断项，需要你确认后才能生成代码")
    for s in spec.structural:
        if s.pending_fields:
            b.append(f"{s.id}（{s.op_id}）参数未补全：{'、'.join(s.pending_fields)}")
    return b


def _version_summary(v: db.Version) -> dict:
    chk = json.loads(v.check_json) if v.check_json else None
    return {
        "version": v.version, "parent_version": v.parent_version, "change_reason": v.change_reason, "created_at": v.created_at,
        "level": v.level, "checked": chk is not None, "has_error": bool(chk and chk["has_error"]), "has_warning": bool(chk and chk["has_warning"]),
        "counts": chk["counts"] if chk else None, "solved": bool(v.result_json), "evaluated": bool(v.metrics_json),
    }


def _same_content(a: ModelSpec, b: ModelSpec) -> bool:
    d = spec_diff(a.model_dump(), b.model_dump())
    return d["total"] == 0 and not d["instruction_changed"]


def task_state(tid: str) -> dict[str, Any]:
    t = _task(tid)
    parse, draft = _load_parse(t), _load_draft(t)
    versions = db.list_versions(tid)
    latest = versions[-1] if versions else None
    dirty = True
    if draft is not None and latest is not None:
        dirty = not _same_content(ModelSpec.model_validate_json(latest.spec_json), draft)
    out: dict[str, Any] = {
        "task": {"id": t.id, "created_at": t.created_at, "instruction": t.instruction, "snapshot_id": t.snapshot_id, "start": t.start,
                 "engine": t.engine, "ask_enabled": t.ask_enabled, "max_rounds": t.max_rounds, "feedback_mode": t.feedback_mode},
        "parse": parse.model_dump() if parse else None,
        "spec": draft.model_dump() if draft else None,
        "level": level_reasons(draft) if draft else None,
        "versions": [_version_summary(v) for v in versions],
        "current_version": latest.version if latest else None,
        "draft_dirty": dirty,
        "confirm_blockers": confirm_blockers(draft, parse) if draft else ["尚未解析指令"],
        "draft_parent": draft.parent_version if draft else None,
        "draft_change_reason": draft.change_reason if draft else None,
    }
    return out


# ------------------------------------------------------------------------------------------------
# 元信息
# ------------------------------------------------------------------------------------------------
@router.get("/meta")
def meta():
    """工作台元信息：引擎选项、白名单、算子库、默认设置。"""
    from ..config import app_config

    cfg = app_config()
    return {
        "engines": engine_options(), "whitelist": whitelist_json(), "operators": ops.operator_json(),
        "rules": cfg["rules"], "questions": cfg["questions"],
        "scenarios": [
            {"id": "load", "title": "负荷增长", "level": "L1", "icon": "load",
             "desc": "母线 43 的有功负荷提高 20%，机组重新分配出力",
             "text": "母线 43 的有功负荷提高 20%。", "answers": {}},
            {"id": "outage", "title": "线路检修停运", "level": "L1", "icon": "outage",
             "desc": "110kV 线路 L376 检修，校验是否形成孤岛并移出可开断集合",
             "text": "110kV 线路 L376（54–359）检修停运。", "answers": {}},
            {"id": "heat", "title": "高温限额下降 · 少动开关", "level": "L4", "icon": "heat",
             "desc": "L875 热稳限额大幅下降，要求满足 N−1，尽量少动开关：推断 + 结构修改",
             "text": "持续高温，线路 L875 热稳限额下降，要求满足 N−1，尽量少动开关。", "answers": {"value": "降低 92%"}},
            {"id": "limit", "title": "开关次数限制", "level": "L3", "icon": "switch",
             "desc": "L875 限额设为 17 MVA，优化拓扑，每次调整开关操作不超过 2 次",
             "text": "线路 L875 热稳限额设为 17 MVA，开关操作不超过 2 次。", "answers": {}},
            {"id": "gen", "title": "机组出力受限", "level": "L2", "icon": "gen",
             "desc": "母线 314 上的机组出力受限，系统自动补足缺口",
             "text": "母线 314 上的机组近期出力受限。", "answers": {"value": "降低 95%"}},
        ],
        "templates": [
            {"id": "outage", "label": "检修", "text": "110kV 线路 L376（54–359）第 5–12 时段检修停运。"},
            {"id": "heat", "label": "高温限额下降", "text": "明天午后持续高温，220kV 线路 L155（174–172）热稳能力下降。"},
            {"id": "load", "label": "负荷增长", "text": "第 1–8 时段，母线 43 的有功负荷提高 20%。"},
            {"id": "switch", "label": "开关次数限制", "text": "母线 43 负荷提高 10%，每个时段开关操作不超过 2 次。"},
            {"id": "section", "label": "断面限额", "text": "由 L428、L429 组成的断面，有功限额设为 300 MW。"},
        ],
    }


@router.get("/demo-cases")
def demo_cases():
    from ..config import DATA_DIR

    return json.loads((DATA_DIR / "testsets" / "demo_cases.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------
# 任务
# ------------------------------------------------------------------------------------------------
@router.get("/tasks")
def list_tasks():
    out = []
    for t in db.list_tasks():
        lv = db.latest_version(t.id)
        out.append({"id": t.id, "created_at": t.created_at, "instruction": t.instruction, "engine": t.engine,
                    "version": lv.version if lv else None, "level": lv.level if lv else None})
    return {"tasks": out}


@router.post("/tasks")
def create_task(body: TaskCreate):
    sid = body.snapshot or default_snapshot_id()
    if sid is None:
        raise HTTPException(400, "断面库为空：请把断面文件放入 data/snapshots/")
    opts = {o["id"]: o for o in engine_options()}
    if body.engine not in opts:
        raise HTTPException(400, f"未知引擎：{body.engine}")
    if not opts[body.engine]["selectable"]:
        raise HTTPException(400, f"“{opts[body.engine]['label']}”目前不可选：{opts[body.engine]['note']}")
    try:
        if body.start:
            datetime.fromisoformat(body.start)
        make_context(sid, datetime.fromisoformat(body.start) if body.start else None)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    from ..config import app_config

    mr = body.max_rounds if body.max_rounds is not None else app_config()["questions"]["max_rounds"]
    t = db.create_task(instruction=body.instruction.strip(), snapshot_id=sid, start=body.start, engine=body.engine,
                       ask_enabled=body.ask_enabled, max_rounds=max(0, int(mr)))
    db.log(t.id, f"新建任务：断面 {sid}，引擎 {body.engine}，追问 {'开' if body.ask_enabled else '关'}（最多 {t.max_rounds} 轮）")
    return task_state(t.id)


@router.get("/tasks/{tid}")
def get_task_state(tid: str):
    return task_state(tid)


def _run_engine(t: db.Task, instruction: str, ctx: ParseContext) -> ParseResult:
    if t.engine == "demo":
        return DemoRuleEngine().parse(instruction, ctx)
    if t.engine == "openai":
        from ..modeling.openai_engine import parse_with_fallback
        return parse_with_fallback(instruction, ctx)
    if t.engine == "external":
        from ..modeling.external_engine import parse_with_fallback as ext
        return ext(instruction, ctx)
    raise HTTPException(400, f"引擎 {t.engine} 目前不可用")


@router.post("/tasks/{tid}/parse")
def parse_task(tid: str, body: ParseBody | None = None):
    body = body or ParseBody()
    t = _task(tid)
    if body.engine and body.engine != t.engine:
        opts = {o["id"]: o for o in engine_options()}
        if body.engine not in opts or not opts[body.engine]["selectable"]:
            raise HTTPException(400, f"引擎 {body.engine} 不可选")
        t.engine = body.engine
    if body.ask_enabled is not None:
        t.ask_enabled = body.ask_enabled
    if body.max_rounds is not None:
        t.max_rounds = max(0, body.max_rounds)
    old_parse = _load_parse(t)
    text = (body.instruction if body.instruction is not None else t.instruction).strip()
    if not text:
        raise HTTPException(400, "请先输入调度指令")
    if body.supplement and old_parse and body.instruction:
        text = (old_parse.instruction.rstrip("。；; ") + "；" + body.instruction.strip()).strip()
    ctx = ctx_of(t)
    res = _run_engine(t, text, ctx)
    replayed = 0
    if body.supplement and old_parse:                      # 回放此前的回答（问题 id 仍存在才应用）
        for a in old_parse.answers:
            if a.raw:
                try:
                    res = dialog.apply_answer(res, a.question_id, a.raw, ctx)
                    replayed += 1
                except ValueError:
                    pass
    t.instruction = text
    latest = db.latest_version(tid)
    draft = spec_from_parse(tid, _next_version_no(tid), res, ctx, parent=latest.version if latest else None,
                            reason="重新解析指令" if latest else None)
    _save(t, res, draft)
    db.log(tid, f"解析指令（{res.engine_name}，{res.elapsed_ms:.0f} ms）：判级 {res.level}；Δπ {len(res.delta_pi)} 项，s {len(res.structural)} 项，追问 {len(res.questions)} 个"
           + (f"；回放回答 {replayed} 条" if replayed else "") + (f"；{res.fallback_note}" if res.fallback_note else ""))
    return task_state(tid)


@router.post("/tasks/{tid}/answer")
def answer_task(tid: str, body: AnswerBody):
    t = _task(tid)
    parse, draft = _load_parse(t), _load_draft(t)
    if parse is None or draft is None:
        raise HTTPException(400, "还没有解析指令")
    ctx = ctx_of(t)
    try:
        res = dialog.apply_answer(parse.model_copy(deep=True), body.question_id, body.answer, ctx)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _save(t, res, _sync_draft_from_parse(draft, res))
    db.log(tid, f"回答追问 {body.question_id}：{res.answers[-1].answer}")
    return task_state(tid)


# ------------------------------------------------------------------------------------------------
# 规格草稿
# ------------------------------------------------------------------------------------------------
@router.get("/tasks/{tid}/spec")
def get_spec(tid: str):
    t = _task(tid)
    d = _load_draft(t)
    if d is None:
        raise HTTPException(404, "还没有规格草稿")
    return d.model_dump()


@router.put("/tasks/{tid}/spec")
def put_spec(tid: str, body: dict):
    t = _task(tid)
    parse = _load_parse(t)
    if parse is None:
        raise HTTPException(400, "还没有解析指令")
    try:
        body = dict(body)
        body["task_id"] = tid
        spec = ModelSpec.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, "规格格式不合法：" + "；".join(f"{'.'.join(map(str, x['loc']))}：{x['msg']}" for x in e.errors()[:4]))
    spec.version = _next_version_no(tid)
    for d in spec.delta_pi:                                 # 幅度已填：该字段不再待补
        if d.value is not None:
            d.pending_fields = [f for f in d.pending_fields if f != "value"]
    parse.delta_pi = [x.model_copy(deep=True) for x in spec.delta_pi]
    parse.structural = [x.model_copy(deep=True) for x in spec.structural]
    parse = dialog.finalize(parse, ctx_of(t))
    _save(t, parse, spec)
    db.log(tid, "保存规格草稿")
    return task_state(tid)


@router.get("/tasks/{tid}/draft/preview")
def draft_preview(tid: str):
    """草稿的公式与规模估算（确认前就能看公式；代码要确认后才生成）。"""
    t = _task(tid)
    d = _load_draft(t)
    if d is None:
        raise HTTPException(404, "还没有规格草稿")
    return {"formulas": build_formulas(d), "scale": estimate(d, window_of(d))}


# ------------------------------------------------------------------------------------------------
# 确认出版本
# ------------------------------------------------------------------------------------------------
def _auto_reason(prev: ModelSpec | None, spec: ModelSpec) -> str:
    if prev is None:
        return "首次确认：指令解析结果"
    d = spec_diff(prev.model_dump(), spec.model_dump())
    parts = []
    for tag, lst in (("新增", "added"), ("删除", "removed")):
        parts += [f"{tag} {x['key']}" for x in d["delta_pi"][lst] + d["structural"][lst]]
    parts += [f"修改 {x['key']}（{'、'.join(c['field'] for c in x['changes'])}）" for x in d["delta_pi"]["modified"] + d["structural"]["modified"]]
    parts += [f"ω.{c['field']}" for c in d["omega"]] + [f"R.{c['field']}" for c in d["solver_req"]]
    return "；".join(parts[:6]) + ("…" if len(parts) > 6 else "") if parts else "无实质改动"


def build_version(tid: str, spec: ModelSpec, reason: str | None, skip_trial: bool = False) -> db.Version:
    """生成产物（公式、代码、校验）并存成一个版本。"""
    code = generate_code(spec)
    formulas = build_formulas(spec)
    report = run_checks(spec, check_ctx(spec, skip_trial=skip_trial), code)
    v = spec.version
    db.write_artifact(tid, v, "spec.json", spec.model_dump())
    db.write_artifact(tid, v, "model.tex", to_tex_file(spec, formulas))
    db.write_artifact(tid, v, "model.py", code)
    db.write_artifact(tid, v, "check.json", report)
    from ..spec.level import compute_level

    row = db.add_version(task_id=tid, version=v, parent_version=spec.parent_version, change_reason=reason, level=compute_level(spec),
                         spec_json=spec.model_dump_json(), check_json=json.dumps(report, ensure_ascii=False))
    db.log(tid, f"v{v} 已生成：判级 {report['level']}；校验 错误 {report['counts']['error']} / 警告 {report['counts']['warn']} / 提示 {report['counts']['info']}", version=v)
    return row


@router.post("/tasks/{tid}/confirm")
def confirm(tid: str, body: ConfirmBody | None = None):
    body = body or ConfirmBody()
    t = _task(tid)
    parse, draft = _load_parse(t), _load_draft(t)
    if draft is None:
        raise HTTPException(400, "还没有规格草稿")
    blockers = confirm_blockers(draft, parse)
    if blockers:
        return JSONResponse(status_code=409, content={"detail": "不能确认：" + "；".join(blockers), "blockers": blockers})
    latest = db.latest_version(tid)
    prev = ModelSpec.model_validate_json(latest.spec_json) if latest else None
    if prev is not None and _same_content(prev, draft):
        return JSONResponse(status_code=409, content={"detail": f"与 v{prev.version} 完全相同，无需重复确认", "blockers": []})
    n = _next_version_no(tid)
    reason = body.change_reason or draft.change_reason or _auto_reason(prev, draft)
    spec = draft.model_copy(deep=True, update={"version": n, "parent_version": latest.version if latest else None, "change_reason": reason})
    row = build_version(tid, spec, reason)
    nxt = spec.model_copy(deep=True, update={"version": n + 1, "parent_version": n, "change_reason": None})
    _save(t, None, nxt)
    return {"state": task_state(tid), "version": _version_summary(row)}


# ------------------------------------------------------------------------------------------------
# 版本与产物
# ------------------------------------------------------------------------------------------------
def _ver(tid: str, v: int) -> db.Version:
    _task(tid)
    row = db.get_version(tid, v)
    if row is None:
        raise HTTPException(404, f"版本不存在：{tid} v{v}")
    return row


@router.get("/tasks/{tid}/versions")
def list_versions(tid: str):
    _task(tid)
    return {"versions": [_version_summary(v) for v in db.list_versions(tid)]}


@router.get("/tasks/{tid}/versions/{v}")
def get_version(tid: str, v: int):
    row = _ver(tid, v)
    return {**_version_summary(row), "spec": json.loads(row.spec_json),
            "check": json.loads(row.check_json) if row.check_json else None,
            "result": json.loads(row.result_json) if row.result_json else None,
            "metrics": json.loads(row.metrics_json) if row.metrics_json else None,
            "risk": json.loads(row.risk_json) if row.risk_json else None}


@router.get("/tasks/{tid}/versions/{v}/latex")
def get_latex(tid: str, v: int):
    row = _ver(tid, v)
    spec = ModelSpec.model_validate_json(row.spec_json)
    return {"formulas": build_formulas(spec), "tex": db.read_artifact(tid, v, "model.tex")}


@router.get("/tasks/{tid}/versions/{v}/code")
def get_code(tid: str, v: int):
    row = _ver(tid, v)
    code = db.read_artifact(tid, v, "model.py")
    if code is None:
        raise HTTPException(404, "该版本没有代码")
    spec = ModelSpec.model_validate_json(row.spec_json)
    return {"code": code, "markers": parse_markers(code), "filename": f"model_{tid}_v{v}.py",
            "scale": estimate(spec, window_of(spec))}


@router.get("/tasks/{tid}/versions/{v}/code.py", response_class=PlainTextResponse)
def download_code(tid: str, v: int):
    _ver(tid, v)
    return PlainTextResponse(db.read_artifact(tid, v, "model.py") or "", headers={"Content-Disposition": f'attachment; filename="model_{tid}_v{v}.py"'})


def _spec_of(tid: str, key: str) -> dict:
    if key == "draft":
        d = _load_draft(_task(tid))
        if d is None:
            raise HTTPException(404, "没有草稿")
        return d.model_dump()
    try:
        return json.loads(_ver(tid, int(key)).spec_json)
    except ValueError:
        raise HTTPException(400, f"版本参数不合法：{key}")


@router.get("/tasks/{tid}/diff")
def diff(tid: str, a: str, b: str):
    """两个版本的规格差异；a / b 可以是版本号或 draft（当前草稿）。"""
    return spec_diff(_spec_of(tid, a), _spec_of(tid, b))


@router.post("/tasks/{tid}/check")
def check(tid: str, body: CheckBody | None = None):
    body = body or CheckBody()
    t = _task(tid)
    if body.draft:
        d = _load_draft(t)
        if d is None:
            raise HTTPException(400, "还没有规格草稿")
        return run_checks(d, check_ctx(d, skip_trial=True))
    row = db.get_version(tid, body.version) if body.version else db.latest_version(tid)
    if row is None:
        raise HTTPException(404, "还没有已确认的版本，先确认规格")
    spec = ModelSpec.model_validate_json(row.spec_json)
    code = db.read_artifact(tid, row.version, "model.py")
    report = run_checks(spec, check_ctx(spec), code)
    db.write_artifact(tid, row.version, "check.json", report)
    db.update_version(tid, row.version, check_json=json.dumps(report, ensure_ascii=False))
    db.log(tid, f"v{row.version} 重新校验：错误 {report['counts']['error']} / 警告 {report['counts']['warn']}", version=row.version)
    return report


@router.get("/tasks/{tid}/log", response_class=PlainTextResponse)
def task_log(tid: str):
    _task(tid)
    return PlainTextResponse(db.read_log(tid) or "（暂无日志）")

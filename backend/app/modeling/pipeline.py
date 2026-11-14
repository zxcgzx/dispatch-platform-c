"""把 ParseResult 组装成 ModelSpec，并提供“解析 → 判级 → 校验”的一站式入口（工作台与测评模式共用）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..config import app_config, settings
from ..data.library import Window, build_window, default_snapshot_id, get_snapshot
from ..spec.schema import ModelSpec, SnapshotRef
from .demo_engine import DemoRuleEngine
from .state import ParseContext, ParseResult

DEMO_ENGINE_ID = "demo"


def make_context(snapshot_id: str | None = None, start: datetime | None = None, ask_enabled: bool = True,
                 max_rounds: int | None = None) -> ParseContext:
    sid = snapshot_id or default_snapshot_id()
    if sid is None:
        raise KeyError("断面库为空：请把断面文件放入 data/snapshots/")
    snap, topo = get_snapshot(sid)
    win = build_window(start, sid)
    cfg = app_config()["questions"]
    return ParseContext(snap=snap, topo=topo, window=win, ask_enabled=ask_enabled,
                        max_rounds=int(max_rounds if max_rounds is not None else cfg["max_rounds"]))


def snapshot_ref(win: Window) -> SnapshotRef:
    return SnapshotRef(snapshot_ids=list(win.snapshot_ids), start=win.start.isoformat(timespec="minutes") if win.start else None,
                       periods=win.periods, step_min=win.step_min, single_snapshot=win.periods == 1)


def spec_from_parse(task_id: str, version: int, res: ParseResult, ctx: ParseContext, parent: int | None = None,
                    reason: str | None = None) -> ModelSpec:
    spec = ModelSpec(task_id=task_id, version=version, parent_version=parent, change_reason=reason, instruction=res.instruction,
                     snapshot=snapshot_ref(ctx.window), delta_pi=[d.model_copy(deep=True) for d in res.delta_pi],
                     structural=[s.model_copy(deep=True) for s in res.structural])
    spec.omega.periods, spec.omega.step_min = ctx.window.periods, ctx.window.step_min
    if "n_minus_1" in res.omega_confirm:
        spec.omega.n_minus_1 = bool(res.omega_confirm["n_minus_1"])
    if any(s.op_id == "multi_period_acopf" for s in spec.structural):
        spec.omega.problem = "multi_period_acopf"
    return spec


def get_engine(engine_id: str):
    """引擎注册：demo 永远可用；openai / external 在各自模块里，缺依赖或没配置时由调用方回落。"""
    if engine_id == "demo":
        return DemoRuleEngine()
    if engine_id == "openai":
        from .openai_engine import OpenAICompatEngine
        return OpenAICompatEngine()
    if engine_id == "external":
        from .external_engine import ExternalMethodEngine
        return ExternalMethodEngine()
    raise KeyError(f"未知引擎：{engine_id}")


def engine_options() -> list[dict[str, Any]]:
    """顶栏“模型选择”的选项。selectable：能否选；configured：服务是否已配置（本地 Qwen 未配置时仍可选，会自动回落并提示）。"""
    llm_ok = settings.llm_mode == "openai" and bool(settings.llm_base_url)
    return [
        {"id": "demo", "label": "演示规则引擎", "selectable": True, "configured": True, "feature": "m1.model_select",
         "note": "离线，不依赖任何大模型"},
        {"id": "openai", "label": "本地 Qwen（OpenAI 兼容）", "selectable": True, "configured": llm_ok, "feature": "m1.model_select",
         "note": "已配置" if llm_ok else "未配置 LLM_BASE_URL（.env 里设 LLM_MODE=openai）：可以选，连不上时自动回落到演示规则引擎并提示"},
        {"id": "proopf", "label": "微调模型（接口预留）", "selectable": False, "configured": False, "feature": "m1.llm_proopf",
         "note": "接口预留：微调模型部署成 OpenAI 兼容接口后，改 LLM_BASE_URL / LLM_MODEL 即可使用"},
        {"id": "t2llm", "label": "课题 2 大模型（接口预留）", "selectable": False, "configured": False, "feature": "m1.llm_t2",
         "note": "接口预留：待课题 2 提供接口"},
        {"id": "external", "label": "外部建模引擎" + ("" if settings.method_endpoint else "（接口预留）"),
         "selectable": bool(settings.method_endpoint), "configured": bool(settings.method_endpoint), "feature": "m2.ext_model",
         "note": "已接入" if settings.method_endpoint else "接口预留：未配置 METHOD_ENDPOINT，不可选"},
    ]

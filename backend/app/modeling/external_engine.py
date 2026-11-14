"""ExternalMethodEngine：动态建模与去幻觉方法，接口预留。

POST {METHOD_ENDPOINT}/parse，请求 {instruction, snapshot_meta, whitelist, operators}，
响应 {delta_pi, structural, questions, findings}。
未配置时，模型选择里显示“动态建模与去幻觉方法（接口预留）”且不可选（见 pipeline.engine_options）。
"""
from __future__ import annotations

import time

import httpx
from pydantic import ValidationError

from ..config import settings
from ..spec.schema import DeltaPi, StructuralOp
from ..spec.whitelist import whitelist_json
from . import dialog
from . import operators as ops
from .demo_engine import DemoRuleEngine
from .openai_engine import LLMUnavailable, _entities_from_evidence
from .state import Finding, Option, ParseContext, ParseResult, Question


class ExternalMethodEngine:
    name = "external"
    display = "外部建模引擎"

    def answer(self, state: ParseResult, question_id: str, answer: str, ctx: ParseContext) -> ParseResult:
        """回答追问：待确认字段都记在规格草稿里，回答逻辑与引擎无关。"""
        return dialog.apply_answer(state.model_copy(deep=True), question_id, answer, ctx)

    def parse(self, instruction: str, ctx: ParseContext) -> ParseResult:
        ep = settings.method_endpoint
        if not ep:
            raise LLMUnavailable("未配置 METHOD_ENDPOINT")
        t0 = time.perf_counter()
        meta = {"system": "dali_905", "periods": ctx.periods, "step_min": ctx.window.step_min,
                "start": ctx.window.start.isoformat() if ctx.window.start else None,
                "counts": {"bus": len(ctx.snap.bus), "gen": len(ctx.snap.gen), "branch": len(ctx.snap.branch)}}
        try:
            r = httpx.post(f"{ep}/parse", timeout=60,
                           json={"instruction": instruction, "snapshot_meta": meta, "whitelist": whitelist_json(), "operators": ops.operator_json()})
            r.raise_for_status()
            raw = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        res = ParseResult(instruction=instruction, engine=self.name, engine_name=self.display)
        for i, d in enumerate(raw.get("delta_pi", []), start=1):
            try:
                d = dict(d)
                d["id"] = d.get("id") or f"dp-{i}"
                d.setdefault("pending_fields", ["value"] if d.get("source") == "inferred" and d.get("value") is None else [])
                res.delta_pi.append(DeltaPi.model_validate(d))
            except ValidationError as e:
                res.notes.append(f"外部方法返回的第 {i} 条 Δπ 不符合 schema：{e.errors()[0]['msg']}")
        for i, s in enumerate(raw.get("structural", []), start=1):
            try:
                s = dict(s)
                s["id"] = s.get("id") or f"s-{i}"
                res.structural.append(StructuralOp.model_validate(s))
            except ValidationError as e:
                res.notes.append(f"外部方法返回的第 {i} 条 s 不符合 schema：{e.errors()[0]['msg']}")
        for j, q in enumerate(raw.get("questions", []), start=1):
            res.notes.append(q if isinstance(q, str) else str(q.get("text", "")))
        for f in raw.get("findings", []):
            res.findings.append(Finding(code=str(f.get("code", "X501")), level=f.get("level", "warn"), message=str(f.get("message", "")),
                                        item_id=f.get("item_id"), suggestion=f.get("suggestion"), source="动态建模与去幻觉方法"))
        res.entities = _entities_from_evidence(res, instruction)
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return dialog.finalize(res, ctx)


def parse_with_fallback(instruction: str, ctx: ParseContext) -> ParseResult:
    try:
        return ExternalMethodEngine().parse(instruction, ctx)
    except LLMUnavailable as e:
        res = DemoRuleEngine().parse(instruction, ctx)
        res.fallback_note = f"动态建模与去幻觉方法接口不可用（{e}），已自动回落到演示规则引擎"
        return res

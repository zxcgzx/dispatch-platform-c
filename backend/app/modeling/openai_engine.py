"""OpenAICompatEngine：调用 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY（本地 Qwen 用 vLLM 起 OpenAI 兼容服务）。

流程：系统提示词（白名单、算子库、已知编号、schema 由程序注入）→ 输出先用 Pydantic 校验 → 失败就把错误信息发回重试一次
→ 仍失败转成追问 → 服务连不上时回落到演示规则引擎并提示。
判级仍由程序从规格推出，不信大模型自报。大模型输出的编号若不在 known_ids 里，不替换，保留给 M4 报 E101。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from ..spec.schema import DeltaPi, StructuralOp
from ..spec.whitelist import whitelist_json
from . import dialog
from . import operators as ops
from .demo_engine import DemoRuleEngine
from .state import Entity, ParseContext, ParseResult, PendingIntent, Question, Option

SYSTEM_PROMPT = """你是电网运行方式调整的建模助手，任务是把调度员的指令转换成“模型规格”JSON，不求解，不写求解代码。
只能使用下面给出的对象类型、参数和结构算子：{whitelist} {operators}
对象编号格式：母线 B{{BUS_I}}，支路 L{{行号}}，机组 G{{行号}}。只能使用指令中出现、并且在 {known_ids} 中存在的编号。
规则：
1. 每一项修改都要给 evidence：从指令原文逐字摘出的片段。
2. 指令给了具体数值的，source=explicit，填 operation 和 value；只描述现象、没给数值的，source=inferred，只填 direction，value 为 null，并在 inference_chain 写出“事件→机理→参数”。
3. 不得编造编号、数值或时段。对象、时段或幅度不明确时不要猜，写进 questions。
4. “满足 N−1”只表示确认 ω 里的 N−1 设置，不作为结构修改。
5. 只输出一个符合下面 schema 的 JSON 对象，不要任何解释文字：{json_schema}"""

FEWSHOT = [
    ("第 1–8 时段，母线 43 的有功负荷提高 20%。", {
        "delta_pi": [{"id": "dp-1", "component": "bus", "target": "B43", "param": "PD", "operation": "scale", "direction": None, "value": 1.2,
                      "periods": [1, 2, 3, 4, 5, 6, 7, 8], "source": "explicit", "evidence": "第 1–8 时段，母线 43 的有功负荷提高 20%",
                      "inference_chain": None}],
        "structural": [], "omega_confirm": {}, "questions": []}),
    ("午高峰高温，220kV 线路 L155 热稳限额下降，要求满足 N−1，尽量少动开关。", {
        "delta_pi": [{"id": "dp-1", "component": "branch", "target": "L155", "param": "RATE_A", "operation": None, "direction": "decrease",
                      "value": None, "periods": [], "source": "inferred", "evidence": "午高峰高温，220kV 线路 L155 热稳限额下降",
                      "inference_chain": ["高温", "热稳裕度下降", "调低 RATE_A"]}],
        "structural": [{"id": "s-1", "kind": "objective", "op_id": "switching_penalty", "params": {"beta": None}, "source": "explicit", "evidence": "尽量少动开关"}],
        "omega_confirm": {"n_minus_1": True, "evidence": "满足 N−1"},
        "questions": [{"field": "periods", "item_id": "dp-1", "text": "“午高峰”对应哪些时段？"},
                      {"field": "value", "item_id": "dp-1", "text": "L155 热稳限额下降幅度按多少考虑？"}]}),
]


class LLMDelta(BaseModel):
    id: str = ""
    component: str
    target: str
    param: str
    operation: str | None = None
    direction: str | None = None
    value: float | None = None
    periods: list[int] = Field(default_factory=list)
    source: str
    evidence: str = ""
    inference_chain: list[str] | None = None


class LLMStruct(BaseModel):
    id: str = ""
    kind: str
    op_id: str
    params: dict = Field(default_factory=dict)
    source: str = "explicit"
    evidence: str = ""
    custom_code: str | None = None


class LLMQuestion(BaseModel):
    field: str = "other"
    item_id: str | None = None
    text: str = ""


class LLMOutput(BaseModel):
    delta_pi: list[LLMDelta] = Field(default_factory=list)
    structural: list[LLMStruct] = Field(default_factory=list)
    omega_confirm: dict = Field(default_factory=dict)
    questions: list[LLMQuestion] = Field(default_factory=list)


class LLMUnavailable(Exception):
    """服务连不上：回落到演示规则引擎。"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < i:
        raise ValueError("输出里没有 JSON 对象")
    return json.loads(text[i:j + 1])


class OpenAICompatEngine:
    name = "openai"
    display = "本地 Qwen（OpenAI 兼容）"

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None, timeout: float = 60.0):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.timeout = timeout

    # ------------------------------------------------------------------ HTTP
    def _chat(self, messages: list[dict]) -> str:
        if not self.base_url:
            raise LLMUnavailable("未配置 LLM_BASE_URL")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", headers=headers, timeout=self.timeout,
                           json={"model": self.model, "messages": messages, "temperature": 0, "response_format": {"type": "json_object"}})
            if r.status_code == 400 and "response_format" in r.text:   # 个别服务不支持 response_format
                r = httpx.post(f"{self.base_url}/chat/completions", headers=headers, timeout=self.timeout,
                               json={"model": self.model, "messages": messages, "temperature": 0})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}") from e
        except httpx.HTTPStatusError as e:
            raise LLMUnavailable(f"HTTP {e.response.status_code}: {e.response.text[:200]}") from e

    def _messages(self, instruction: str, ctx: ParseContext) -> list[dict]:
        known = sorted(ctx.snap.known_ids(), key=lambda s: (s[0], int(s[1:])))
        # 编号全集太长：只给规模与范围，由程序在输出后校验是否存在
        known_desc = (f"母线 B{int(ctx.snap.bus.BUS_I.min())}–B{int(ctx.snap.bus.BUS_I.max())}（共 {len(ctx.snap.bus)} 个，BUS_I 不连续）、"
                      f"支路 L1–L{len(ctx.snap.branch)}、机组 G1–G{len(ctx.snap.gen)}")
        sysmsg = SYSTEM_PROMPT.format(
            whitelist=json.dumps(whitelist_json(), ensure_ascii=False),
            operators=json.dumps(ops.operator_json(), ensure_ascii=False),
            known_ids=known_desc,
            json_schema=json.dumps(LLMOutput.model_json_schema(), ensure_ascii=False))
        msgs = [{"role": "system", "content": sysmsg}]
        for q, a in FEWSHOT:
            msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(a, ensure_ascii=False)}]
        msgs.append({"role": "user", "content": instruction})
        return msgs

    def answer(self, state: ParseResult, question_id: str, answer: str, ctx: ParseContext) -> ParseResult:
        """回答追问：待确认字段都记在规格草稿里，回答逻辑与引擎无关。"""
        return dialog.apply_answer(state.model_copy(deep=True), question_id, answer, ctx)

    # ------------------------------------------------------------------ parse
    def parse(self, instruction: str, ctx: ParseContext) -> ParseResult:
        t0 = time.perf_counter()
        msgs = self._messages(instruction, ctx)
        raw = self._chat(msgs)                      # 连不上抛 LLMUnavailable，由调用方回落
        out: LLMOutput | None = None
        err = ""
        for attempt in range(2):
            try:
                out = LLMOutput.model_validate(_extract_json(raw))
                break
            except (ValueError, ValidationError, json.JSONDecodeError) as e:
                err = str(e)[:600]
                if attempt == 0:
                    msgs = msgs + [{"role": "assistant", "content": raw},
                                   {"role": "user", "content": f"你的输出没有通过 schema 校验：{err}\n请只输出一个符合 schema 的 JSON 对象。"}]
                    raw = self._chat(msgs)
        res = ParseResult(instruction=instruction, engine=self.name, engine_name=self.display)
        if out is None:                              # 仍失败：转成追问，不编造
            res.questions = [Question(id="q-llm-format", field="other", text="大模型输出格式有误，没能解析出规格。请换种说法，或直接在规格表里填写。",
                                      options=[], blocking=True)]
            res.notes.append(f"大模型输出两次都没通过校验：{err}")
            res.elapsed_ms = (time.perf_counter() - t0) * 1000
            res.level = "待追问"
            return res
        self._to_result(out, res, ctx)
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return dialog.finalize(res, ctx)

    def _to_result(self, out: LLMOutput, res: ParseResult, ctx: ParseContext) -> None:
        text = res.instruction
        for i, d in enumerate(out.delta_pi, start=1):
            try:
                comp = d.component if d.component in ("bus", "gen", "branch") else "bus"
                src = "inferred" if d.source == "inferred" else "explicit"
                dp = DeltaPi(id=f"dp-{i}", component=comp, target=d.target, param=d.param,  # type: ignore[arg-type]
                             operation=d.operation if d.operation in ("scale", "set", "add") else None,  # type: ignore[arg-type]
                             direction=d.direction if d.direction in ("increase", "decrease", "set_zero") else None,  # type: ignore[arg-type]
                             value=None if src == "inferred" else d.value, periods=[p for p in d.periods], source=src,  # type: ignore[arg-type]
                             evidence=d.evidence, inference_chain=d.inference_chain, confirmed=False,
                             pending_fields=(["value"] if src == "inferred" else []))
                res.delta_pi.append(dp)
            except ValidationError as e:
                res.notes.append(f"丢弃一条无法转换的修改：{e.errors()[0]['msg']}")
        for i, s in enumerate(out.structural, start=1):
            kind = s.kind if s.kind in ("problem", "constraint", "objective") else "constraint"
            res.structural.append(StructuralOp(id=f"s-{i}", kind=kind, op_id=s.op_id, params=s.params, source="explicit",  # type: ignore[arg-type]
                                               evidence=s.evidence, custom_code=s.custom_code))
        if "n_minus_1" in out.omega_confirm:
            res.omega_confirm = {"n_minus_1": bool(out.omega_confirm["n_minus_1"]), "evidence": str(out.omega_confirm.get("evidence", ""))}
        # 时段 / 幅度没给：交给追问（程序判断，不信模型的 questions 文本）
        for d in res.delta_pi:
            if not d.periods and d.source == "inferred":
                d.pending_fields.append("periods")
        res.notes += [q.text for q in out.questions if q.text]
        res.entities = _entities_from_evidence(res, text)


def _entities_from_evidence(res: ParseResult, text: str) -> list[Entity]:
    """大模型路径的解析卡片：用 evidence 在原文里的位置生成实体（对象编号按原文片段）。"""
    ents: list[Entity] = []
    for d in res.delta_pi:
        i = text.find(d.evidence) if d.evidence else -1
        if i >= 0:
            ents.append(Entity(id=f"e{len(ents) + 1}", type="keyword", text=d.evidence, start=i, end=i + len(d.evidence), status="ok",
                               role="inference" if d.source == "inferred" else "magnitude", item_ids=[d.id]))
    for s in res.structural:
        i = text.find(s.evidence) if s.evidence else -1
        if i >= 0:
            ents.append(Entity(id=f"e{len(ents) + 1}", type="keyword", text=s.evidence, start=i, end=i + len(s.evidence), status="ok", role="structural", item_ids=[s.id]))
    return ents


def parse_with_fallback(instruction: str, ctx: ParseContext) -> ParseResult:
    """openai 引擎入口：连不上自动回落到演示规则引擎并提示。"""
    try:
        return OpenAICompatEngine().parse(instruction, ctx)
    except LLMUnavailable as e:
        res = DemoRuleEngine().parse(instruction, ctx)
        res.fallback_note = f"本地 Qwen 服务不可用（{e}），已自动回落到演示规则引擎"
        return res

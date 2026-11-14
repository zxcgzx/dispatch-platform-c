"""建模引擎的输入输出模型：ParseContext / ParseResult / Entity / Question 等。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..data.library import Window
from ..data.snapshot import Snapshot
from ..data.topology import Topology
from ..spec.schema import DeltaPi, StructuralOp


class Entity(BaseModel):
    """指令里识别出的实体（母线 / 支路 / 机组 / 时段 / 电压等级 / 关键词），带原文位置。"""

    id: str
    type: Literal["bus", "branch", "gen", "period", "kv", "keyword"]
    text: str
    start: int
    end: int
    object_id: str | None = None                  # B43 / L155 / G237
    status: Literal["found", "not_found", "ambiguous", "ok", "fuzzy"] = "found"
    candidates: list[str] = Field(default_factory=list)   # ambiguous：候选编号
    periods: list[int] | None = None              # period：明确时段（空列表 = 全部）；fuzzy 时为 None
    kv: float | None = None
    role: str | None = None                       # keyword：inference / outage / n1 / structural
    rule_id: str | None = None
    note: str | None = None
    item_ids: list[str] = Field(default_factory=list)     # 这个实体支撑的规格条目（点实体 → 高亮这些条目的 evidence）


class Option(BaseModel):
    label: str
    value: str
    disabled: bool = False
    hint: str | None = None


class Question(BaseModel):
    id: str                                       # q-{item_id}-{field}
    field: Literal["target", "periods", "value", "beta", "other"]
    item_id: str | None = None
    param: str | None = None                      # field = other 时的算子参数名，如 limit_mw
    text: str
    options: list[Option] = Field(default_factory=list)
    multi: bool = False                           # 选项可多选（时段）
    allow_free_text: bool = True
    free_text_hint: str | None = None
    basis: str | None = None                      # 依据：如“高温 → 热稳裕度下降”
    blocking: bool = True


class PendingIntent(BaseModel):
    """还没有确定对象的修改意图：对象不明确（没写 / 并联多条）时先挂起，不编造对象。"""

    id: str
    component: Literal["bus", "gen", "branch"]
    param: str
    operation: Literal["scale", "set", "add"] | None = None
    direction: Literal["increase", "decrease", "set_zero"] | None = None
    value: float | None = None
    source: Literal["explicit", "inferred"]
    evidence: str
    inference_chain: list[str] | None = None
    periods: list[int] = Field(default_factory=list)
    periods_unresolved: bool = False
    candidates: list[str] = Field(default_factory=list)
    label: str = ""


class Finding(BaseModel):
    code: str
    level: Literal["error", "warn", "info"]
    message: str
    item_id: str | None = None
    suggestion: str | None = None
    source: str = "内置"
    layer: int | None = None
    data: dict[str, Any] | None = None            # 附带的结构化内容（如回译对照）


class AnswerRecord(BaseModel):
    question_id: str
    question: str
    answer: str                                   # 展示用文字
    raw: str = ""                                 # 用户原始回答（补充条件重新解析时回放）


class ParseResult(BaseModel):
    instruction: str
    entities: list[Entity] = Field(default_factory=list)
    delta_pi: list[DeltaPi] = Field(default_factory=list)
    structural: list[StructuralOp] = Field(default_factory=list)
    omega_confirm: dict[str, Any] = Field(default_factory=dict)      # {"n_minus_1": True}
    pending: list[PendingIntent] = Field(default_factory=list)
    unresolved: dict[str, list[str]] = Field(default_factory=dict)   # item_id -> ["periods", "value", ...]
    questions: list[Question] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)            # 外部方法返回的 findings
    answers: list[AnswerRecord] = Field(default_factory=list)
    evidence_spans: dict[str, list[int]] = Field(default_factory=dict)   # item_id -> [start, end]，evidence 在指令原文中的位置
    level: str = "待追问"
    engine: str = ""
    engine_name: str = ""
    elapsed_ms: float = 0.0
    fallback_note: str | None = None                                  # 大模型连不上回落到演示规则引擎时的提示
    rounds: int = 0                                                   # 追问轮数：每出现一批新问题记一轮
    asked: list[str] = Field(default_factory=list)                    # 已经问过的问题 id
    suppressed: str | None = None                                     # 追问被关闭或达到轮数上限时的说明


@dataclass
class ParseContext:
    snap: Snapshot
    topo: Topology
    window: Window
    ask_enabled: bool = True
    max_rounds: int = 3
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def periods(self) -> int:
        return self.window.periods

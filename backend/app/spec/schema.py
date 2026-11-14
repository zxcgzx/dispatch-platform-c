"""模型规格：全平台唯一的中间产物 M = {ω, Δπ, s, R}（沿用 ProOPF），加断面、版本和校验信息。

前端类型由 JSON Schema 生成（backend/app/spec/export_schema.py → spec.schema.json → npm run gen:types），两边保持一致。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    # extra=forbid：规格里不允许出现未定义字段（防止大模型 / 外部方法夹带私货）。
    # json_schema_serialization_defaults_required：带默认值的字段在后端响应里总是存在，生成的前端类型里就是必填而不是可选。
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class DeltaPi(_Strict):
    """参数修改 Δπ，一条一项。"""

    id: str                                                        # "dp-1"
    component: Literal["bus", "gen", "branch"]
    target: str                                                    # "B43" / "G237" / "L155"
    param: str                                                     # 见白名单
    operation: Literal["scale", "set", "add"] | None = None        # 明确项必填
    direction: Literal["increase", "decrease", "set_zero"] | None = None  # 推断项必填
    value: float | None = None                                     # 推断项在用户确认前为 None
    periods: list[int] = Field(default_factory=list)               # 1..16；空列表表示全部时段
    source: Literal["explicit", "inferred"]
    evidence: str = ""                                             # 从指令原文逐字摘出的片段
    inference_chain: list[str] | None = None                       # 如 ["极端高温", "线路热稳裕度下降", "调低 RATE_A"]
    confirmed: bool = False                                        # 推断项经用户确认后为 True
    pending_fields: list[str] = Field(default_factory=list)        # 追问中尚未确定的字段：periods / value / target（实现扩展，见 ASSUMPTIONS）
    origin: str | None = None                                      # 条目来源：空 = 来自指令；"negotiation:r-1" = 协商调整建议（没有原文依据，W501 不检查）


class StructuralOp(_Strict):
    """结构修改 s。kind 对应 ProOPF 的 sp / sc / so。"""

    id: str                                                        # "s-1"
    kind: Literal["problem", "constraint", "objective"]
    op_id: str                                                     # 算子库 id
    params: dict = Field(default_factory=dict)
    source: Literal["explicit", "inferred"] = "explicit"
    evidence: str = ""
    custom_code: str | None = None                                 # 只有算子库里没有、由大模型写的新算子才有，界面标黄待审
    pending_fields: list[str] = Field(default_factory=list)        # 尚未确定的算子参数名（如 limit_mw）
    origin: str | None = None                                      # 同 DeltaPi.origin


class BaseModelDef(_Strict):
    """基础模型 ω。N−1 是 ω 的默认设置（任务书要求），s 只放 ω 之外的扩展。"""

    system: str = "dali_905"
    problem: Literal["multi_period_ac_ots", "multi_period_acopf"] = "multi_period_ac_ots"
    periods: int = 16
    step_min: int = 15
    n_minus_1: bool = True
    contingency_rule: str = "meshed_in_service"
    switchable_rule: str = "meshed_in_service"   # all_in_service / meshed_in_service / meshed_kv_ge_110


class SolverReq(_Strict):
    """求解要求 R。"""

    solver: Literal["builtin", "mock", "ipopt", "copt", "gurobi", "external"] = "builtin"
    time_limit_s: int = 60
    tolerance: float = 1e-6
    outputs: list[str] = Field(default_factory=lambda: ["branch_status", "gen_p", "bus_vm", "branch_flow"])


class SnapshotRef(_Strict):
    """断面引用：每个时段所用断面文件。"""

    source: str = "node_txt"
    system: str = "dali_905"
    snapshot_ids: list[str] = Field(default_factory=list)          # 长度 = periods
    start: str | None = None                                       # 起始时刻 ISO
    periods: int = 16
    step_min: int = 15
    single_snapshot: bool = False                                  # 只有一个文件，复制成 16 时段（演示模式）


class LevelOverride(_Strict):
    level: Literal["L1", "L2", "L3", "L4"]
    reason: str


class ModelSpec(_Strict):
    task_id: str
    version: int
    parent_version: int | None = None
    change_reason: str | None = None
    instruction: str
    snapshot: SnapshotRef
    omega: BaseModelDef = Field(default_factory=BaseModelDef)
    delta_pi: list[DeltaPi] = Field(default_factory=list)
    structural: list[StructuralOp] = Field(default_factory=list)
    solver_req: SolverReq = Field(default_factory=SolverReq)
    level_override: LevelOverride | None = None                    # 人工改选层级时记录 {level, reason}


def periods_or_all(periods: list[int], n: int) -> list[int]:
    """空列表 = 全部时段。"""
    return list(periods) if periods else list(range(1, n + 1))

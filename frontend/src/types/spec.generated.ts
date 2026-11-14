/* 由 backend/app/spec/spec.schema.json 生成，请勿手改（npm run gen:types） */

export type TaskId = string;
export type Version = number;
export type ParentVersion = number | null;
export type ChangeReason = string | null;
export type Instruction = string;
export type Source = string;
export type System = string;
export type SnapshotIds = string[];
export type Start = string | null;
export type Periods = number;
export type StepMin = number;
export type SingleSnapshot = boolean;
export type System1 = string;
export type Problem = "multi_period_ac_ots" | "multi_period_acopf";
export type Periods1 = number;
export type StepMin1 = number;
export type NMinus1 = boolean;
export type ContingencyRule = string;
export type SwitchableRule = string;
export type Id = string;
export type Component = "bus" | "gen" | "branch";
export type Target = string;
export type Param = string;
export type Operation = ("scale" | "set" | "add") | null;
export type Direction = ("increase" | "decrease" | "set_zero") | null;
export type Value = number | null;
export type Periods2 = number[];
export type Source1 = "explicit" | "inferred";
export type Evidence = string;
export type InferenceChain = string[] | null;
export type Confirmed = boolean;
export type PendingFields = string[];
export type Origin = string | null;
export type DeltaPi = DeltaPi1[];
export type Id1 = string;
export type Kind = "problem" | "constraint" | "objective";
export type OpId = string;
export type Source2 = "explicit" | "inferred";
export type Evidence1 = string;
export type CustomCode = string | null;
export type PendingFields1 = string[];
export type Origin1 = string | null;
export type Structural = StructuralOp[];
export type Solver = "builtin" | "mock" | "ipopt" | "copt" | "gurobi" | "external";
export type TimeLimitS = number;
export type Tolerance = number;
export type Outputs = string[];
export type Level = "L1" | "L2" | "L3" | "L4";
export type Reason = string;

export interface ModelSpec {
  task_id: TaskId;
  version: Version;
  parent_version: ParentVersion;
  change_reason: ChangeReason;
  instruction: Instruction;
  snapshot: SnapshotRef;
  omega: BaseModelDef;
  delta_pi: DeltaPi;
  structural: Structural;
  solver_req: SolverReq;
  level_override: LevelOverride | null;
}
/**
 * 断面引用：每个时段所用断面文件。
 */
export interface SnapshotRef {
  source: Source;
  system: System;
  snapshot_ids: SnapshotIds;
  start: Start;
  periods: Periods;
  step_min: StepMin;
  single_snapshot: SingleSnapshot;
}
/**
 * 基础模型 ω。N−1 是 ω 的默认设置（任务书要求），s 只放 ω 之外的扩展。
 */
export interface BaseModelDef {
  system: System1;
  problem: Problem;
  periods: Periods1;
  step_min: StepMin1;
  n_minus_1: NMinus1;
  contingency_rule: ContingencyRule;
  switchable_rule: SwitchableRule;
}
/**
 * 参数修改 Δπ，一条一项。
 */
export interface DeltaPi1 {
  id: Id;
  component: Component;
  target: Target;
  param: Param;
  operation: Operation;
  direction: Direction;
  value: Value;
  periods: Periods2;
  source: Source1;
  evidence: Evidence;
  inference_chain: InferenceChain;
  confirmed: Confirmed;
  pending_fields: PendingFields;
  origin: Origin;
}
/**
 * 结构修改 s。kind 对应 ProOPF 的 sp / sc / so。
 */
export interface StructuralOp {
  id: Id1;
  kind: Kind;
  op_id: OpId;
  params: Params;
  source: Source2;
  evidence: Evidence1;
  custom_code: CustomCode;
  pending_fields: PendingFields1;
  origin: Origin1;
}
export interface Params {
  [k: string]: unknown;
}
/**
 * 求解要求 R。
 */
export interface SolverReq {
  solver: Solver;
  time_limit_s: TimeLimitS;
  tolerance: Tolerance;
  outputs: Outputs;
}
export interface LevelOverride {
  level: Level;
  reason: Reason;
}

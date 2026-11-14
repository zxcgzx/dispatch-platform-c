"""求解（M5）：builtin / mock / import / external 四种模式。不做任何求解加速、调参、热启动。

- builtin（默认）：内置 HiGHS 求解直流近似 DC-OTS（见 dcots.py），让整条流程不依赖外部求解链也能跑通，输出真实的开断方案与机组调整。
- mock：不调用任何求解器，立即返回 status = "mock"。**不得生成任何看起来像求解结果的开断方案或出力曲线**：
  结果里没有 branch_status / gen_p / bus_vm / branch_flow，只有状态、说明和空耗时。
- import：用户上传结果 JSON，按 result_schema.json 校验 + 业务校验（对象存在、数组长度 = periods）后作为该版本的结果。
- external：执行 SOLVER_CMD（占位符 {spec} {dir} {out}），带超时，读取输出 JSON，日志实时推到前端。
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import jsonschema

from ..config import app_config, settings
from ..data.library import Window, get_snapshot
from ..storage import db

SCHEMA_PATH = Path(__file__).with_name("result_schema.json")
MODES = ("builtin", "mock", "import", "external")
MODE_LABEL = {"builtin": "内置求解器（HiGHS · 直流近似 OTS）", "mock": "mock（占位，不调用求解器）", "import": "导入结果", "external": "外部命令（接现有求解链）"}


def result_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


class ResultError(ValueError):
    """结果 JSON 不合法。"""


def validate_result(res: Any, window: Window | None = None) -> dict:
    """schema 校验 + 业务校验。返回规整后的结果；不合法抛 ResultError（带可读说明）。"""
    if not isinstance(res, dict):
        raise ResultError("结果必须是 JSON 对象")
    v = jsonschema.Draft202012Validator(result_schema())
    errs = sorted(v.iter_errors(res), key=lambda e: list(e.path))
    if errs:
        e = errs[0]
        where = "/".join(str(p) for p in e.path) or "根"
        raise ResultError(f"结果不符合 result_schema.json：{where}：{e.message[:200]}" + (f"（另有 {len(errs) - 1} 处）" if len(errs) > 1 else ""))
    n = int(res["periods"])
    if window is not None and n != window.periods:
        raise ResultError(f"结果的 periods = {n}，与本任务的 {window.periods} 时段不一致")
    if res["status"] == "mock" and any(res.get(k) for k in ("branch_status", "gen_p", "bus_vm", "branch_flow")):
        raise ResultError("status = mock 的结果不能带开断方案或曲线（mock 不得伪造求解结果）")
    snap = get_snapshot(window.snapshot_ids[0])[0] if window is not None else None
    def check_arr(kind: str, key: str, arr: list) -> None:
        if len(arr) != n:
            raise ResultError(f"{kind} {key} 的数组长度为 {len(arr)}，应等于 periods = {n}")
    for kind in ("branch_status", "gen_p", "bus_vm"):
        for key, arr in (res.get(kind) or {}).items():
            check_arr(kind, key, arr)
            if snap is not None and not snap.object_exists(key):
                raise ResultError(f"{kind} 里的对象 {key} 在数据中不存在")
    for key, d in (res.get("branch_flow") or {}).items():
        if snap is not None and not snap.object_exists(key):
            raise ResultError(f"branch_flow 里的对象 {key} 在数据中不存在")
        for f in ("pf", "qf", "pt", "qt"):
            if f in d and d[f] and len(d[f]) != n:
                raise ResultError(f"branch_flow {key}.{f} 的数组长度为 {len(d[f])}，应等于 periods = {n}")
    out = dict(res)
    out.setdefault("solver", "")
    out.setdefault("objective", None)
    out.setdefault("timings_s", {})
    out.setdefault("messages", [])
    return out


def mock_result(window: Window, solver: str = "mock") -> dict:
    """mock：占位，不含任何方案 / 曲线。"""
    return {
        "status": "mock", "solver": solver or "mock", "objective": None, "periods": window.periods,
        "timings_s": {"read": None, "build": None, "solve": None, "n1_check": None},
        "messages": ["黑盒占位：未调用求解器。结果页展示调整前断面；接入求解链后（SOLVER_MODE=external 或导入结果 JSON）才会有开断方案与出力曲线。"],
    }


# ------------------------------------------------------------------------------------------------
# 作业（后台线程 + 实时日志）
# ------------------------------------------------------------------------------------------------
@dataclass
class Job:
    id: str
    task_id: str
    version: int
    mode: str
    status: str = "running"           # running / done / failed / timeout
    lines: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    ended: float | None = None
    result: dict | None = None
    error: str | None = None
    proc: subprocess.Popen | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, msg: str) -> None:
        with self.lock:
            self.lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        db.log(self.task_id, f"[求解 {self.id}] {msg}", version=self.version)

    @property
    def elapsed(self) -> float:
        return (self.ended or time.time()) - self.started


JOBS: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def get_job(job_id: str) -> Job | None:
    return JOBS.get(job_id)


def _finish(job: Job, status: str, result: dict | None = None, error: str | None = None) -> None:
    job.status, job.result, job.error, job.ended = status, result, error, time.time()
    if result is not None:
        db.update_version(job.task_id, job.version, result_json=json.dumps(result, ensure_ascii=False),
                          metrics_json=None, risk_json=None)              # 结果变了：旧指标和风险作废
        db.write_artifact(job.task_id, job.version, "result.json", result)
    job.log(f"作业结束：{status}" + (f"（{error}）" if error else ""))


def start_solve(task_id: str, version: int, spec_path: Path, window: Window, mode: str, time_limit_s: int,
                on_done: Callable[[Job], None] | None = None) -> Job:
    """启动一次求解作业。mock 立即完成；external 在后台线程里跑命令。import 不走这里（直接 import_result）。"""
    job = Job(id=uuid.uuid4().hex[:8], task_id=task_id, version=version, mode=mode)
    with _jobs_lock:
        JOBS[job.id] = job
    job.log(f"启动求解作业：模式 {MODE_LABEL.get(mode, mode)}，时限 {time_limit_s} s（求解是黑盒：不做求解加速 / 调参 / 热启动）")
    if mode == "builtin":
        from .dcots import solve_spec
        from ..spec.schema import ModelSpec
        try:
            spec = ModelSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
            job.log("内置求解器：读取规格，按断面逐时段建立直流近似 OTS 混合整数模型")
            res = solve_spec(spec, window, time_limit_s)
            for m in res.get("messages", []):
                job.log(m)
            _finish(job, "done" if res["status"] in ("optimal", "feasible", "infeasible") else "failed", res if res["status"] != "error" else res,
                    None if res["status"] != "error" else "求解出错")
        except Exception as e:  # noqa: BLE001
            _finish(job, "failed", error=f"内置求解器异常：{type(e).__name__}: {e}")
        return job
    if mode == "mock":
        res = mock_result(window)
        job.log("mock：不调用任何求解器，立即返回 status = mock")
        _finish(job, "done", res)
        return job
    if mode == "external":
        cmd_t = settings.solver_cmd
        if not cmd_t:
            _finish(job, "failed", error="SOLVER_MODE=external 但没有配置 SOLVER_CMD（.env 里设，例：python solve.py --spec {spec} --snapshots {dir} --out {out}）")
            return job
        out_path = db.version_dir(task_id, version) / "solver_out.json"
        if out_path.exists():
            out_path.unlink()
        cmd = cmd_t.format(spec=str(spec_path), dir=str(settings.snapshot_dir), out=str(out_path))
        job.log(f"执行：{cmd}")
        margin = int(app_config()["solver"]["external_margin_s"])
        t = threading.Thread(target=_run_external, args=(job, cmd, out_path, window, time_limit_s + margin), daemon=True)
        t.start()
        return job
    _finish(job, "failed", error=f"模式 {mode} 不支持直接求解")
    return job


def _run_external(job: Job, cmd: str, out_path: Path, window: Window, timeout_s: int) -> None:
    try:
        args = shlex.split(cmd, posix=(sys.platform != "win32"))
        if sys.platform == "win32":      # 非 posix 模式保留引号，路径里的反斜杠不被当转义；这里去掉成对引号
            args = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a for a in args]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                cwd=str(settings.runs_dir), bufsize=1)
    except (OSError, ValueError) as e:
        _finish(job, "failed", error=f"无法启动命令：{e}")
        return
    job.proc = proc
    timed_out = threading.Event()

    def killer():
        if not timed_out.wait(timeout_s) and proc.poll() is None:
            pass

    def watchdog():
        end = time.time() + timeout_s
        while proc.poll() is None:
            if time.time() > end:
                timed_out.set()
                proc.kill()
                return
            time.sleep(0.2)

    threading.Thread(target=watchdog, daemon=True).start()
    assert proc.stdout is not None
    for line in proc.stdout:
        job.log(line.rstrip())
    rc = proc.wait()
    if timed_out.is_set():
        _finish(job, "timeout", error=f"超过 {timeout_s} s，已终止外部命令")
        return
    if rc != 0:
        _finish(job, "failed", error=f"外部命令退出码 {rc}")
        return
    if not out_path.exists():
        _finish(job, "failed", error=f"外部命令正常退出，但没有生成输出文件 {out_path.name}")
        return
    try:
        res = validate_result(json.loads(out_path.read_text(encoding="utf-8")), window)
    except (ValueError, json.JSONDecodeError) as e:
        _finish(job, "failed", error=f"输出 JSON 不合法：{e}")
        return
    job.log(f"读取输出 JSON：status = {res['status']}")
    _finish(job, "done", res)


def import_result(task_id: str, version: int, raw: Any, window: Window) -> dict:
    """import 模式：校验通过后作为该版本的结果。"""
    res = validate_result(raw, window)
    db.update_version(task_id, version, result_json=json.dumps(res, ensure_ascii=False), metrics_json=None, risk_json=None)
    db.write_artifact(task_id, version, "result.json", res)
    db.log(task_id, f"导入结果：status = {res['status']}，求解器 {res.get('solver') or '—'}", version=version)
    return res

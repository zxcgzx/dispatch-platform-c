"""试构建：子进程里执行代码页的同一份代码（T = 1、跳过 B9），限时 60 秒，报告真实的变量数、0-1 变量数、约束数。

- 没装 Pyomo：跳过，状态 skipped（M4 第 4 层给警告）。
- custom_code 来自大模型：先做静态检查，含危险调用就不执行（子进程里执行，也只做了超时限制，不是完整沙箱，见 ASSUMPTIONS）。
- 只构建模型，不调用任何求解器。
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import app_config
from ..spec.schema import ModelSpec

BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("trial_worker.py")

_FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals", "getattr", "setattr", "delattr", "vars"}
_FORBIDDEN_MODULES = {"os", "sys", "subprocess", "shutil", "socket", "pathlib", "ctypes", "requests", "httpx", "urllib", "importlib", "builtins", "pickle", "multiprocessing"}


def pyomo_available() -> bool:
    return importlib.util.find_spec("pyomo") is not None


def syntax_check(code: str) -> str | None:
    """E401：ast.parse。返回错误说明或 None。"""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"第 {e.lineno} 行：{e.msg}"
    return None


def custom_code_risks(spec: ModelSpec) -> list[tuple[str, str]]:
    """custom_code 的静态检查：返回 [(算子 id, 问题)]。"""
    out: list[tuple[str, str]] = []
    for s in spec.structural:
        if not s.custom_code:
            continue
        try:
            tree = ast.parse(s.custom_code)
        except SyntaxError as e:
            out.append((s.id, f"custom_code 语法错误：第 {e.lineno} 行 {e.msg}"))
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
                bad = [n for n in names if n in _FORBIDDEN_MODULES]
                if bad:
                    out.append((s.id, f"custom_code 导入了不允许的模块：{', '.join(bad)}"))
            elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
                out.append((s.id, f"custom_code 使用了不允许的名称：{node.id}"))
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                out.append((s.id, f"custom_code 访问了双下划线属性：{node.attr}"))
    return out


def run_trial(code: str, spec: ModelSpec, snapshot_id: str) -> dict:
    """返回 {status: ok|error|skipped|timeout, ...}。"""
    cfg = app_config()["trial_build"]
    if not cfg.get("enabled", True):
        return {"status": "skipped", "reason": "试构建已在 config/app.yaml 中关闭"}
    if not pyomo_available():
        return {"status": "skipped", "reason": "没有安装 Pyomo（pip install pyomo），试构建已跳过"}
    risks = custom_code_risks(spec)
    if risks:
        return {"status": "error", "error": "；".join(f"{i}：{m}" for i, m in risks), "item_id": risks[0][0]}
    timeout = int(cfg.get("timeout_s", 60))
    with tempfile.TemporaryDirectory(prefix="wb_trial_") as td:
        td_p = Path(td)
        (td_p / "model.py").write_text(code, encoding="utf-8")
        (td_p / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
        out = td_p / "out.json"
        cmd = [sys.executable, str(WORKER), str(BACKEND_DIR), str(td_p / "model.py"), str(td_p / "spec.json"), str(out), snapshot_id]
        try:
            proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": f"试构建超过 {timeout} 秒，已终止"}
        if not out.exists():
            return {"status": "error", "error": "试构建进程异常退出：" + (proc.stderr or proc.stdout or "无输出")[-600:]}
        res = json.loads(out.read_text(encoding="utf-8"))
    if res.get("ok"):
        return {"status": "ok", **{k: res[k] for k in ("vars", "binary", "continuous", "constraints", "build_s", "data_s")}, "T": 1}
    return {"status": "error", "error": res.get("error", "未知错误"), "trace": res.get("trace", "")}

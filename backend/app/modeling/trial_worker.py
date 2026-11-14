"""试构建工作进程：在子进程里执行“代码页显示的那份代码”（model.py 文本，不做二次拼接），T = 1、跳过 B9。

用法（由 trial.py 调用，路径作为参数传入）：
    python trial_worker.py <backend_dir> <code.py> <spec.json> <out.json> <snapshot_id> [<snapshot_id> ...]
只构建模型，不调用任何求解器。
"""
import json
import sys
import time


def main() -> None:
    backend_dir, code_path, spec_path, out_path = sys.argv[1:5]
    snapshot_ids = sys.argv[5:]
    sys.path.insert(0, backend_dir)
    res = {"ok": False}
    try:
        from app.data.library import Window
        from app.modeling.rundata import build_data

        spec = json.load(open(spec_path, encoding="utf-8"))
        win = Window(None, 1, 15, snapshot_ids[:1], True, [])
        t0 = time.perf_counter()
        data = build_data(win, T=1)
        t_data = time.perf_counter() - t0

        code = open(code_path, encoding="utf-8").read()
        ns: dict = {"__name__": "generated_model"}
        exec(compile(code, code_path, "exec"), ns)  # noqa: S102  与代码页显示的是同一份文本
        t1 = time.perf_counter()
        spec = dict(spec)
        spec["omega"] = dict(spec["omega"], periods=1)
        m = ns["build_model"](data, spec, with_n1=False)
        t_build = time.perf_counter() - t1

        import pyomo.environ as pyo

        nvars = sum(1 for _ in m.component_data_objects(pyo.Var, active=True))
        nbin = sum(1 for v in m.component_data_objects(pyo.Var, active=True) if v.is_binary())
        ncons = sum(1 for _ in m.component_data_objects(pyo.Constraint, active=True))
        res = {"ok": True, "vars": nvars, "binary": nbin, "continuous": nvars - nbin, "constraints": ncons,
               "build_s": round(t_build, 3), "data_s": round(t_data, 3)}
    except Exception as e:  # noqa: BLE001
        import traceback

        res = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()

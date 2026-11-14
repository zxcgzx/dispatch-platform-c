"""把 MATLAB v1.3（16 时段完整交流 OTS 基准）的结果转成平台能读的小 JSON。
用法：python scripts/import_matlab_benchmark.py "<dali_matlab_v1.3 目录>"
输出：backend/app/data/benchmarks/ots905_v1.3.json（只放摘要与逐时段指标，不拷贝 121 MB 原始文件）
依赖：numpy、scipy
"""
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio

src = Path(sys.argv[1])
out = Path(__file__).resolve().parents[1] / "backend/app/data/benchmarks/ots905_v1.3.json"
e1 = src / "speed_E1_chain"


def rows(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        return float(x)
    except ValueError:
        return x


periods = [{k: num(v) for k, v in r.items()} for r in rows(e1 / "MPAC_periods.csv")]
stage = [{k: num(v) for k, v in r.items()} for r in rows(e1 / "MPAC_stage_costs.csv")]
m = sio.loadmat(e1 / "MPAC_solutions.mat")
VM, PG, cand, path = m["VM"], m["PG"], m["cand"].ravel().astype(int), m["path"].ravel().astype(int)
T = VM.shape[0]
per = []
for t in range(T):
    k = path[t] - 1          # path 是 15 种拓扑（含“不开断”）里的序号，取解用它；断开的支路以 periods.csv 的 open_row 为准
    vm, pg = VM[t, k], PG[t, k]
    per.append({"t": t + 1, "vm_min": round(float(vm.min()), 4), "vm_max": round(float(vm.max()), 4),
                "pg_total_MW": round(float(pg.sum()), 1)})
for p, q in zip(periods, per):
    p.update({k: v for k, v in q.items() if k not in ("t", "open_row")})

speed = []
txt = (src / "speed_tests_summary.md").read_text(encoding="utf-8")
for line in txt.splitlines():
    c = [x.strip() for x in line.strip("|").split("|")]
    if len(c) >= 12 and c[0].startswith("E") and c[0][1].isdigit():
        speed.append({"name": c[0], "init": c[1], "usable": c[2], "total_s": float(c[3]), "opf_s": float(c[4]), "iters": float(c[5]),
                      "n1_count": int(c[6]), "n1_s": float(c[7]), "obj_4h": float(c[10]), "obj_noopen_4h": float(c[11])})

report = (e1 / "MPAC_report.md").read_text(encoding="utf-8")
doc = {
    "id": "ots905_v1.3", "title": "905 节点 · 16 时段完整交流 OTS 基准（MATLAB + MATPOWER 8 MIPS）",
    "source": "dali_matlab_v1.3 / speed_E1_chain（热启动：时段链）", "periods_n": T, "step_min": 15,
    "case": {"buses": int(VM.shape[2]), "gens": int(PG.shape[2]), "candidates": [f"L{c}" for c in cand]},
    "branch_status": {f"L{r}": [0 if int(p["open_row"]) == r else 1 for p in periods] for r in sorted({int(p["open_row"]) for p in periods if p["open_row"]})},
    "opened": [f"L{r}" for r in sorted({int(p["open_row"]) for p in periods if p["open_row"]})],
    "periods": periods, "stage_costs": stage, "speed": speed,
    "summary": {"obj_4h": speed[1]["obj_4h"] if len(speed) > 1 else None, "obj_noopen_4h": speed[1]["obj_noopen_4h"] if len(speed) > 1 else None,
                "total_s": speed[1]["total_s"] if len(speed) > 1 else None, "ac_opf_runs": 240, "n1_runs": 16},
    "report_md": report,
}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
print(out, out.stat().st_size // 1024, "KB; speed rows", len(speed), "opened", doc["opened"])

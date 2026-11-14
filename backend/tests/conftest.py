import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# 测试用独立的运行目录与数据库，不污染 runs/
_tmp = tempfile.mkdtemp(prefix="wb_test_")
os.environ["RUNS_DIR"] = _tmp
os.environ["WORKBENCH_DB"] = str(Path(_tmp) / "test.sqlite")
os.environ["LLM_MODE"] = "demo"
os.environ["SOLVER_MODE"] = "builtin"
os.environ["METHOD_ENDPOINT"] = ""
os.environ["RISK_ENDPOINT"] = ""


@pytest.fixture(scope="session")
def snap_topo():
    from app.data.library import default_snapshot_id, get_snapshot

    sid = default_snapshot_id()
    assert sid, "data/snapshots 下没有断面文件"
    return get_snapshot(sid)


@pytest.fixture(scope="session")
def snap(snap_topo):
    return snap_topo[0]


@pytest.fixture(scope="session")
def topo(snap_topo):
    return snap_topo[1]


@pytest.fixture(scope="session")
def multi_dir(tmp_path_factory):
    """16 个断面（每个相隔 15 分钟，内容同源）：用来验证多时段滚动窗口。"""
    import re
    from datetime import datetime, timedelta

    src = (ROOT / "data" / "snapshots" / "pasExp_20261004_153500_1.txt").read_text(encoding="utf-8")
    d = tmp_path_factory.mktemp("snaps16")
    t0 = datetime(2026, 10, 15, 18, 15, 0)
    for k in range(16):
        t = (t0 + timedelta(minutes=15 * k)).strftime("%Y-%m-%d_%H-%M-%S")
        (d / f"pasExp_20261015_{181500 + k:06d}_{k + 1}.txt").write_text(re.sub(r"time = .*", f"time = {t}", src, count=1), encoding="utf-8")
    return d


@pytest.fixture
def multi_env(multi_dir, monkeypatch):
    monkeypatch.setenv("SNAPSHOT_DIR", str(multi_dir))
    yield multi_dir

"""断面库：扫描 SNAPSHOT_DIR，按时刻排序。一个断面就是一个时段；断面够多时取 16 个间隔 15 分钟的最近断面做滚动窗口。只读，不修改任何断面文件。"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..config import app_config, settings
from .facts import compute_facts, compute_quality
from .snapshot import Snapshot, SnapshotFormatError, load_snapshot
from .topology import Topology

_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, Snapshot, Topology]] = {}


@dataclass
class Window:
    """一个任务选定的时段窗口：断面数 = 时段数（单断面即单时段，最多 16 个时段）。"""

    start: datetime | None
    periods: int
    step_min: int
    snapshot_ids: list[str]               # 每个时段所用断面 id（长度 = periods）
    single_snapshot: bool                 # 只有一个断面（单时段）
    notes: list[str]

    def period_time(self, t: int) -> datetime | None:
        """t 为 1..periods。"""
        if self.start is None:
            return None
        return self.start + timedelta(minutes=self.step_min * (t - 1))

    def period_label(self, t: int) -> str:
        d = self.period_time(t)
        return d.strftime("%H:%M") if d else f"第{t}时段"


def _scan() -> list[Path]:
    d = settings.snapshot_dir
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.txt") if re.search(r"pasExp_", p.name) or p.is_file())


def get_snapshot(snapshot_id: str) -> tuple[Snapshot, Topology]:
    """按 id（文件名去后缀）读断面，带缓存（按文件修改时间失效）。"""
    path = settings.snapshot_dir / f"{snapshot_id}.txt"
    if not path.exists():
        raise KeyError(f"断面不存在：{snapshot_id}")
    mtime = path.stat().st_mtime
    key = (str(settings.snapshot_dir), snapshot_id)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
        snap = load_snapshot(path)
        topo = Topology(snap)
        _cache[key] = (mtime, snap, topo)
        return snap, topo


def list_snapshots() -> list[dict]:
    out: list[dict] = []
    for p in _scan():
        try:
            snap, _ = get_snapshot(p.stem)
        except (SnapshotFormatError, ValueError, OSError) as e:
            out.append({"id": p.stem, "file": p.name, "error": str(e), "time": None})
            continue
        out.append({
            "id": snap.snapshot_id, "file": p.name,
            "time": snap.time.isoformat(timespec="seconds") if snap.time else None,
            "time_source": snap.time_source, "time_mismatch": snap.time_mismatch,
            "counts": {"bus": len(snap.bus), "gen": len(snap.gen), "branch": len(snap.branch)},
        })
    out.sort(key=lambda x: (x["time"] is None, x["time"] or "", x["id"]))
    return out


def snapshot_summary(snapshot_id: str) -> dict:
    snap, topo = get_snapshot(snapshot_id)
    return {
        "id": snapshot_id, "file": snap.path.name,
        "dict_info": snap.dict_info,
        "time_source": snap.time_source,
        "facts": compute_facts(snap, topo),
        "quality": compute_quality(snap, topo),
    }


def default_snapshot_id() -> str | None:
    lst = [s for s in list_snapshots() if not s.get("error")]
    return lst[0]["id"] if lst else None


def build_window(start: datetime | None = None, snapshot_id: str | None = None) -> Window:
    """选起始时刻组成时段窗口：断面库只有 1 个断面 → 1 个时段；断面不足 16 个 → 按时刻顺序全取；够 16 个 → 取 16 个间隔 15 分钟的最近断面。"""
    cfg = app_config()["time"]
    max_p, step = int(cfg["periods"]), int(cfg["step_min"])
    snaps = [s for s in list_snapshots() if not s.get("error")]
    if not snaps:
        raise KeyError("断面库为空：请把断面文件放入 data/snapshots/")
    if snapshot_id and not any(s["id"] == snapshot_id for s in snaps):
        raise KeyError(f"断面不存在：{snapshot_id}")
    timed = [(datetime.fromisoformat(s["time"]), s["id"]) for s in snaps if s["time"]]
    if len(snaps) == 1:
        s = snaps[0]
        t0 = start or (datetime.fromisoformat(s["time"]).replace(second=0, microsecond=0) if s["time"] else None)
        return Window(t0, 1, step, [s["id"]], True, [])
    if start is None:
        start = (datetime.fromisoformat(snapshots_time_of(snapshot_id, snaps)) if snapshot_id else timed[0][0]) if timed else None
    if len(snaps) < max_p or not timed:
        ordered = [x[1] for x in sorted(timed)] if timed else [s["id"] for s in snaps]
        i0 = 0
        if start and timed:
            i0 = min(range(len(ordered)), key=lambda i: abs((sorted(timed)[i][0] - start).total_seconds()))
        ids = ordered[i0:][:max_p]
        return Window(start, len(ids), step, ids, len(ids) == 1, [])
    ids: list[str] = []
    for k in range(max_p):
        target = start + timedelta(minutes=step * k) if start else None
        best = min(timed, key=lambda x: abs((x[0] - target).total_seconds())) if target else timed[0]
        ids.append(best[1])
    return Window(start, max_p, step, ids, len(set(ids)) == 1 and len(ids) == 1, [])


def snapshots_time_of(snapshot_id: str, snaps: list[dict]) -> str:
    for s in snaps:
        if s["id"] == snapshot_id and s["time"]:
            return s["time"]
    return snaps[0]["time"]

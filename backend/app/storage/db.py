"""SQLite（SQLModel）存任务与版本；产物（spec.json / model.tex / model.py / check.json / result.json / metrics.json / log.txt）
落在 runs/{task}/v{n}/。运行目录与数据库路径由 RUNS_DIR / WORKBENCH_DB 覆盖（测试用）。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text as sql_text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from ..config import settings


class Task(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: str
    instruction: str
    snapshot_id: str
    start: str | None = None
    engine: str = "demo"
    ask_enabled: bool = True
    max_rounds: int = 3
    parse_json: str | None = None            # ParseResult（实体、挂起项、追问、回答记录）
    draft_json: str | None = None            # 草稿的 ω、R、层级改选、parent_version、change_reason
    feedback_mode: str = "negotiate"
    testrun: bool = False                    # 测评模式批量跑出来的任务，不进任务列表


class Version(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True)
    version: int
    parent_version: int | None = None
    change_reason: str | None = None
    created_at: str = ""
    level: str = ""
    spec_json: str = ""
    check_json: str | None = None
    result_json: str | None = None
    metrics_json: str | None = None
    risk_json: str | None = None


_lock = threading.RLock()
_engines: dict[str, Any] = {}


def _engine():
    path = str(settings.db_path)
    with _lock:
        if path not in _engines:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
            SQLModel.metadata.create_all(eng)
            _engines[path] = eng
        return _engines[path]


def session() -> Session:
    return Session(_engine())


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- 目录与日志
def task_dir(task_id: str) -> Path:
    d = settings.runs_dir / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def version_dir(task_id: str, v: int) -> Path:
    d = task_dir(task_id) / f"v{v}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log(task_id: str, msg: str, version: int | None = None) -> None:
    """任务日志（运行日志抽屉）；version 给定时同时写入该版本的 log.txt。"""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"
    with _lock:
        with open(task_dir(task_id) / "log.txt", "a", encoding="utf-8") as f:
            f.write(line)
        if version is not None:
            with open(version_dir(task_id, version) / "log.txt", "a", encoding="utf-8") as f:
                f.write(line)


def read_log(task_id: str) -> str:
    p = settings.runs_dir / task_id / "log.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# --------------------------------------------------------------------------- 任务
def new_task_id(s: Session) -> str:
    n = len(s.exec(select(Task.id)).all()) + 1
    while s.get(Task, f"T{n:04d}"):
        n += 1
    return f"T{n:04d}"


def create_task(**kw: Any) -> Task:
    with _lock, session() as s:
        t = Task(id=new_task_id(s), created_at=now(), **kw)
        s.add(t)
        s.commit()
        s.refresh(t)
        return t


def get_task(task_id: str) -> Task | None:
    with session() as s:
        return s.get(Task, task_id)


def save_task(t: Task) -> None:
    with _lock, session() as s:
        s.merge(t)
        s.commit()


def list_tasks(include_test: bool = False) -> list[Task]:
    with session() as s:
        q = select(Task).order_by(Task.created_at.desc(), Task.id.desc())
        rows = s.exec(q).all()
    return [t for t in rows if include_test or not t.testrun]


# --------------------------------------------------------------------------- 版本
def list_versions(task_id: str) -> list[Version]:
    with session() as s:
        return list(s.exec(select(Version).where(Version.task_id == task_id).order_by(Version.version)).all())


def get_version(task_id: str, v: int) -> Version | None:
    with session() as s:
        return s.exec(select(Version).where(Version.task_id == task_id, Version.version == v)).first()


def latest_version(task_id: str) -> Version | None:
    vs = list_versions(task_id)
    return vs[-1] if vs else None


def add_version(**kw: Any) -> Version:
    with _lock, session() as s:
        v = Version(created_at=now(), **kw)
        s.add(v)
        s.commit()
        s.refresh(v)
        return v


def update_version(task_id: str, v: int, **fields: Any) -> Version:
    with _lock, session() as s:
        row = s.exec(select(Version).where(Version.task_id == task_id, Version.version == v)).first()
        if row is None:
            raise KeyError(f"版本不存在：{task_id} v{v}")
        for k, val in fields.items():
            setattr(row, k, val)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def write_artifact(task_id: str, v: int, name: str, content: str | dict | list) -> Path:
    p = version_dir(task_id, v) / name
    p.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def read_artifact(task_id: str, v: int, name: str) -> str | None:
    p = settings.runs_dir / task_id / f"v{v}" / name
    return p.read_text(encoding="utf-8") if p.exists() else None

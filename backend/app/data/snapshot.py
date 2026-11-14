"""断面文件解析（只读）与对象编号。

文件是分段文本，不是 MATPOWER case：
  #####Begin Dict Info#####  key = value
  #####Begin Matrix Bus#####  首行表头，逗号分隔，#####End Matrix Bus##### 结束
对象编号全平台统一：母线 B{BUS_I}，支路 L{行号}，机组 G{行号}（行号从 1 开始）。
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

BUS_COLS = ["BUS_I", "BUS_TYPE", "PD", "QD", "GS", "BS", "BUS_AREA", "VM", "VA", "BASE_KV", "ZONE", "VMAX", "VMIN", "RENEWABLE"]
GEN_COLS = ["GEN_BUS", "PG", "QG", "QMAX", "QMIN", "VG", "MBASE", "GEN_STATUS", "PMAX", "PMIN"]
BRANCH_COLS = ["F_BUS", "T_BUS", "BR_R", "BR_X", "BR_B", "RATE_A", "RATE_B", "RATE_C", "TAP", "SHIFT", "BR_STATUS",
               "ANGMIN", "ANGMAX", "PF", "QF", "PT", "QT"]

FILENAME_RE = re.compile(r"pasExp_(\d{8})_(\d{6})_(\d+)")


class SnapshotFormatError(ValueError):
    """断面文件格式错误（缺段、缺列等），对应校验 E301。"""


def bus_id(bus_i: int) -> str:
    return f"B{int(bus_i)}"


def branch_id(row: int) -> str:
    return f"L{int(row)}"


def gen_id(row: int) -> str:
    return f"G{int(row)}"


def parse_id(obj_id: str) -> tuple[str, int] | None:
    """'B43' -> ('bus', 43)；'L155' -> ('branch', 155)；'G237' -> ('gen', 237)；非法返回 None。"""
    m = re.fullmatch(r"([BLG])(\d+)", obj_id.strip())
    if not m:
        return None
    return {"B": "bus", "L": "branch", "G": "gen"}[m.group(1)], int(m.group(2))


@dataclass
class Snapshot:
    """一个断面。DataFrame 的行序即文件行序（Branch/Gen 行号 = 下标 + 1），不排序、不修改。"""

    path: Path
    snapshot_id: str
    dict_info: dict[str, str]
    bus: pd.DataFrame
    gen: pd.DataFrame
    branch: pd.DataFrame
    time: datetime | None                 # 断面时刻（优先 Dict Info，其次文件名）
    time_source: str                      # "dict" | "filename" | "none"
    file_time: datetime | None            # 文件名里的时间戳
    dict_time: datetime | None
    time_mismatch: bool
    base_mva: float
    format_issues: list[str] = field(default_factory=list)

    # ---- 编号工具 ----
    @property
    def bus_ids(self) -> list[str]:
        return [bus_id(b) for b in self.bus["BUS_I"]]

    @property
    def branch_ids(self) -> list[str]:
        return [branch_id(i + 1) for i in range(len(self.branch))]

    @property
    def gen_ids(self) -> list[str]:
        return [gen_id(i + 1) for i in range(len(self.gen))]

    def bus_index(self) -> dict[int, int]:
        """BUS_I -> 行下标。"""
        return {int(b): i for i, b in enumerate(self.bus["BUS_I"])}

    def has_object(self, component: str, key: int) -> bool:
        if component == "bus":
            return key in self.bus_index()
        if component == "branch":
            return 1 <= key <= len(self.branch)
        if component == "gen":
            return 1 <= key <= len(self.gen)
        return False

    def object_exists(self, obj_id: str) -> bool:
        p = parse_id(obj_id)
        return bool(p) and self.has_object(p[0], p[1])

    def known_ids(self) -> set[str]:
        return set(self.bus_ids) | set(self.branch_ids) | set(self.gen_ids)

    def bus_kv(self) -> dict[int, float]:
        return {int(b): float(k) for b, k in zip(self.bus["BUS_I"], self.bus["BASE_KV"])}

    def rate_mva(self):
        """支路热稳限额，MVA。断面里的 RATE_A 是额定电流（A），按首端电压折算：S = √3·kV·I / 1000；0 表示不限。"""
        import numpy as np

        kv = self.bus_kv()
        f = np.array([kv.get(int(b), 0.0) for b in self.branch["F_BUS"]])
        return self.branch["RATE_A"].to_numpy(dtype=float) * np.sqrt(3.0) * f / 1000.0

    def branch_label(self, row: int) -> str:
        """显示名，如 L155（174–172，220kV）。"""
        r = self.branch.iloc[row - 1]
        kvm = self.bus_kv()
        kv = max(kvm.get(int(r.F_BUS), 0.0), kvm.get(int(r.T_BUS), 0.0))
        return f"L{row}（{int(r.F_BUS)}–{int(r.T_BUS)}，{kv:g}kV）"


def _split_sections(lines: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    info: dict[str, str] = {}
    mats: dict[str, list[str]] = {}
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s == "#####Begin Dict Info#####":
            i += 1
            while i < n and lines[i].strip() != "#####End Dict Info#####":
                if "=" in lines[i]:
                    k, v = lines[i].split("=", 1)
                    info[k.strip()] = v.strip()
                i += 1
        else:
            m = re.fullmatch(r"#####Begin Matrix (\w+)#####", s)
            if m:
                name = m.group(1)
                i += 1
                body: list[str] = []
                while i < n and lines[i].strip() != f"#####End Matrix {name}#####":
                    if lines[i].strip():
                        body.append(lines[i])
                    i += 1
                mats[name] = body
        i += 1
    return info, mats


def _to_frame(name: str, body: list[str], required: list[str]) -> pd.DataFrame:
    if not body:
        raise SnapshotFormatError(f"缺少 Matrix {name} 段")
    df = pd.read_csv(io.StringIO("\n".join(body)))
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SnapshotFormatError(f"Matrix {name} 缺少列：{', '.join(missing)}")
    return df


def _parse_dict_time(v: str | None) -> datetime | None:
    if not v:
        return None
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(v.strip(), fmt)
        except ValueError:
            pass
    return None


def filename_time(path: Path) -> datetime | None:
    m = FILENAME_RE.search(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def load_snapshot(path: str | Path) -> Snapshot:
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    info, mats = _split_sections(lines)
    bus = _to_frame("Bus", mats.get("Bus", []), BUS_COLS)
    gen = _to_frame("Gen", mats.get("Gen", []), GEN_COLS)
    branch = _to_frame("Branch", mats.get("Branch", []), BRANCH_COLS)
    for c in ("BUS_I", "BUS_TYPE", "BUS_AREA", "ZONE"):
        bus[c] = bus[c].astype(int)
    gen["GEN_BUS"] = gen["GEN_BUS"].astype(int)
    branch["F_BUS"] = branch["F_BUS"].astype(int)
    branch["T_BUS"] = branch["T_BUS"].astype(int)

    dict_time = _parse_dict_time(info.get("time"))
    file_time = filename_time(path)
    if dict_time is not None:
        t, src = dict_time, "dict"
    elif file_time is not None:
        t, src = file_time, "filename"
    else:
        t, src = None, "none"
    mismatch = bool(dict_time and file_time and dict_time != file_time)
    try:
        base_mva = float(info.get("baseMVA", 100.0))
    except ValueError:
        base_mva = 100.0
    return Snapshot(
        path=path, snapshot_id=path.stem, dict_info=info, bus=bus, gen=gen, branch=branch,
        time=t, time_source=src, file_time=file_time, dict_time=dict_time, time_mismatch=mismatch,
        base_mva=base_mva,
    )

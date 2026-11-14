"""追问回答的解析：幅度（缩放系数 / 百分比 / 目标值）和时段。"""
from __future__ import annotations

import re

from .extract import DASH, clock_to_periods

_DOWN = ("降低", "下降", "下调", "减少", "减小", "调低", "降")
_UP = ("提高", "增加", "增大", "上调", "上升", "提升", "调高", "升高", "增长")
_TO = ("到", "至", "按", "取", "为", "设")
_UNIT_ABS = re.compile(r"(\d+(?:\.\d+)?)\s*(MVA|Mvar|MW|kW|兆瓦|万千瓦|p\.?u\.?)", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")
_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def to_mw(num: float, unit: str) -> float:
    u = unit.lower()
    if u == "万千瓦":
        return num * 10.0
    if u == "kw":
        return num / 1000.0
    return num


def parse_magnitude(text: str, direction: str | None) -> tuple[str, float]:
    """把用户输入的幅度解析成 (operation, value)。

    - “降低 20%” / “提高 10%” / “20%”（按 direction 的方向）→ scale 0.8 / 1.1
    - “降到 80%” / “按 80%” → scale 0.8
    - “0.8”（0 < x ≤ 3）→ scale 0.8；“800”（> 3）→ set 800
    - “800 MW” → set 800
    """
    s = (text or "").strip()
    if not s:
        raise ValueError("请输入幅度")
    has_down = any(w in s for w in _DOWN)
    has_up = any(w in s for w in _UP)
    has_to = any(w in s for w in _TO)

    m = _UNIT_ABS.search(s)
    if m:
        if (has_down or has_up) and not has_to:
            raise ValueError("请直接写目标值（如 800 MW）或百分比（如 降低 20%），不接受“增减若干 MW”")
        return "set", to_mw(float(m.group(1)), m.group(2))
    m = _PCT.search(s)
    if m:
        x = float(m.group(1))
        if has_to and not (has_down or has_up) or ("到" in s or "至" in s or "按" in s or "取" in s):
            return "scale", x / 100.0
        if has_down:
            return "scale", 1.0 - x / 100.0
        if has_up:
            return "scale", 1.0 + x / 100.0
        if direction == "decrease":
            return "scale", 1.0 - x / 100.0
        if direction == "increase":
            return "scale", 1.0 + x / 100.0
        raise ValueError("请说明是增加还是降低（如 降低 20%）")
    m = _NUM.search(s)
    if m:
        x = float(m.group(1))
        return ("scale", x) if 0 < x <= 3 else ("set", x)
    raise ValueError("无法理解幅度，可写：降低 20% / 0.8 / 800 MW")


def parse_periods_answer(answer: str, window, n: int) -> list[int]:
    """追问“对应哪些时段”的回答 → 时段列表（空列表 = 全部时段）。支持 all、1,2,3、5-12、HH:MM-HH:MM、中文说法。"""
    s = (answer or "").strip()
    if not s:
        raise ValueError("请选择时段")
    if s.lower() in ("all", "__all__") or any(w in s for w in ("全部", "全天", "所有", "每个时段")):
        return []
    out: set[int] = set()
    for tok in re.split(r"[,，、;；\s]+", s):
        if not tok:
            continue
        tok = tok.replace("第", "").replace("时段", "").replace("个", "")
        mc = re.fullmatch(r"(\d{1,2})[:：](\d{2})\s*" + DASH + r"\s*(\d{1,2})[:：](\d{2})", tok)
        if mc:
            ps = clock_to_periods(window, int(mc.group(1)), int(mc.group(2)), int(mc.group(3)), int(mc.group(4)), n)
            if ps is None:
                raise ValueError(f"钟点范围 {tok} 超出 {n} 个时段的窗口")
            out.update(ps)
            continue
        mr = re.fullmatch(r"(\d+)\s*" + DASH + r"\s*(\d+)", tok)
        if mr:
            a, b = int(mr.group(1)), int(mr.group(2))
            if a > b:
                raise ValueError(f"时段范围 {tok} 起止颠倒")
            out.update(range(a, b + 1))
            continue
        if tok.isdigit():
            out.add(int(tok))
            continue
        raise ValueError(f"无法理解时段“{tok}”，可写：5-12 / 5,6,7 / 全部时段")
    bad = sorted(p for p in out if not 1 <= p <= n)
    if bad:
        raise ValueError(f"时段超出 1–{n}：{bad}")
    return sorted(out)

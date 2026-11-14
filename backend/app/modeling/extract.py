"""与引擎无关的实体与要求抽取：演示规则引擎用它解析指令；第 5 层校验用它独立检查“遗漏”和电压等级。

只做确定性正则 + 知识表匹配，不依赖任何大模型。找不到对象时不替换成别的编号：
  not_found = 编号在数据里不存在（保留原文编号，交给 M4 报 E101）
  ambiguous = 并联多条 / 多台机组（交给追问）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import knowledge
from ..data.snapshot import Snapshot, branch_id, bus_id, gen_id
from ..data.topology import Topology
from .state import Entity

DASH = r"[-–—−~～至到]"
SENT_SPLIT = re.compile(r"[。；;\n]")
CLAUSE_SPLIT = re.compile(r"[，,]")

RE_GEN_BY_BUS = re.compile(r"母线\s*B?(\d+)\s*(?:上|处|侧)?\s*的?\s*(?:机组|发电机|电厂)")
RE_BR_ID = re.compile(r"(?<![A-Za-z0-9])L(\d+)(?![0-9])(?:\s*[（(]\s*(\d+)\s*" + DASH + r"\s*(\d+)\s*[)）])?")
RE_BR_ENDS = re.compile(r"(?:支路|线路)\s*(\d+)\s*" + DASH + r"\s*(\d+)")
RE_GEN_ID = re.compile(r"(?<![A-Za-z0-9])G(\d+)(?![0-9])")
RE_GEN_NUM = re.compile(r"机组\s*(\d+)(?![0-9])")
RE_BUS = re.compile(r"(?:母线\s*B?(\d+))|(?<![A-Za-z0-9])B(\d+)(?![0-9])")
RE_KV = re.compile(r"(\d+(?:\.\d+)?)\s*[kK][vV]")

RE_P_RANGE = re.compile(r"第\s*(\d+)\s*" + DASH + r"\s*(\d+)\s*(?:个)?时段|(?<![\d:：])(\d+)\s*(?:到|至)\s*(\d+)\s*(?:个)?时段")
RE_P_LIST = re.compile(r"第\s*(\d+(?:\s*、\s*\d+)+)\s*(?:个)?时段")
RE_P_ONE = re.compile(r"第\s*(\d+)\s*(?:个)?时段")
RE_P_CLOCK = re.compile(r"(\d{1,2})[:：](\d{2})\s*" + DASH + r"\s*(\d{1,2})[:：](\d{2})")

RE_N1 = re.compile(r"N\s*[-−–—]\s*1")


def _fuzzy_re() -> re.Pattern:
    words = sorted(knowledge()["fuzzy_time_words"], key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in words))


def _all_re() -> re.Pattern:
    words = sorted(knowledge()["all_period_words"], key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in words))


@dataclass
class Span:
    start: int
    end: int

    def overlaps(self, o: "Span") -> bool:
        return self.start < o.end and o.start < self.end


def _free(spans: list[Span], s: int, e: int) -> bool:
    return not any(sp.overlaps(Span(s, e)) for sp in spans)


def split_sentences(text: str) -> list[tuple[int, int]]:
    out, pos = [], 0
    for m in SENT_SPLIT.finditer(text):
        if text[pos:m.start()].strip():
            out.append((pos, m.start()))
        pos = m.end()
    if text[pos:].strip():
        out.append((pos, len(text)))
    return out


def split_clauses(text: str) -> list[tuple[int, int]]:
    """按 。；，分句，返回 (start, end)（去掉首尾空白后的位置）。"""
    out, pos = [], 0
    for m in re.finditer(r"[。；;，,\n]", text):
        out.append((pos, m.start()))
        pos = m.end()
    out.append((pos, len(text)))
    res = []
    for s, e in out:
        seg = text[s:e]
        ls = len(seg) - len(seg.lstrip())
        rs = len(seg) - len(seg.rstrip())
        if seg.strip():
            res.append((s + ls, e - rs))
    return res


# --------------------------------------------------------------------------------------
# 对象
# --------------------------------------------------------------------------------------
def extract_objects(text: str, snap: Snapshot, topo: Topology) -> list[Entity]:
    claimed: list[Span] = []
    ents: list[Entity] = []
    counter = [0]

    def new(type_: str, m_start: int, m_end: int, **kw) -> Entity:
        counter[0] += 1
        e = Entity(id=f"e-{counter[0]}", type=type_, text=text[m_start:m_end], start=m_start, end=m_end, **kw)  # type: ignore[arg-type]
        ents.append(e)
        claimed.append(Span(m_start, m_end))
        return e

    gen_bus: dict[int, list[int]] = {}
    for i, b in enumerate(snap.gen["GEN_BUS"], start=1):
        gen_bus.setdefault(int(b), []).append(i)

    # 1. 母线 N 上的机组
    for m in RE_GEN_BY_BUS.finditer(text):
        b = int(m.group(1))
        rows = gen_bus.get(b, [])
        if not snap.has_object("bus", b):
            new("gen", m.start(), m.end(), status="not_found", note=f"母线 B{b} 不存在", object_id=None)
        elif not rows:
            new("gen", m.start(), m.end(), status="not_found", note=f"母线 B{b} 上没有机组")
        elif len(rows) == 1:
            new("gen", m.start(), m.end(), object_id=gen_id(rows[0]), status="found", note=f"母线 B{b} 上只有一台机组")
        else:
            new("gen", m.start(), m.end(), status="ambiguous", candidates=[gen_id(r) for r in rows],
                note=f"母线 B{b} 上有 {len(rows)} 台机组")

    # 2. 支路 L 编号（可带（首–末））
    for m in RE_BR_ID.finditer(text):
        s = m.start()
        # 吃掉前面的“支路 / 线路”二字
        pre = re.search(r"(?:支路|线路)\s*$", text[:s])
        s0 = pre.start() if pre else s
        if not _free(claimed, s0, m.end()):
            continue
        row = int(m.group(1))
        if not snap.has_object("branch", row):
            new("branch", s0, m.end(), object_id=branch_id(row), status="not_found", note=f"支路 L{row} 不存在（共 {len(snap.branch)} 条）")
            continue
        note = None
        if m.group(2):
            r = snap.branch.iloc[row - 1]
            a, b = int(m.group(2)), int(m.group(3))
            if {a, b} != {int(r.F_BUS), int(r.T_BUS)}:
                note = f"指令写的端点 {a}–{b} 与 L{row} 实际端点 {int(r.F_BUS)}–{int(r.T_BUS)} 不一致"
        e = new("branch", s0, m.end(), object_id=branch_id(row), status="found", note=note)
        if note:
            e.role = "endpoint_mismatch"

    # 3. 线路 首–末
    for m in RE_BR_ENDS.finditer(text):
        if not _free(claimed, m.start(), m.end()):
            continue
        a, b = int(m.group(1)), int(m.group(2))
        br = snap.branch
        rows = [i + 1 for i in range(len(br)) if {int(br.F_BUS.iloc[i]), int(br.T_BUS.iloc[i])} == {a, b}]
        if not rows:
            new("branch", m.start(), m.end(), status="not_found", note=f"没有端点为 {a}–{b} 的支路")
        elif len(rows) == 1:
            new("branch", m.start(), m.end(), object_id=branch_id(rows[0]), status="found")
        else:
            new("branch", m.start(), m.end(), status="ambiguous", candidates=[branch_id(r) for r in rows],
                note=f"{a}–{b} 之间有 {len(rows)} 条并联支路")

    # 4. 机组 G 编号 / 机组 N
    for rx in (RE_GEN_ID, RE_GEN_NUM):
        for m in rx.finditer(text):
            s0 = m.start()
            pre = re.search(r"机组\s*$", text[:s0])
            if pre and rx is RE_GEN_ID:
                s0 = pre.start()
            if not _free(claimed, s0, m.end()):
                continue
            row = int(m.group(1))
            if snap.has_object("gen", row):
                new("gen", s0, m.end(), object_id=gen_id(row), status="found")
            else:
                new("gen", s0, m.end(), object_id=gen_id(row), status="not_found", note=f"机组 G{row} 不存在（共 {len(snap.gen)} 台）")

    # 5. 母线
    for m in RE_BUS.finditer(text):
        if not _free(claimed, m.start(), m.end()):
            continue
        n = int(m.group(1) or m.group(2))
        if snap.has_object("bus", n):
            new("bus", m.start(), m.end(), object_id=bus_id(n), status="found")
        else:
            new("bus", m.start(), m.end(), object_id=bus_id(n), status="not_found", note=f"母线 B{n} 不存在（BUS_I 范围 {int(snap.bus.BUS_I.min())}–{int(snap.bus.BUS_I.max())}，共 {len(snap.bus)} 个）")

    ents.sort(key=lambda e: e.start)
    for i, e in enumerate(ents, start=1):
        e.id = f"e-{i}"
    return ents


def extract_kv_mentions(text: str, objects: list[Entity]) -> list[Entity]:
    """电压等级提及；就近绑定到其后 10 个字符内的对象（如“220kV 线路 L155”）。"""
    out = []
    for i, m in enumerate(RE_KV.finditer(text), start=1):
        kv = float(m.group(1))
        near = next((o for o in objects if o.start >= m.end() and o.start - m.end() <= 10 and o.type in ("branch", "bus", "gen")), None)
        out.append(Entity(id=f"kv-{i}", type="kv", text=m.group(0), start=m.start(), end=m.end(), kv=kv, status="ok",
                          object_id=near.object_id if near else None,
                          candidates=list(near.candidates) if near and near.status == "ambiguous" else []))
    return out


def object_kv(snap: Snapshot, topo: Topology, obj_id: str) -> float | None:
    kvm = snap.bus_kv()
    t, n = obj_id[0], int(obj_id[1:])
    if t == "B":
        return kvm.get(n)
    if t == "L" and 1 <= n <= len(snap.branch):
        return float(topo.kv[n - 1])
    if t == "G" and 1 <= n <= len(snap.gen):
        return kvm.get(int(snap.gen.GEN_BUS.iloc[n - 1]))
    return None


# --------------------------------------------------------------------------------------
# 时段
# --------------------------------------------------------------------------------------
def extract_periods(text: str, window, n_periods: int, taken: list[Span] | None = None) -> list[Entity]:
    """时段表达。periods：明确时段（[] = 全部）；fuzzy：模糊说法，必须追问。"""
    taken = list(taken or [])
    out: list[Entity] = []
    cnt = [0]

    def add(m_start: int, m_end: int, **kw) -> Entity:
        cnt[0] += 1
        e = Entity(id=f"p-{cnt[0]}", type="period", text=text[m_start:m_end], start=m_start, end=m_end, **kw)
        out.append(e)
        taken.append(Span(m_start, m_end))
        return e

    for m in RE_P_RANGE.finditer(text):
        if not _free(taken, m.start(), m.end()):
            continue
        a = int(m.group(1) or m.group(3))
        b = int(m.group(2) or m.group(4))
        if a > b:
            add(m.start(), m.end(), status="fuzzy", periods=None, note=f"时段范围 {a}–{b} 起止颠倒，请确认")
        else:
            add(m.start(), m.end(), status="ok", periods=list(range(a, b + 1)))
    for m in RE_P_LIST.finditer(text):
        if not _free(taken, m.start(), m.end()):
            continue
        add(m.start(), m.end(), status="ok", periods=sorted({int(x) for x in re.findall(r"\d+", m.group(1))}))
    for m in RE_P_ONE.finditer(text):
        if not _free(taken, m.start(), m.end()):
            continue
        add(m.start(), m.end(), status="ok", periods=[int(m.group(1))])
    for m in RE_P_CLOCK.finditer(text):
        if not _free(taken, m.start(), m.end()):
            continue
        res = clock_to_periods(window, int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), n_periods)
        if res is None:
            add(m.start(), m.end(), status="fuzzy", periods=None,
                note="钟点范围超出 4 小时窗口或断面起始时刻未知，需要追问")
        else:
            add(m.start(), m.end(), status="ok", periods=res)
    for m in _all_re().finditer(text):
        if _free(taken, m.start(), m.end()):
            add(m.start(), m.end(), status="ok", periods=[])
    # 模糊说法：相邻合并（“明天午后”）
    fz = [(m.start(), m.end()) for m in _fuzzy_re().finditer(text) if _free(taken, m.start(), m.end())]
    merged: list[list[int]] = []
    for s, e in fz:
        if merged and s - merged[-1][1] <= 1:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    for s, e in merged:
        add(s, e, status="fuzzy", periods=None, note="模糊时间说法，需要追问具体时段")
    out.sort(key=lambda e: e.start)
    return out


def clock_to_periods(window, h1: int, m1: int, h2: int, m2: int, n: int) -> list[int] | None:
    """HH:MM–HH:MM → 时段列表；超出窗口返回 None。时段 k 的起点 = 起始时刻 + 15(k−1) 分钟。"""
    if window is None or window.start is None:
        return None
    day = window.start.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        t1 = day + timedelta(hours=h1, minutes=m1)
        t2 = day + timedelta(hours=h2, minutes=m2)
    except ValueError:
        return None
    if t1 < window.start - timedelta(seconds=59):
        t1 += timedelta(days=1)
    if t2 <= t1:
        t2 += timedelta(days=1)
    end = window.start + timedelta(minutes=window.step_min * n)
    if t1 < window.start - timedelta(seconds=59) or t2 > end + timedelta(seconds=59):
        return None
    ps = [k for k in range(1, n + 1)
          if t1 - timedelta(seconds=59) <= window.start + timedelta(minutes=window.step_min * (k - 1)) < t2]
    return ps or None


# --------------------------------------------------------------------------------------
# 关键词 / 要求
# --------------------------------------------------------------------------------------
def _find_all(text: str, words: list[str]) -> list[tuple[int, int, str]]:
    """最长优先、不重叠的关键词匹配。"""
    ws = sorted(set(words), key=len, reverse=True)
    spans: list[Span] = []
    out = []
    for w in ws:
        for m in re.finditer(re.escape(w), text):
            if _free(spans, m.start(), m.end()):
                spans.append(Span(m.start(), m.end()))
                out.append((m.start(), m.end(), w))
    out.sort()
    return out


def extract_keywords(text: str) -> list[Entity]:
    """推断、检修停运、N−1、结构类关键词。"""
    kb = knowledge()
    out: list[Entity] = []
    cnt = [0]

    def add(s: int, e: int, role: str, rule_id: str | None, note: str | None = None) -> None:
        cnt[0] += 1
        out.append(Entity(id=f"k-{cnt[0]}", type="keyword", text=text[s:e], start=s, end=e, status="ok", role=role, rule_id=rule_id, note=note))

    for rule in kb["inference_rules"]:
        for s, e, _ in _find_all(text, rule["keywords"]):
            add(s, e, "inference", rule["id"])
    for s, e, _ in _find_all(text, kb["outage_keywords"]):
        add(s, e, "outage", "outage")
    neg = kb["n_minus_1"]["negative_words"]
    for m in RE_N1.finditer(text):
        before = text[max(0, m.start() - 6):m.start()]
        negated = any(w in before for w in neg)
        add(m.start(), m.end(), "n1", "n_minus_1_off" if negated else "n_minus_1_on")
    sr = kb["structural_rules"]
    for key in ("switching_penalty", "section_limit", "loss_min", "voltage_deviation", "fixed_topology"):
        for s, e, _ in _find_all(text, sr[key]["keywords"]):
            add(s, e, "structural", key)
    out.sort(key=lambda e: e.start)
    return out


def match_switching_limit(text: str) -> list[dict]:
    """“开关操作不超过 k 次”：默认每时段；前后说了全天 / 总共则为全部时段总数。"""
    kb = knowledge()["structural_rules"]["switching_limit"]
    pat = re.compile(kb["pattern"])
    out = []
    for m in pat.finditer(text):
        k = int(m.group(1))
        ls = max(0, m.start() - 8)
        window_txt = text[ls:m.end()]
        total_hit = next((w for w in kb["total_words"] if w in window_txt), None)
        per_re = re.search(r"(每个时段|每时段|各时段|每个时间段)", text[ls:m.end()])
        start = m.start()
        if total_hit:
            i = text.rfind(total_hit, ls, m.end())
            start = min(start, i)
        elif per_re:
            start = min(start, ls + per_re.start())
        out.append({"k": k, "total": bool(total_hit), "start": start, "end": m.end(), "text": text[start:m.end()]})
    return out

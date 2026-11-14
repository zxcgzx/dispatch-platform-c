"""演示规则引擎（离线，默认）：规则 + 知识表（config/knowledge.yaml），保证 D1–D10 与指令第 10 节一致。

原则：
- 找不到对象时绝不替换成别的编号：保留原文编号（交给 M4 报 E101），或转成追问。
- 数值只取原文里写明的；推断项的幅度不准猜。
- 每一项修改带 evidence：从指令原文逐字摘出的连续片段。
"""
from __future__ import annotations

import re
import time

from ..config import app_config, knowledge
from ..spec.schema import DeltaPi, StructuralOp
from . import dialog
from .extract import (
    Span, extract_keywords, extract_kv_mentions, extract_objects, extract_periods,
    match_switching_limit, match_uc_limit, split_clauses, split_sentences,
)
from .magnitude import to_mw
from .state import Entity, ParseContext, ParseResult, PendingIntent

UP = ["提高", "增加", "增大", "上调", "上升", "提升", "调高", "升高", "增长"]
DOWN = ["降低", "减少", "下降", "下调", "调低", "减小", "降"]
SET = ["设为", "设置为", "设定为", "调整为", "限制为", "限额为", "改为", "取"]
_VERBS = sorted(UP + DOWN + SET, key=len, reverse=True)
MAG_RE = re.compile(
    r"(?P<verb>" + "|".join(map(re.escape, _VERBS)) + r")\s*(?P<to>到|至|为|成)?\s*(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|％|MVA|Mvar|MW|kW|兆瓦|万千瓦|p\.?u\.?)?", re.I)
MW_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>MW|MVA|兆瓦|万千瓦|kW)", re.I)

# (对象类型, 参数, 说法)
_PHRASES: list[tuple[str, str, str]] = (
    [("bus", "QD", w) for w in ["无功负荷", "无功需求"]]
    + [("bus", "PD", w) for w in ["有功负荷", "有功需求", "负荷"]]
    + [("bus", "VMAX", w) for w in ["电压上限", "最高电压"]]
    + [("bus", "VMIN", w) for w in ["电压下限", "最低电压"]]
    + [("gen", "PMAX", w) for w in ["出力上限", "最大出力", "最大技术出力", "可用出力上限"]]
    + [("gen", "PMIN", w) for w in ["出力下限", "最小出力", "最小技术出力"]]
    + [("branch", "RATE_A", w) for w in ["热稳限额", "热稳能力", "热稳裕度", "传输限额", "输送限额", "输电限额", "传输容量", "输送容量", "载流量", "限额", "容量"]]
)
_PHRASES.sort(key=lambda x: -len(x[2]))


def _classify(m: re.Match) -> tuple[str, float] | None:
    verb, to, unit = m.group("verb"), m.group("to"), (m.group("unit") or "").lower()
    x = float(m.group("num"))
    pct = unit in ("%", "％")
    absu = unit in ("mw", "mvar", "mva", "kw", "兆瓦", "万千瓦")
    val = to_mw(x, m.group("unit") or "") if absu else x
    if verb in UP:
        if pct:
            return "scale", (x / 100.0 if to else 1.0 + x / 100.0)
        return (("set" if to else "add"), val) if absu else None
    if verb in DOWN:
        if pct:
            return "scale", (x / 100.0 if to else 1.0 - x / 100.0)
        return (("set", val) if to else ("add", -val)) if absu else None
    # 设定类
    if pct:
        return "scale", x / 100.0
    return "set", val


class _Act:
    """内部动作：一条将变成 Δπ / 挂起意图的修改。"""

    def __init__(self, kind: str, component: str, param: str, sentence: int, clauses: set[int]):
        self.kind = kind                      # explicit / outage / inferred
        self.component = component
        self.param = param
        self.sentence = sentence
        self.clauses = clauses
        self.operation: str | None = None
        self.direction: str | None = None
        self.value: float | None = None
        self.spans: list[tuple[int, int]] = []
        self.ents: list[Entity] = []          # 参与的实体（对象 / 关键词 / 时段 / 数值）
        self.targets: list[Entity] = []       # 已确定的对象实体
        self.amb: Entity | None = None        # 并联 / 多机：待追问
        self.chain: list[str] | None = None
        self.label = ""

    @property
    def start(self) -> int:
        return min(s for s, _ in self.spans) if self.spans else 0


class DemoRuleEngine:
    name = "demo"
    display = "演示规则引擎"

    # ---------------------------------------------------------------- parse
    def parse(self, instruction: str, ctx: ParseContext) -> ParseResult:
        t0 = time.perf_counter()
        text = instruction
        kb = knowledge()
        res = ParseResult(instruction=instruction, engine=self.name, engine_name=self.display)

        objs = extract_objects(text, ctx.snap, ctx.topo)
        kvs = extract_kv_mentions(text, objs)
        sw = match_switching_limit(text)
        struct_spans = [Span(m["start"], m["end"]) for m in sw]
        pers = extract_periods(text, ctx.window, ctx.periods, taken=[Span(o.start, o.end) for o in objs])
        kws = extract_keywords(text)

        sents = split_sentences(text)
        clauses = split_clauses(text)

        def sent_of(pos: int) -> int:
            for i, (s, e) in enumerate(sents):
                if s <= pos <= e:
                    return i
            return max(0, len(sents) - 1)

        def clause_of(pos: int) -> int:
            for i, (s, e) in enumerate(clauses):
                if s <= pos <= e:
                    return i
            return max(0, len(clauses) - 1)

        # ---- 数值实体 ----
        mags: list[tuple[re.Match, tuple[str, float]]] = []
        for m in MAG_RE.finditer(text):
            c = _classify(m)
            if c:
                mags.append((m, c))

        consumed: list[Span] = []           # 已被结构动作 / 显式修改占用的区间
        acts: list[_Act] = []
        structural: list[StructuralOp] = []
        struct_ents: dict[str, list[Entity]] = {}
        kw_by_id = {k.id: k for k in kws}

        def add_struct(op_id: str, kind: str, params: dict, evidence: str, ents: list[Entity], pending: list[str] | None = None) -> None:
            if any(s.op_id == op_id for s in structural) and op_id not in ("section_limit",):
                return
            sid = f"s-{len(structural) + 1}"
            structural.append(StructuralOp(id=sid, kind=kind, op_id=op_id, params=params, source="explicit", evidence=evidence,  # type: ignore[arg-type]
                                           pending_fields=pending or []))
            struct_ents[sid] = ents

        # ---- 结构：断面限额 ----
        for si, (ss, se) in enumerate(sents):
            sec_kw = [k for k in kws if k.role == "structural" and k.rule_id == "section_limit" and ss <= k.start < se]
            if not sec_kw:
                continue
            brs = [o for o in objs if o.type == "branch" and ss <= o.start < se]
            ids: list[str] = []
            for o in brs:
                ids.extend(o.candidates if o.status == "ambiguous" else ([o.object_id] if o.object_id else []))
            lim = next((mm for mm in MW_RE.finditer(text, ss, se)), None)
            limit = to_mw(float(lim.group("num")), lim.group("unit")) if lim else None
            spans = [(k.start, k.end) for k in sec_kw] + [(o.start, o.end) for o in brs] + ([(lim.start(), lim.end())] if lim else [])
            # 限额数值前的“设为”等动词一并纳入证据
            mg = next((m for m, _ in mags if lim and m.start() <= lim.start() < m.end()), None)
            if mg is not None:
                spans.append((mg.start(), mg.end()))
                consumed.append(Span(mg.start(), mg.end()))
            for o in brs:
                consumed.append(Span(o.start, o.end))
            pend = (["limit_mw"] if limit is None else []) + (["branches"] if not ids else [])
            ev = text[min(s for s, _ in spans):max(e for _, e in spans)]
            add_struct("section_limit", "constraint", {"branches": ids, "limit_mw": limit, "direction": "forward"}, ev,
                       sec_kw + brs, pend)

        # ---- 结构：开关次数 ----
        for m in sw:
            op = "switching_limit_total" if m["total"] else "switching_limit_per_period"
            ents = [e for e in pers if m["start"] <= e.start and e.end <= m["end"]]
            add_struct(op, "constraint", {("K" if m["total"] else "k"): m["k"]}, text[m["start"]:m["end"]], ents)

        # ---- 结构：目标项、固定拓扑 ----
        for k in kws:
            if k.role != "structural":
                continue
            rid = k.rule_id
            if rid == "switching_penalty":
                add_struct("switching_penalty", "objective", {"beta": None}, k.text, [k])
            elif rid == "loss_min":
                add_struct("loss_min", "objective", {"beta": None}, k.text, [k])
            elif rid == "voltage_deviation":
                add_struct("voltage_deviation", "objective", {"beta": None}, k.text, [k])
            elif rid == "fixed_topology":
                add_struct("multi_period_acopf", "problem", {}, k.text, [k])
            elif rid == "generator_redispatch":
                add_struct("generator_redispatch", "problem", {"ramp_pct": None}, k.text, [k])
            elif rid == "unit_commitment":
                uc = match_uc_limit(text)
                if uc:
                    add_struct("unit_commitment", "constraint", {"max_switch": uc["k"]}, text[min(k.start, uc["start"]):uc["end"]], [k])
                else:
                    add_struct("unit_commitment", "constraint", {"max_switch": None}, k.text, [k], ["max_switch"])
            elif rid in ("cost_economic", "reliability_nm1", "renewable_accommodation"):
                coef = "unit_cost" if rid == "cost_economic" else "penalty"
                add_struct(rid, "objective", {coef: None}, k.text, [k], [coef])

        # ---- N−1：确认 ω，不生成 s ----
        n1_on = [k for k in kws if k.rule_id == "n_minus_1_on"]
        n1_off = [k for k in kws if k.rule_id == "n_minus_1_off"]
        if n1_off:
            res.omega_confirm = {"n_minus_1": False, "evidence": text[n1_off[0].start:n1_off[0].end]}
        elif n1_on:
            k = n1_on[0]
            pre = re.search(r"(?:满足|考虑|按|按照|通过)\s*$", text[:k.start])
            s0 = pre.start() if pre else k.start
            res.omega_confirm = {"n_minus_1": True, "evidence": text[s0:k.end]}

        # ---- Δπ：显式数值 ----
        for si, (ss, se) in enumerate(sents):
            for ci, (cs, ce) in enumerate(clauses):
                if cs < ss or ce > se:
                    continue
                cm = [(m, c) for m, c in mags if cs <= m.start() < ce and not any(sp.overlaps(Span(m.start(), m.end())) for sp in consumed)]
                prev_end = cs
                for m, (op, val) in cm:
                    seg_s, seg_e = prev_end, m.start()
                    prev_end = m.end()
                    ph = self._phrase_before(text, seg_s, seg_e)
                    if ph is None:
                        continue
                    comp, param, ps, pe = ph
                    act = _Act("explicit", comp, param, si, {ci})
                    act.operation, act.value = op, val
                    act.spans += [(ps, pe), (m.start(), m.end())]
                    mag_ent = Entity(id="", type="keyword", text=text[m.start():m.end()], start=m.start(), end=m.end(), status="ok", role="magnitude")
                    act.ents.append(mag_ent)
                    self._bind_objects(act, objs, comp, seg_s, m.start(), cs, ce, ss, se, ps)
                    consumed.append(Span(ps, m.end()))
                    acts.append(act)

        # ---- Δπ：检修 / 停运 ----
        out_kws = [k for k in kws if k.role == "outage"]
        groups: list[list[Entity]] = []
        for k in out_kws:
            if groups and k.start - groups[-1][-1].end <= 1:
                groups[-1].append(k)
            else:
                groups.append([k])
        for g in groups:
            si = sent_of(g[0].start)
            ss, se = sents[si]
            ci = clause_of(g[0].start)
            cs, ce = clauses[ci]
            cand = [o for o in objs if o.type in ("branch", "gen") and cs <= o.start < ce]
            if not cand:
                cand = [o for o in objs if o.type in ("branch", "gen") and ss <= o.start < se and not any(sp.overlaps(Span(o.start, o.end)) for sp in consumed)]
            for o in cand:
                comp = o.type
                param = "BR_STATUS" if comp == "branch" else "GEN_STATUS"
                act = _Act("outage", comp, param, si, {ci})
                act.operation, act.value = "set", 0.0
                act.spans += [(k.start, k.end) for k in g]
                act.ents += list(g)
                if o.status == "ambiguous":
                    act.amb = o
                else:
                    act.targets.append(o)
                act.spans.append((o.start, o.end))
                act.ents.append(o)
                acts.append(act)

        # ---- Δπ：推断（知识表）----
        for rule in kb["inference_rules"]:
            by_sent: dict[int, list[Entity]] = {}
            for k in kws:
                if k.role == "inference" and k.rule_id == rule["id"] and not any(sp.overlaps(Span(k.start, k.end)) for sp in consumed):
                    by_sent.setdefault(sent_of(k.start), []).append(k)
            for si, ks in by_sent.items():
                ss, se = sents[si]
                comp = rule["component"]
                used = {o.object_id for a in acts if a.sentence == si and (a.kind == "outage" or a.param == rule["param"]) for o in a.targets}
                cand = [o for o in objs if o.type == comp and ss <= o.start < se and o.object_id not in used and not any(sp.overlaps(Span(o.start, o.end)) for sp in struct_spans)]
                cl = {clause_of(k.start) for k in ks}
                act = _Act("inferred", comp, rule["param"], si, cl)
                act.direction = rule["direction"]
                act.spans += [(k.start, k.end) for k in ks]
                act.ents += list(ks)
                event = rule.get("event")
                hit_event = any(w in text[k.start:k.end] for k in ks for w in rule.get("event_keywords", []))
                act.chain = [event if (event and hit_event) else ks[0].text, rule["mechanism"], rule["action"]]
                if not cand:
                    act.label = rule["name"]
                    acts.append(act)
                    continue
                for o in cand:
                    a = _Act("inferred", comp, rule["param"], si, set(cl))
                    a.direction, a.spans, a.ents, a.chain = act.direction, list(act.spans), list(act.ents), list(act.chain or [])
                    a.spans.append((o.start, o.end))
                    a.ents.append(o)
                    if o.status == "ambiguous":
                        a.amb = o
                    else:
                        a.targets.append(o)
                    acts.append(a)

        # ---- 对象的电压等级提及并入证据 ----
        for a in acts:
            for o in a.targets + ([a.amb] if a.amb else []):
                for kv in kvs:
                    if kv.object_id == o.object_id or (a.amb and kv.candidates and set(kv.candidates) == set(a.amb.candidates)):
                        a.spans.append((kv.start, kv.end))
                        if kv not in a.ents:
                            a.ents.append(kv)

        # ---- 时段 ----
        acts.sort(key=lambda a: a.start)
        deltas: list[DeltaPi] = []
        pending: list[PendingIntent] = []
        n = ctx.periods

        def periods_for(a: _Act) -> tuple[list[int], bool, list[Entity]]:
            cands = [p for p in pers if sent_of(p.start) == a.sentence and not any(sp.overlaps(Span(p.start, p.end)) for sp in struct_spans)]
            if not cands:
                return [], False, []
            if n == 1:                      # 单时段断面：“午后”“明天”这类模糊说法不产生追问；明确写出的时段仍照常解析（超出范围由校验 E105 报）
                cands = [p for p in cands if p.status != "fuzzy"] or []
                if not cands:
                    return [], False, []
            inside = [p for p in cands if clause_of(p.start) in a.clauses]
            if not inside:
                dist = lambda p: min(abs(clause_of(p.start) - c) for c in a.clauses)  # noqa: E731
                d0 = min(dist(p) for p in cands)
                inside = [p for p in cands if dist(p) == d0]
            if any(p.status == "fuzzy" for p in inside):
                return [], True, inside
            if any(p.periods == [] for p in inside):
                return [], False, inside
            s: set[int] = set()
            for p in inside:
                s |= set(p.periods or [])
            return sorted(s), False, inside

        item_ents: dict[str, list[Entity]] = {}
        for a in acts:
            ps, unresolved, pents = periods_for(a)
            a.spans += [(p.start, p.end) for p in pents]
            a.ents += pents
            ev = text[min(s for s, _ in a.spans):max(e for _, e in a.spans)]
            if a.amb is not None or (not a.targets):
                p_id = f"pd-{len(pending) + 1}"
                pend = PendingIntent(
                    id=p_id, component=a.component, param=a.param, operation=a.operation, direction=a.direction,  # type: ignore[arg-type]
                    value=a.value, source="inferred" if a.kind == "inferred" else "explicit", evidence=ev,
                    inference_chain=a.chain, periods=ps, periods_unresolved=unresolved,
                    candidates=(a.amb.candidates if a.amb else []), label=a.label or "")
                if a.kind == "outage":
                    pend.direction = None
                pending.append(pend)
                item_ents[p_id] = a.ents
                continue
            for o in a.targets:
                did = f"dp-{len(deltas) + 1}"
                pf = []
                if unresolved:
                    pf.append("periods")
                if a.kind == "inferred":
                    pf.append("value")
                d = DeltaPi(
                    id=did, component=a.component, target=o.object_id or o.text, param=a.param,  # type: ignore[arg-type]
                    operation=a.operation if a.kind != "inferred" else None,  # type: ignore[arg-type]
                    direction=a.direction if a.kind == "inferred" else None,  # type: ignore[arg-type]
                    value=a.value if a.kind != "inferred" else None, periods=list(ps),
                    source="inferred" if a.kind == "inferred" else "explicit", evidence=ev,  # type: ignore[arg-type]
                    inference_chain=a.chain if a.kind == "inferred" else None, confirmed=False, pending_fields=pf)
                deltas.append(d)
                item_ents[did] = a.ents
        res.delta_pi, res.structural, res.pending = deltas, structural, pending
        for sid, ents in struct_ents.items():
            item_ents[sid] = ents

        # ---- 实体列表（解析卡片）----
        all_ents: list[Entity] = []
        seen: set[tuple[str, int, int]] = set()
        for e in objs + kvs + pers + kws:
            all_ents.append(e)
            seen.add((e.type, e.start, e.end))
        for ents in item_ents.values():
            for e in ents:
                if e.type == "keyword" and e.role == "magnitude" and ("keyword", e.start, e.end) not in seen:
                    all_ents.append(e)
                    seen.add(("keyword", e.start, e.end))
        all_ents.sort(key=lambda e: (e.start, e.end))
        for i, e in enumerate(all_ents, start=1):
            e.id = f"e{i}"
        index = {(e.type, e.start, e.end): e for e in all_ents}
        for iid, ents in item_ents.items():
            for e in ents:
                tgt = index.get((e.type, e.start, e.end))
                if tgt is not None and iid not in tgt.item_ids:
                    tgt.item_ids.append(iid)
        res.entities = all_ents
        # 没有进入规格的提示，交给第 5 层 W502；这里只记说明
        if not deltas and not structural and not pending:
            res.notes.append("没有识别到可建模的参数修改或结构修改，需要追问。")
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return dialog.finalize(res, ctx)

    # ---------------------------------------------------------------- answer
    def answer(self, state: ParseResult, question_id: str, answer: str, ctx: ParseContext) -> ParseResult:
        t0 = time.perf_counter()
        out = dialog.apply_answer(state.model_copy(deep=True), question_id, answer, ctx)
        out.elapsed_ms = state.elapsed_ms + (time.perf_counter() - t0) * 1000
        return out

    # ---------------------------------------------------------------- 内部
    @staticmethod
    def _phrase_before(text: str, seg_s: int, seg_e: int) -> tuple[str, str, int, int] | None:
        """在 [seg_s, seg_e) 内，离数值最近的参数说法（最长优先）。"""
        best = None
        for comp, param, w in _PHRASES:
            i = text.rfind(w, seg_s, seg_e)
            while i >= 0:
                e = i + len(w)
                if seg_e - e <= 6:
                    if best is None or e > best[3] or (e == best[3] and len(w) > best[3] - best[2]):
                        best = (comp, param, i, e)
                    break
                i = text.rfind(w, seg_s, i + len(w) - 1) if i > seg_s else -1
        return best

    @staticmethod
    def _bind_objects(act: _Act, objs: list[Entity], comp: str, seg_s: int, mag_start: int, cs: int, ce: int, ss: int, se: int, ph_start: int) -> None:
        def pick(lo: int, hi: int) -> list[Entity]:
            return [o for o in objs if o.type == comp and lo <= o.start and o.end <= hi]

        found = pick(seg_s, mag_start) or pick(cs, ce)
        if not found:
            near = [o for o in objs if o.type == comp and ss <= o.start < se]
            if near:
                found = [min(near, key=lambda o: abs(o.start - ph_start))]
        for o in found:
            act.spans.append((o.start, o.end))
            act.ents.append(o)
            if o.status == "ambiguous":
                act.amb = o
            else:
                act.targets.append(o)
        if act.amb is not None:
            act.targets = []

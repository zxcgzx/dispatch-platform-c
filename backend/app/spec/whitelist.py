"""参数白名单（指令 5.2）与数值范围校验。数值范围放在 config/app.yaml，可修改。"""
from __future__ import annotations

from ..config import app_config
from .schema import DeltaPi

# 对象 → 参数 → {允许的操作, 推断方向, 公式符号, 中文名, 单位}
WHITELIST: dict[str, dict[str, dict]] = {
    "bus": {
        "PD": {"ops": ["scale", "set", "add"], "dirs": ["increase", "decrease"], "symbol": r"P^{D}", "label": "有功负荷", "unit": "MW"},
        "QD": {"ops": ["scale", "set", "add"], "dirs": ["increase", "decrease"], "symbol": r"Q^{D}", "label": "无功负荷", "unit": "Mvar"},
        "VMAX": {"ops": ["set"], "dirs": [], "symbol": r"\overline{V}", "label": "电压上限", "unit": "p.u."},
        "VMIN": {"ops": ["set"], "dirs": [], "symbol": r"\underline{V}", "label": "电压下限", "unit": "p.u."},
    },
    "gen": {
        "PMAX": {"ops": ["scale", "set"], "dirs": ["increase", "decrease"], "symbol": r"\overline{P}", "label": "出力上限", "unit": "MW"},
        "PMIN": {"ops": ["scale", "set"], "dirs": ["increase", "decrease"], "symbol": r"\underline{P}", "label": "出力下限", "unit": "MW"},
        "GEN_STATUS": {"ops": ["set"], "dirs": ["set_zero"], "symbol": "u", "label": "机组状态", "unit": ""},
    },
    "branch": {
        "RATE_A": {"ops": ["scale", "set"], "dirs": ["increase", "decrease"], "symbol": r"\bar S", "label": "热稳限额", "unit": "MVA"},
        "BR_STATUS": {"ops": ["set"], "dirs": ["set_zero"], "symbol": "z", "label": "支路状态", "unit": ""},
    },
}

COMPONENT_LABEL = {"bus": "母线", "gen": "机组", "branch": "支路"}
ID_PREFIX = {"bus": "B", "gen": "G", "branch": "L"}
DIRECTION_LABEL = {"increase": "调高", "decrease": "调低", "set_zero": "置 0"}
OP_LABEL = {"scale": "按比例", "set": "设定为", "add": "增加"}


def whitelist_json() -> dict:
    """给界面（参数按对象类型过滤）和大模型提示词用的可序列化白名单。"""
    return {
        comp: {p: {"ops": v["ops"], "dirs": v["dirs"], "label": v["label"], "unit": v["unit"]} for p, v in params.items()}
        for comp, params in WHITELIST.items()
    }


def param_info(component: str, param: str) -> dict | None:
    return WHITELIST.get(component, {}).get(param)


def validate_delta_pi(dp: DeltaPi) -> list[tuple[str, str]]:
    """第 1 层中 E102 / E103 / E104 的纯规则部分。返回 [(code, 说明)]。"""
    out: list[tuple[str, str]] = []
    info = param_info(dp.component, dp.param)
    if info is None:
        label = COMPONENT_LABEL.get(dp.component, dp.component)
        out.append(("E102", f"参数 {dp.param} 不在{label}类对象的白名单内（允许：{', '.join(WHITELIST.get(dp.component, {}))}）"))
        return out
    rng = app_config()["ranges"]
    if dp.source == "explicit":
        if dp.operation is None or dp.value is None:
            out.append(("E103", "明确项缺少 operation 或 value"))
            return out
        if dp.operation not in info["ops"]:
            out.append(("E102", f"操作 {dp.operation} 不适用于 {dp.param}（允许：{', '.join(info['ops'])}）"))
            return out
        out.extend(_range_errors(dp, rng, info))
    else:
        if dp.direction is None:
            out.append(("E103", "推断项缺少 direction"))
            return out
        if dp.direction not in info["dirs"]:
            out.append(("E102", f"方向 {dp.direction} 不适用于 {dp.param}（允许：{', '.join(info['dirs']) or '无'}）"))
            return out
        if dp.value is not None:  # 用户确认后填了幅度：按比例（scale）或绝对值（set）
            if dp.operation == "set":
                if dp.value < 0:
                    out.append(("E104", f"{dp.param} 设定值不能为负，实际为 {dp.value:g}"))
            elif dp.operation not in (None, "scale"):
                out.append(("E102", "推断项的幅度只能按比例（scale）或设定值（set）填写"))
            else:
                v = dp.value
                if not (rng["scale_min_exclusive"] < v <= rng["scale_max"]):
                    out.append(("E104", f"缩放系数 {v:g} 越界，应在 ({rng['scale_min_exclusive']:g}, {rng['scale_max']:g}] 内"))
                elif dp.direction == "decrease" and v >= 1:
                    out.append(("E104", f"方向为“调低”，缩放系数应小于 1，实际为 {v:g}"))
                elif dp.direction == "increase" and v <= 1:
                    out.append(("E104", f"方向为“调高”，缩放系数应大于 1，实际为 {v:g}"))
    return out


def _range_errors(dp: DeltaPi, rng: dict, info: dict) -> list[tuple[str, str]]:
    v = dp.value
    assert v is not None
    out: list[tuple[str, str]] = []
    if dp.param in ("GEN_STATUS", "BR_STATUS"):
        if v not in rng["status_values"]:
            out.append(("E104", f"状态只能是 {rng['status_values']}，实际为 {v:g}"))
    elif dp.param in ("VMAX", "VMIN"):
        if not (rng["voltage_min"] <= v <= rng["voltage_max"]):
            out.append(("E104", f"{dp.param} = {v:g} 越界，应在 [{rng['voltage_min']:g}, {rng['voltage_max']:g}] 内"))
    elif dp.operation == "scale":
        if not (rng["scale_min_exclusive"] < v <= rng["scale_max"]):
            out.append(("E104", f"缩放系数 {v:g} 越界，应在 ({rng['scale_min_exclusive']:g}, {rng['scale_max']:g}] 内"))
    elif dp.operation == "set" and dp.param in ("PMAX", "PMIN", "RATE_A") and v < 0:
        out.append(("E104", f"{dp.param} 设定值不能为负，实际为 {v:g}"))
    return out

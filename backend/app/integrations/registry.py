"""外部接口登记与状态：顶栏状态灯、“数据与接口”页都读这里。

state：connected 已接入 / mock 本地模拟或占位 / none 未接入
"""
from __future__ import annotations

from ..config import settings


def _llm_state() -> tuple[str, str]:
    if settings.llm_mode == "openai" and settings.llm_base_url:
        return "connected", f"OpenAI 兼容接口：{settings.llm_base_url}（模型 {settings.llm_model or '未设置'}）"
    return "none", "未配置（LLM_MODE=demo 时使用离线演示规则引擎）"


def integrations() -> list[dict]:
    llm_state, llm_detail = _llm_state()
    method = settings.method_endpoint
    risk = settings.risk_endpoint
    mode = settings.solver_mode
    return [
        {
            "id": "t2_data", "name": "课题 2 测点数据", "feature": "m1.tp_data",
            "state": "none", "state_label": "未接入", "mode": "接口预留", "endpoint": "",
            "detail": "节点 → 模拟测点、逆向恢复与方案回写已实现（测点转换页）；真实测点接入需课题 2 提供映射、单位字典与标识范围。",
            "request": "静态 / 动态两组表（XLSX / CSV），按母线、变压器、开关、连接线路四类对象组织",
            "response": "节点模型（Bus / Gen / Branch）；方案回写为开关动作清单",
        },
        {
            "id": "t2_llm", "name": "课题 2 大模型", "feature": "m1.llm_t2",
            "state": "none", "state_label": "未接入", "mode": "接口预留", "endpoint": "",
            "detail": "建议 OpenAI 兼容对话接口，输出规格 JSON。当前可用“本地 Qwen（OpenAI 兼容）”引擎做同类对接。",
            "request": "POST /v1/chat/completions {model, messages}",
            "response": "choices[0].message.content = 规格 JSON（delta_pi / structural / questions）",
        },
        {
            "id": "ext_method", "name": "外部建模与校验引擎", "feature": "m2.ext_model",
            "state": "connected" if method else "none",
            "state_label": "已接入" if method else "未接入",
            "mode": "HTTP" if method else "接口预留", "endpoint": method,
            "detail": "动态建模（/parse）与去幻觉（/check）。未配置 METHOD_ENDPOINT 时，模型选择里显示“外部建模引擎（接口预留）”且不可选；第 5 层显示“外部方法：未接入”。",
            "request": "POST {METHOD_ENDPOINT}/parse  {instruction, snapshot_meta, whitelist, operators}\nPOST {METHOD_ENDPOINT}/check  {instruction, spec}",
            "response": "/parse → {delta_pi, structural, questions, findings}\n/check → findings 列表（合并进第 5 层并注明来源）",
        },
        {
            "id": "llm", "name": "本地 Qwen（OpenAI 兼容）", "feature": "m1.model_select",
            "state": llm_state, "state_label": {"connected": "已配置", "none": "未配置"}[llm_state],
            "mode": settings.llm_mode, "endpoint": settings.llm_base_url, "detail": llm_detail,
            "request": "POST {LLM_BASE_URL}/chat/completions {model, messages, temperature}",
            "response": "输出先用 Pydantic 校验，失败回传错误重试一次，仍失败转追问；连不上自动回落到演示规则引擎并提示",
        },
        {
            "id": "solver", "name": "求解器", "feature": "m5.solve",
            "state": "mock" if mode == "mock" else "connected",
            "state_label": {"builtin": "内置求解器", "mock": "占位（mock）", "import": "导入结果", "external": "外部命令"}[mode],
            "mode": mode, "endpoint": settings.solver_cmd if mode == "external" else "",
            "detail": "内置 HiGHS 求解直流近似 OTS（默认）；也可 mock 占位、导入结果 JSON，或用 external 执行 SOLVER_CMD 接现有求解链。不做求解加速。",
            "request": "SOLVER_CMD 例：python solve.py --spec {spec} --snapshots {dir} --out {out}",
            "response": "结果 JSON，格式见 backend/app/solver/result_schema.json",
        },
        {
            "id": "risk", "name": "课题 3 风险评估", "feature": "m7.risk",
            "state": "connected" if risk else "mock",
            "state_label": "已接入" if risk else "本地规则模拟",
            "mode": "HTTP" if risk else "本地模拟", "endpoint": risk,
            "detail": "未配置 RISK_ENDPOINT 时用本地规则：ρ≥100% 或 N−1 筛查不通过为“高”；ρ≥80% 或电压越限为“中”；其余为“低”。",
            "request": "POST {RISK_ENDPOINT}  {task_id, version, metrics, result_summary}",
            "response": "{risk_level: 低|中|高, reasons: [], reward: number|null}",
        },
    ]

"""功能登记表：状态的唯一来源。

后端 `/api/features` 直接输出这份表；前端 `src/features.ts` 启动时从接口取，
`scripts/gen_features.py` 把同一份表导出成 `frontend/src/features.fallback.json` 作离线兜底。
所有按钮、标签页、卡片的状态徽标都从这里按 id 取，不在组件里写死。

状态：implemented 已实现 / blackbox 黑盒 / reserved 接口预留 / todo 待开发
"""
from __future__ import annotations

from typing import Literal

Status = Literal["implemented", "blackbox", "reserved", "todo"]

STATUS_LABEL = {"implemented": "已实现", "blackbox": "黑盒", "reserved": "接口预留", "todo": "待开发"}

MODULES = {
    "M1": "输入与场景",
    "M2": "语义解析与层级判定",
    "M3": "模型规格与方程确认",
    "M4": "去幻觉与校验",
    "M5": "求解",
    "M6": "结果与地图",
    "M7": "风险评估与动态调整",
    "M8": "测评模式",
    "M9": "问题分解与多智能体",
}

# (id, 模块, 名称, 状态, 说明)
_F: list[tuple[str, str, str, Status, str]] = [
    # M1
    ("m1.instruction", "M1", "文本指令输入", "implemented", "自然语言调度指令输入，生成任务记录"),
    ("m1.templates", "M1", "场景模板", "implemented", "检修、高温限额下降、负荷增长、开关次数限制、断面限额"),
    ("m1.snapshot", "M1", "断面选择", "implemented", "断面库按时刻排序，取 16 个间隔 15 分钟的最近断面；单断面时复制成 16 时段"),
    ("m1.model_select", "M1", "模型与提问设置", "implemented", "演示规则引擎 / 本地 Qwen；是否追问与最多追问轮数"),
    ("m1.voice", "M1", "语音输入", "todo", "任务书的具身智能样机要求调度指令语音交互"),
    ("m1.tp_data", "M1", "测点 ↔ 节点转换（模拟测点）", "implemented", "节点 → 模拟测点（母线 / 变压器 / 开关 / 连接线路）、静态动态表、逆向恢复与往返验证；真实测点接入待课题 2 提供映射与字段字典"),
    ("m1.llm_t2", "M1", "课题 2 大模型", "reserved", "OpenAI 兼容对话接口，输出规格 JSON"),
    ("m1.llm_proopf", "M1", "ProOPF 微调模型", "reserved", "微调 Qwen3-30B-A3B，部署后以 OpenAI 兼容接口接入"),
    # M2
    ("m2.entities", "M2", "实体解析与原文高亮", "implemented", "母线、支路、机组、时段、数值；点一下在原文高亮依据"),
    ("m2.level", "M2", "L1–L4 判级", "implemented", "由程序从规格推出，不信大模型自报；可人工改选并留痕"),
    ("m2.chain", "M2", "推断链", "implemented", "事件 → 机理 → 参数；推断项必须人工确认"),
    ("m2.ask", "M2", "追问", "implemented", "对象、时段、幅度不明确时追问，给选项按钮"),
    ("m2.ext_model", "M2", "外部建模引擎接入", "reserved", "动态建模：可接入外部解析服务，输出规格 Δπ / s"),
    # M3
    ("m3.spec", "M3", "规格编辑", "implemented", "ω、Δπ、s、R 四块可编辑表单"),
    ("m3.formula", "M3", "公式渲染", "implemented", "基础模型 B1–B9 逐块渲染，改动块高亮"),
    ("m3.code", "M3", "代码生成", "implemented", "规格 → Pyomo 代码，带标记，与规格行双向跳转"),
    ("m3.scale", "M3", "规模估算", "implemented", "变量数、0-1 变量数、约束数；三种可开断集合口径并列"),
    ("m3.trial", "M3", "试构建", "implemented", "子进程执行同一份代码（T = 1，不含 N−1），限时 60 秒"),
    ("m3.versions", "M3", "版本管理", "implemented", "规格版本链与差异比对"),
    # M4
    ("m4.checks", "M4", "五层校验", "implemented", "规格合法 / 结构一致 / 数据检查 / 可执行 / 语义回译"),
    ("m4.ext_check", "M4", "外部去幻觉校验接入", "reserved", "外部校验结果并入第 5 层"),
    ("m4.iis", "M4", "冲突定位（IIS）", "todo", "需要求解器支持，求解不可行时给出冲突与允许调整项"),
    # M5
    ("m5.solve", "M5", "求解", "implemented", "内置 HiGHS（直流近似 OTS）真实求解；mock / 导入结果 / 外部命令（接现有求解链）可切换；不做求解加速"),
    ("m5.import", "M5", "结果导入", "implemented", "上传结果 JSON，按 result_schema.json 校验后作为该版本结果"),
    ("m5.external", "M5", "外部求解器", "reserved", "SOLVER_CMD 命令适配框架，后续接 905 节点 IPOPT 求解链"),
    # M6
    ("m6.matrix", "M6", "开断矩阵", "implemented", "时段 × 支路，断开格子着色"),
    ("m6.gen", "M6", "出力曲线", "implemented", "机组 16 时段出力，越界标红"),
    ("m6.topo", "M6", "拓扑网架图", "implemented", "905 节点 / 1000 支路，坐标后端预算，按电压等级与负载率着色"),
    ("m6.compare", "M6", "前后对比", "implemented", "调整前（断面）与调整后（结果）并排，只列差异项"),
    ("m6.geomap", "M6", "地理地图", "implemented", "大理州真实行政区划底图叠加网架；变电站落点按拓扑分区示意，待大理地理坐标后精确定位"),
    ("m6.writeback", "M6", "结果回写测点", "implemented", "把开断方案映射为虚拟开关动作清单；现场设备执行待课题 2 提供真实控制点关联规则"),
    # M7
    ("m7.loadrate", "M7", "负载率指标", "implemented", "最大值、平均值、≥80%、≥100% 条数"),
    ("m7.voltage", "M7", "电压偏移指标", "implemented", "最大值、平均值、越限母线数"),
    ("m7.n1", "M7", "N−1 直流筛查", "implemented", "PTDF / LODF 直流近似筛查，非交流 N−1 校核"),
    ("m7.vsm", "M7", "静态电压稳定裕度", "todo", "需要连续潮流"),
    ("m7.renewable", "M7", "新能源消纳率", "todo", "数据中没有新能源机组信息，暂不计算"),
    ("m7.risk", "M7", "课题 3 风险评估", "reserved", "配置 RISK_ENDPOINT 后调用；未配置时用本地规则模拟"),
    ("m7.negotiate", "M7", "协商调整", "implemented", "按风险原因生成待确认的 Δπ / s 建议，生成新版本"),
    ("m7.reward", "M7", "Reward 反馈", "reserved", "对应任务 3 的安全强化学习，中期之后部署"),
    # M8
    ("m8.testmode", "M8", "测评模式", "implemented", "批量跑 解析 → 判级 → 校验，规格级比对，导出报告"),
    ("m8.objective", "M8", "目标值比对测评", "todo", "等求解接入后做，ProOPF 以求解目标值判对错"),
    # M9
    ("m9.decompose", "M9", "问题分解（任务 2）", "todo", "问题类型识别、分解策略选择、子问题网络"),
    ("m9.multiagent", "M9", "多智能体协同（任务 4）", "todo", "子问题智能体、边端协同、全局收敛"),
    ("m9.knowledge", "M9", "知识库", "todo", "建模规则与调度规程知识库"),
    # 其他
    ("host.embed", "M1", "宿主平台嵌入", "reserved", "/embed/workbench 已可 iframe 嵌入；账号与风格对齐待博文老师侧确认"),
]


def feature_table() -> list[dict]:
    return [
        {"id": i, "module": m, "module_name": MODULES[m], "name": n, "status": s, "status_label": STATUS_LABEL[s], "note": note}
        for i, m, n, s, note in _F
    ]


def feature_response() -> dict:
    return {"status_labels": STATUS_LABEL, "modules": MODULES, "features": feature_table()}

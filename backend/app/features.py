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
    "M1": "指令输入与场景",
    "M2": "层级判定（L1–L4）",
    "M3": "动态建模、规格与方程确认",
    "M4": "去幻觉校验与无解诊断",
    "M5": "求解",
    "M6": "结果与地图",
    "M7": "风险评估与协商",
    "M8": "测评模式",
    "M9": "聚合与分解",
    "M10": "强化学习与 CMDP",
    "X": "跨课题接口",
}

# (id, 模块, 名称, 状态, 说明)
_F: list[tuple[str, str, str, Status, str]] = [
    # M1
    ("m1.instruction", "M1", "文本指令输入", "implemented", "自然语言调度指令，附示例与场景模板"),
    ("m1.builder", "M1", "指令构建器", "implemented", "选对象、动作、约束与目标，自动拼成一句指令"),
    ("m1.conditions", "M1", "条件拆解", "implemented", "把指令拆成对象、参数、幅度、时段、约束要求、目标要求六类条件"),
    ("m1.templates", "M1", "场景模板", "implemented", "检修、高温限额下降、负荷增长、开关次数限制、断面限额、机组启停"),
    ("m1.snapshot", "M1", "断面选择", "implemented", "905 节点断面库；一个断面对应一个时段，断面库有多个文件时按时刻排成连续时段"),
    ("m1.model_select", "M1", "模型与提问设置", "implemented", "演示规则引擎 / 本地小模型；是否追问与最多追问轮数"),
    ("m1.voice", "M1", "语音输入", "todo", "调度指令语音交互"),
    ("m1.llm_t2", "M1", "课题 2 大模型入口", "reserved", "OpenAI 兼容对话接口，输出规格 JSON"),
    ("m1.llm_proopf", "M1", "微调模型入口", "reserved", "微调后的小模型部署成 OpenAI 兼容接口即可接入，单卡可运行"),
    ("m1.tp_data", "M1", "测点 ↔ 节点转换（模拟测点）", "implemented", "节点 → 模拟测点、静态动态表、逆向恢复与往返验证"),
    # M2
    ("m2.entities", "M2", "实体解析与原文高亮", "implemented", "母线、支路、机组、时段、数值；点一下在原文高亮依据"),
    ("m2.level", "M2", "L1–L4 判级与手动改选", "implemented", "程序从规格推出层级，用户可手动改选并留痕"),
    ("m2.chain", "M2", "推断链", "implemented", "事件 → 机理 → 参数；推断项必须人工确认"),
    ("m2.ask", "M2", "追问", "implemented", "对象、时段、幅度、系数不明确时追问，给选项按钮"),
    ("m2.examples", "M2", "分级示例指令", "implemented", "L1–L4 每一级至少一条可直接运行的示例"),
    ("m2.ext_model", "M2", "外部动态建模引擎接入", "reserved", "HTTP 接入外部建模服务，输出规格 Δπ / s"),
    # M3
    ("m3.spec", "M3", "规格编辑", "implemented", "ω、Δπ、s、R 四块可编辑表单"),
    ("m3.problem_switch", "M3", "优化类型动态切换", "implemented", "AC-OPF / AC-OTS 可切换，机组出力调整、机组启停可叠加"),
    ("m3.objectives", "M3", "目标函数类别", "implemented", "偏离当前方式、开关惩罚、网损、电压偏差、经济性、可靠性、新能源消纳"),
    ("m3.unit", "M3", "机组建模", "implemented", "出力上下限、爬坡、出力再调度、机组启停（0-1）"),
    ("m3.formula", "M3", "公式渲染", "implemented", "基础模型 B1–B9 逐块渲染，改动块高亮"),
    ("m3.code", "M3", "代码生成", "implemented", "规格 → Pyomo 代码，带标记，与规格行双向跳转"),
    ("m3.triple", "M3", "规格 / 公式 / 代码对照", "implemented", "三栏并排，点一处其余两处同步高亮"),
    ("m3.scale", "M3", "规模估算", "implemented", "变量数、0-1 变量数、约束数；三种可开断集合口径并列，机组启停变量单列"),
    ("m3.trial", "M3", "试构建", "implemented", "子进程执行同一份代码（T = 1，不含 N−1），限时 60 秒"),
    ("m3.versions", "M3", "版本管理", "implemented", "规格版本链、差异比对与改动原因"),
    ("m3.ext_dynamic", "M3", "动态建模方法接入", "reserved", "多场景优化规则、建模逻辑、结果验证三段接口，接入后在此页展示"),
    # M4
    ("m4.checks", "M4", "五层校验", "implemented", "规格合法 / 结构一致 / 数据检查 / 可执行 / 语义回译"),
    ("m4.backtrans", "M4", "语义回译", "implemented", "每项修改翻回中文并标注原文依据，查漏查多"),
    ("m4.iis", "M4", "无解诊断", "implemented", "不可行时逐项放开约束，定位冲突来源并给出可放松的项"),
    ("m4.ext_check", "M4", "外部去幻觉校验接入", "reserved", "外部校验结果并入第 5 层"),
    # M5
    ("m5.solve", "M5", "求解（黑盒）", "blackbox", "内置 HiGHS 直流近似 OTS 可真实求解；可切换 mock / 导入结果 / 外部命令；不做求解加速"),
    ("m5.import", "M5", "结果导入", "implemented", "上传结果 JSON，按 result_schema.json 校验"),
    ("m5.commercial", "M5", "商业求解器选项", "reserved", "COPT / Gurobi：规格里可选，经外部命令接入"),
    ("m5.external", "M5", "外部求解链", "reserved", "SOLVER_CMD 命令适配，可挂 IPOPT 热启动链路"),
    ("m5.benchmark", "M5", "交流基准结果", "implemented", "16 时段完整交流 OTS（MATPOWER）计算结果，只读展示"),
    # M6
    ("m6.matrix", "M6", "开断矩阵", "implemented", "时段 × 支路，断开格子着色"),
    ("m6.gen", "M6", "机组出力与启停", "implemented", "出力曲线、启停状态，越界标红"),
    ("m6.topo", "M6", "拓扑网架图", "implemented", "905 节点 / 1000 支路，按电压等级与负载率着色"),
    ("m6.compare", "M6", "调整前后对比", "implemented", "调整前与调整后并排，只列差异项"),
    ("m6.geomap", "M6", "地图", "implemented", "行政区划底图叠加网架、开断线路与重载线路；变电站落点为按拓扑分区的示意位置"),
    ("m6.writeback", "M6", "结果回写测点", "implemented", "开断方案映射为虚拟开关动作清单"),
    # M7
    ("m7.loadrate", "M7", "负载率指标", "implemented", "最大值、平均值、≥80%、≥100% 条数"),
    ("m7.voltage", "M7", "电压偏移指标", "implemented", "最大值、平均值、越限母线数"),
    ("m7.n1", "M7", "N−1 通过率（直流筛查）", "implemented", "PTDF / LODF 筛查；事故前已过载的支路单列"),
    ("m7.vsm", "M7", "静态电压稳定裕度", "todo", "需要连续潮流"),
    ("m7.renewable", "M7", "新能源消纳率", "todo", "需要断面标明新能源机组"),
    ("m7.risk", "M7", "课题 3 风险评估", "reserved", "配置 RISK_ENDPOINT 后调用；未配置时用本地规则模拟"),
    ("m7.negotiate", "M7", "协商调整", "implemented", "风险超标时生成待确认的调整建议，形成新版本回到规格确认"),
    ("m7.branch", "M7", "建模后先协商", "implemented", "建模完成后可先进入风险评估与协商，再决定是否求解"),
    ("m7.reward", "M7", "Reward 反馈", "reserved", "风险等级折算奖励，接口预留"),
    # M8
    ("m8.testmode", "M8", "测评模式", "implemented", "批量导入测试集，按 L1–L4 统计准确率与幻觉数，导出报告"),
    ("m8.objective", "M8", "目标值比对测评", "todo", "以求解目标值判对错"),
    # M9
    ("m9.classify", "M9", "问题类型识别", "implemented", "由规格推出问题类型与分解策略"),
    ("m9.node_agg", "M9", "节点聚合", "implemented", "低压叶子节点并入上级节点，给出聚合前后规模"),
    ("m9.time_agg", "M9", "时空聚合", "implemented", "时段方向按组合并为决策段"),
    ("m9.partition", "M9", "区域分解与联络线", "implemented", "按县域分区，统计区域规模与联络线"),
    ("m9.knowledge", "M9", "知识增强的问题分解", "todo", "建模规则与调度规程知识库"),
    ("m9.multiagent", "M9", "多智能体协同求解", "todo", "子问题智能体、边端协同、全局收敛"),
    # M10
    ("m10.cmdp", "M10", "OTS → CMDP 表述", "implemented", "状态、动作、奖励、安全代价的结构化描述与规模"),
    ("m10.rl", "M10", "安全强化学习训练", "todo", "待接入训练与仿真环境"),
    # 跨课题
    ("x.t2", "X", "课题 2 接口区", "implemented", "测点数据、大模型入口、方案回写三条数据流"),
    ("x.t3", "X", "课题 3 接口区", "implemented", "风险评估、协商、reward 三条数据流"),
    ("host.embed", "X", "宿主平台嵌入", "reserved", "/embed/workbench 可 iframe 嵌入；风格与账号待对接"),
]


def feature_table() -> list[dict]:
    return [
        {"id": i, "module": m, "module_name": MODULES[m], "name": n, "status": s, "status_label": STATUS_LABEL[s], "note": note}
        for i, m, n, s, note in _F
    ]


def feature_response() -> dict:
    return {"status_labels": STATUS_LABEL, "modules": MODULES, "features": feature_table()}

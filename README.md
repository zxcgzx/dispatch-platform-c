# 运行方式智能调整平台C（课题 4 · 建模工作台）

调度员输入一句话 → 自动判定 L1–L4 → 生成结构化模型规格 → 公式与代码逐项确认 → 五层校验、去幻觉 → 求解 → 结果与大理地图 → 指标与风险评估 → 协商调整出新一版规格。

重点是“**指令 → 建模 → 方程确认 → 校验**”。求解用内置的 HiGHS（直流近似 OTS）真实求出开断方案，也可以切到 mock、导入结果，或用外部命令接现有的 905 节点求解链；**不做任何求解加速、调参、热启动**。

## 运行

只需要 Python ≥ 3.10，不需要 Node（前端已构建在 `backend/app/static/`）。在 `keti4-workbench/` 目录下：

**Windows**

```bash
pip install -r backend/requirements.txt
python run.py
```

**macOS / Linux**

```bash
pip3 install -r backend/requirements.txt
python3 run.py
```

浏览器会自动打开 <http://localhost:8000>（`--no-browser` 不自动打开，`--port 8010` 换端口）。断网也能完整使用：默认用离线的演示规则引擎，字体、地图底图、图表库都随包打包。

## 怎么演示

1. 首页点任意一张**场景卡片**（例如“高温限额下降 · 少动开关”），系统自动走完 建模 → 校验 → 求解 → 评估，直接停在结果页。
2. 结果页依次看：**开断方案**（求解器选了哪条线断开）、**机组出力调整**、**大理地图**（开断线路红色虚线）、**潮流变化**、**回写测点**（映射成虚拟开关动作）。
3. 点“风险评估”：负载率、电压偏移、N−1 直流筛查、风险等级；风险为“高”时勾选建议、填数值，生成新版本回到规格确认。
4. 想看细节：在“规格确认”页的标签里有**公式**（受影响的块高亮）、**代码**（带标记，和规格行双向跳转）、**校验**（五层亮灯，点一条定位到规格行）。
5. 也可以在首页下方直接输入自己的指令；系统有不确定的地方会追问。

五个演示场景：负荷增长（L1）、线路检修停运（L1）、高温限额下降 · 少动开关（L4）、开关次数限制（L3）、机组出力受限（L2）。

## 页面

| 页面 | 内容 |
| --- | --- |
| 建模工作台 | 首页场景卡片 + 七步向导；左栏对话与追问，右栏随步骤切换，底栏版本链与运行日志 |
| 地图 | 大理白族自治州真实行政区划（12 个县市）为底图，叠加 905 节点网架；可叠加某个任务的方案 |
| 测点转换 | 节点 → 模拟测点的构造、静态 / 动态表、测点 → 节点逆向恢复与往返验证、方案回写 |
| 测评模式 | 导入测试集（JSON / CSV），批量跑 解析 → 判级 → 校验，按层级统计，导出报告 |
| 问题分解与多智能体 | 任务 2、任务 4 的占位页（待开发） |
| 数据与接口 | 断面库、数据事实与质量、外部接口、名称↔编号登记表、知识表 |
| 功能清单 | 按 M1–M9 列出全部功能与状态 |
| `/embed/workbench` | 隐藏顶部导航，便于 iframe 嵌入宿主平台 |

## 数据口径

- **一个断面 = 一个时段**。当前数据库只有一个断面文件，所以建模按单时段进行；放入多个不同时刻的断面后，按时刻组成多时段滚动窗口（最多 16 个，每个间隔 15 分钟）。
- 断面文件在 `data/snapshots/`，只读，不会被修改。

## 测点转换（课题 2）

按怀柔实验室的构造机制，把节点模型转成模拟测点：每个母线 → 母线测点；每条线路两端各插入一个虚拟开关，原线路参数放在两个开关之间；变压器（变比 ≠ 0）中间是变压器测点；发电机、负荷不建独立测点，信息挂在边界开关上。输出静态 / 动态两组表，按母线、变压器、开关、连接线路四类对象组织。

逆向恢复需要映射表：905 节点里有 61 个母线挂了多台机组、67 组平行支路，没有映射表就无法无损恢复。真实测点的接入还需要课题 2 提供映射、单位字典与标识范围。

## 配置

复制 `.env.example` 为 `.env`：

| 变量 | 含义 |
| --- | --- |
| `LLM_MODE` | `demo`（离线规则引擎，默认）或 `openai`（OpenAI 兼容接口，本地 Qwen 用 vLLM 起服务）。连不上自动回落并提示 |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | 大模型服务地址、模型名、密钥 |
| `METHOD_ENDPOINT` | 动态建模与去幻觉方法（`/parse`、`/check`）。空 = 未接入 |
| `RISK_ENDPOINT` | 课题 3 风险评估。空 = 本地规则 |
| `SOLVER_MODE` | `builtin`（内置 HiGHS，默认）/ `mock` / `import` / `external` |
| `SOLVER_CMD` | external 模式的命令，占位符 `{spec}` `{dir}` `{out}` |
| `SNAPSHOT_DIR` | 断面目录，默认 `./data/snapshots` |

`config/app.yaml`（阈值、数值范围、事故集与可开断集合规则）、`config/knowledge.yaml`（推断知识表）、`config/operators.yaml`（结构算子与公式）可直接改，重启后端生效。

接入现有求解链：`SOLVER_MODE=external`，`SOLVER_CMD` 指向求解脚本，脚本读 `--spec`、把结果按 `backend/app/solver/result_schema.json` 写到 `--out`。

## 开发与测试

```bash
cd backend && uvicorn app.main:app --reload --port 8000      # 后端
cd frontend && npm install && npm run dev                    # 前端（http://localhost:5173，/api 代理到 8000）
cd frontend && npm run build                                 # 构建到 backend/app/static/
python -m pytest backend/tests -q                            # 后端测试
node scripts/e2e_demo.mjs                                    # 浏览器端到端（需先 python run.py），截图存到 docs/screenshots/
```

改了 `backend/app/spec/schema.py` 后：`python backend/app/spec/export_schema.py && cd frontend && npm run gen:types`。改了 `backend/app/features.py` 后：`python scripts/gen_features.py`。

## 目录

```text
run.py                  一条命令启动
backend/app/
  data/                 断面解析、断面库、对象编号、数据事实、拓扑与孤岛、坐标与地理落点
  spec/                 规格 schema、判级、参数白名单、版本差异
  modeling/             建模引擎（demo / openai / external）、公式、代码生成、规模估算、试构建
  checks/               五层校验
  solver/               内置 HiGHS 求解（dcots.py）、mock / import / external、result_schema.json
  metrics/              负载率、电压偏移、N−1 直流筛查、风险、协商建议
  measure/              测点 ↔ 节点转换
  testmode/             测评
  storage/ api/ integrations/
frontend/src/           views/ components/ stores/ styles/tokens.css features.ts
frontend/public/geo/    大理州行政区划 GeoJSON
config/  data/  docs/  scripts/  runs/
```

更多假设与限制见 [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md)。

## 交流基准（MATLAB 计算结果）

「交流基准」页展示 `905节点计算/` 里 v1.3 的 16 时段完整非线性交流 OTS 结果（MATPOWER 8 MIPS，240 次交流 OPF、16 次静态 N−1）：全程开断 L151，4 小时目标 1173.91 $（不开断 1174.64 $），总用时 940 s，并附 E0–E4 热启动对比。
只读展示，不在平台内重算。重新生成：`python scripts/import_matlab_benchmark.py "<dali_matlab_v1.3 目录>"`，输出 `backend/app/data/benchmarks/ots905_v1.3.json`（约 24 KB，不拷贝原始 121 MB）。
说明：MATLAB 算例对原始断面做了机组合并、负的 PD 置零等处理，数值与平台内置直流求解不可逐项对比；`OTS905_IPOPT_v0.6_fast60_update.zip` 只含代码更新、没有 905 节点基准数据，未接入。

## 地图

默认用纯 SVG 绘制（不依赖 canvas），页内「简易绘制」开关可切到 ECharts 版（可缩放拖动）；ECharts 绘制出错时自动退回 SVG。

## Logo 来源

南方电网：zh.wikipedia 矢量图；北京大学校徽：Wikimedia Commons 官方 VIS 矢量；北大字标、怀柔实验室：由 `三家Logo.png` 经 `scripts/make_logos.py` 描摹成矢量。

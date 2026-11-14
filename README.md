# 运行方式智能调整平台C

调度员输入一句话 → 自动判定 L1–L4 → 生成结构化模型规格 → 规格 / 公式 / 代码三栏确认 → 五层校验与去幻觉 → 求解 → 结果与地图 → 指标与风险评估 → 协商调整出新一版规格。

重点是“**指令 → 建模 → 方程确认 → 校验**”。求解作为黑盒：内置 HiGHS 可直接求解直流近似 OTS，也可切到 mock、导入结果，或用外部命令接 IPOPT / COPT / Gurobi 等求解链；**不做任何求解加速、调参、热启动**。

## 运行

只需要 Python ≥ 3.10，不需要 Node（前端已构建在 `backend/app/static/`）。

```bash
pip install -r requirements.txt
python run.py
```

浏览器自动打开 <http://localhost:8000>（`--no-browser` 不自动打开，`--port 8010` 换端口）。断网也能完整使用：默认离线规则引擎，字体、地图底图、图表库都随包打包。

## 怎么演示

1. 首页点任意一张**场景卡片**（L1–L4 各有示例，另有机组启停），系统自动走完 建模 → 校验 → 求解 → 评估，停在结果页；也可以用页内的指令构建器选对象、动作、约束、目标，拼出一句指令。
2. 结果页：**开断方案**、**机组出力调整**、**机组启停**、**电网地图**（开断线路红色虚线）、**潮流变化**、**回写测点**。
3. 规格确认页的标签：**规格**、**三栏对照**（规格 / 公式 / 代码并排，点一处同步高亮）、**动态建模**（切换 AC-OTS / AC-OPF，叠加机组建模与各类目标）、**公式**、**代码**、**校验**。
4. 求解不可行时点“定位冲突约束”，列出冲突来源与可放松的项。
5. 建模完成后可点“先协商，不求解”直接进入风险评估与协商；风险评估页可切 Reward，查看 CMDP 描述。

## 页面

| 页面 | 内容 |
| --- | --- |
| 建模工作台 | 首页场景卡片与指令构建器 + 七步向导：指令输入、层级判定、规格确认、去幻觉校验、求解、结果与地图、风险评估 |
| 地图 | 行政区划底图叠加 905 节点网架；可叠加某个任务的方案 |
| 跨课题接口 | 课题 2（测点数据、大模型、方案回写）与课题 3（风险评估、协商、reward）的数据流向与状态 |
| 交流基准 | 16 时段完整交流 OTS（MATPOWER）计算结果，只读展示 |
| 测点转换 | 节点 → 模拟测点、静态 / 动态表、逆向恢复与往返验证、方案回写 |
| 测评模式 | 导入测试集（JSON / CSV），批量跑 解析 → 判级 → 校验，按层级统计，导出报告 |
| 聚合与分解 | 问题类型识别、节点聚合、时段聚合、按县域分区与联络线 |
| 数据与接口 | 断面库、数据事实与质量、外部接口、名称↔编号登记表、知识表 |
| 功能清单 | 全部功能与状态：已实现 / 黑盒 / 接口预留 / 待开发 |
| `/embed/workbench` | 隐藏顶部导航，便于 iframe 嵌入宿主平台 |

口径、算子库、校验与指标的定义见 [docs/DESIGN.md](docs/DESIGN.md)。

## 配置

复制 `.env.example` 为 `.env`：

| 变量 | 含义 |
| --- | --- |
| `LLM_MODE` | `demo`（离线规则引擎，默认）或 `openai`（OpenAI 兼容接口，本地小模型用 vLLM 起服务）。连不上自动回落并提示 |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | 大模型服务地址、模型名、密钥 |
| `METHOD_ENDPOINT` | 动态建模与去幻觉方法（`/parse`、`/check`）。空 = 未接入 |
| `RISK_ENDPOINT` | 课题 3 风险评估。空 = 本地规则 |
| `SOLVER_MODE` | `builtin`（内置 HiGHS，默认）/ `mock` / `import` / `external` |
| `SOLVER_CMD` | external 模式的命令，占位符 `{spec}` `{dir}` `{out}` |
| `SNAPSHOT_DIR` | 断面目录，默认 `./data/snapshots` |

`config/app.yaml`（阈值、数值范围、事故集与可开断集合规则）、`config/knowledge.yaml`（推断知识表与关键词）、`config/operators.yaml`（结构算子与公式）可直接改，重启后端生效。

接入现有求解链：`SOLVER_MODE=external`，`SOLVER_CMD` 指向求解脚本，脚本读 `--spec`、把结果按 `backend/app/solver/result_schema.json` 写到 `--out`。

## 交流基准

「交流基准」页展示 16 时段完整非线性交流 OTS（MATLAB + MATPOWER 8 MIPS）的计算结果：240 次交流 OPF、16 次静态 N−1，全程开断 L151，4 小时目标 1173.91 $（不开断 1174.64 $），总用时 940 s，并附热启动对比。只读展示，不在平台内重算。重新生成：

```bash
python scripts/import_matlab_benchmark.py "<dali_matlab_v1.3 目录>"
```

输出 `backend/app/data/benchmarks/ots905_v1.3.json`（约 24 KB）。

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
  data/                 断面解析、断面库、对象编号、数据事实、拓扑与孤岛、地理落点、交流基准
  spec/                 规格 schema、判级、参数白名单、版本差异
  modeling/             建模引擎（demo / openai / external）、公式、代码生成、规模估算、试构建
  checks/               五层校验
  solver/               内置 HiGHS 求解、mock / import / external、result_schema.json
  metrics/              负载率、电压偏移、N−1 直流筛查、风险、协商建议
  analysis/             无解诊断、CMDP 描述、聚合与分解
  measure/              测点 ↔ 节点转换
  testmode/             测评
  storage/ api/ integrations/
frontend/src/           views/ components/ stores/ styles/ features.ts
config/  data/  docs/  scripts/
```

## 品牌标识

南方电网、北京大学校徽为官方矢量图；北大字标与怀柔实验室标识由提供的图片按颜色分层描摹为矢量（`scripts/make_logos.py`）。

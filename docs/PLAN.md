# 实现计划（PLAN）

依据：`建模工作台_ClaudeCode开发指令.md`（下称“指令”）第 13 节。本页只写一页：做什么、按什么顺序、怎么验。

## 1. 主线

调度员自然语言 → 解析与判级（L1–L4）→ 模型规格（ω、Δπ、s、R）→ 公式 / 代码逐项确认 → 五层校验 → 求解（黑盒）→ 结果与网架图 → 指标与风险 → 协商式调整出新版本。
求解只做 mock / 导入 / 外部命令三种适配，不做任何求解加速。

## 2. 架构要点

- **规格是唯一中间产物**：`backend/app/spec/schema.py`（Pydantic v2）→ 导出 JSON Schema → 前端 `json2ts` 生成类型。
- **判级由程序推出**（`spec/level.py`），不信任大模型自报。
- **三个建模引擎**：`DemoRuleEngine`（离线，保证 D1–D10）、`OpenAICompatEngine`（连不上自动回落）、`ExternalMethodEngine`（接口预留）。
- **去幻觉三件套**：evidence 必须是原文子串（W501）、对象必须存在（E101，绝不替换）、覆盖检查（W502）。第 5 层用与引擎无关的 `spec/extract.py` 独立抽取，才能查出大模型的遗漏。
- **代码页的代码就是试构建执行的代码**：`modeling/codegen.py` 生成 `model.py`，`modeling/trial.py` 在子进程里 `exec` 同一份文件（T = 1，跳过 B9）。
- **状态唯一来源**：`backend/app/features.py` 同源输出 `/api/features`，前端 `src/features.ts` 启动时从接口取，兜底内置同一份。
- **离线**：KaTeX 字体、ECharts、Element Plus 全部随包打包；`npm run build` 输出到 `backend/app/static/` 并随仓库提交。
- **样式**：颜色/字号/间距全走 `src/styles/tokens.css`。

## 3. 里程碑（对应指令第 13 节）

| # | 内容 | 验收 |
| --- | --- | --- |
| M1 | 工程骨架、断面解析、对象编号、数据事实与质量、孤岛型识别、布局缓存；前端导航 / 空工作台 / 七步条 / 功能清单 / 数据与接口 | pytest 核对 4.4 全部数字；`python run.py` 能开页面 |
| M2 | schema、判级、白名单、算子库、演示规则引擎、公式、代码生成、规模估算、五层校验 | pytest 覆盖 D1–D10 |
| M3 | 工作台步骤 1–4：追问、四宫格、推断链、规格编辑、公式/代码联动、校验定位、版本 | 浏览器走 D1/D3/D8 |
| M4 | 求解黑盒三模式、结果页、指标 + N−1 直流筛查、课题 3 模拟、协商调整、版本差异 | 导入结果 JSON 能看；mock 无伪造 |
| M5 | 测评模式、M9 占位页、嵌入路由、README；Playwright 按 D7 走七步并截图 | 验收清单逐项勾 |

每个里程碑末：`pytest` + `npm run build`；工作目录不是 git 仓库，故不提交（记入 ASSUMPTIONS）。

## 4. 不做

求解加速 / 调参 / 热启动；真实 AC-OTS 求解；地理地图；课题 2、3 与动态建模与去幻觉方法的真实对接；登录与权限。

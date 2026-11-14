// 完整演示流程验证：首页点场景卡片 → 一键 建模/校验/求解/评估 → 结果页（开断矩阵、机组调整、地图）→ 风险页 → 协商调整 → 新版本。
// 用法：先 python run.py，再 node scripts/e2e_demo.mjs；截图存到 docs/screenshots/。
import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://localhost:8000'
const OUT = 'docs/screenshots'
fs.mkdirSync(OUT, { recursive: true })
const exe = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome', '/usr/bin/chromium'].find((p) => fs.existsSync(p))
const browser = await chromium.launch({ executablePath: exe, headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } })
const errs = []
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message))
page.on('console', (m) => m.type() === 'error' && errs.push('console: ' + m.text()))
page.on('requestfailed', (r) => errs.push('reqfail: ' + r.url()))
page.on('request', (r) => { if (!r.url().startsWith(BASE) && !/^(data|blob):/.test(r.url())) errs.push('外部请求: ' + r.url()) })
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` })
let k = 0
const ok = (m) => console.log(`✓ ${++k}. ${m}`)
const must = (c, m) => { if (!c) throw new Error('验收失败：' + m) }

await page.goto(BASE + '/workbench')
await page.waitForSelector('[data-testid=scenarios]')
must(await page.$('[data-testid=logos] img[alt="北京大学"]') && await page.$('[data-testid=logos] img[alt="中国南方电网"]') && await page.$('[data-testid=logos] img[alt="怀柔实验室"]'), '页头应有三家 Logo')
must(!(await page.content()).includes('铮昊'), '页面里不应出现“铮昊”')
await shot('01_home')
ok('首页：品牌页头（三家 Logo）+ 五个演示场景卡片')

// ---- 场景：高温限额下降 · 少动开关（L4：推断 + 结构修改）
await page.click('[data-scenario=heat]')
await page.waitForSelector('[data-testid=result-panel]', { timeout: 120000 })
ok('一键演示：L4 场景从指令一路跑到结果页（建模 → 校验 → 求解 → 评估）')
await page.waitForSelector('[data-testid=switch-list]', { timeout: 30000 })
const opened = await page.$$eval('[data-testid=switch-list] tbody tr', (r) => r.map((x) => x.getAttribute('data-open')))
must(opened.length >= 1, '开断方案里应有被开断的支路')
must(Number(await page.textContent('[data-testid=n-open]')) === opened.length, '摘要里的开断数应与清单一致')
await shot('02_result_plan')
ok(`结果：求解器选择开断 ${opened.join('、')}（真实求解结果）`)

await page.click('.el-tabs__item:has-text("电网地图")')
await page.waitForSelector('[data-testid=map-svg] path', { timeout: 20000 })
await page.waitForTimeout(2800)
await shot('03_result_map')
ok('结果：电网地图叠加方案，开断线路红色虚线')

await page.click('.el-tabs__item:has-text("机组出力调整")')
await page.waitForTimeout(400)
await shot('04_gen_adjust')
ok('机组出力调整：前后对比')

await page.click('.el-tabs__item:has-text("回写测点")')
await page.waitForSelector('[data-testid=wb-table]')
must((await page.$$('[data-testid=wb-table] tbody tr')).length >= 2, '回写应给出两端开关动作')
ok('回写测点：开断支路映射为两端虚拟开关动作')

await page.click('[data-step="7"]')
await page.waitForSelector('[data-testid=risk-panel]')
await page.waitForSelector('[data-testid=risk-level]')
const lvl = (await page.textContent('[data-testid=risk-level]')).trim()
must(/高|中|低/.test(lvl), '应有风险等级')
await shot('05_risk')
ok(`风险评估：${lvl}；指标卡片、N−1 直流筛查`)

// 协商调整
const sids = await page.$$eval('.sg', (e) => e.map((x) => x.getAttribute('data-sid')))
if (sids.length) {
  await page.click(`[data-testid="pick-${sids[0]}"]`)
  for (const i of await page.$$('.fields input')) await i.fill((await i.getAttribute('placeholder')) === 'L428,L429' ? 'L875,L877' : '300')
  await page.click('[data-testid=adjust-btn]')
  await page.waitForSelector('[data-testid=spec-editor]', { timeout: 20000 })
  await shot('06_negotiated_spec')
  ok('协商调整：勾选建议、填数值，生成 v2 草稿回到规格确认')
}

// 其它页面
for (const [path, sel, name, label] of [
  ['/map', '[data-testid=map-svg] path', '07_map', '地图'],
  ['/measure', '[data-testid=measure-kpis]', '08_measure', '测点转换'],
  ['/features', '[data-testid=feature-summary]', '09_features', '功能清单'],
  ['/data', '[data-testid=facts-card]', '10_data', '数据与接口'],
  ['/decompose', '[data-testid=m9-card]', '11_decompose', '问题分解与多智能体'],
]) {
  await page.goto(BASE + path)
  await page.waitForSelector(sel, { timeout: 20000 })
  await page.waitForTimeout(path === '/map' ? 2500 : 600)
  if (path === '/measure') {
    await page.click('[data-testid=run-roundtrip]')
    await page.waitForSelector('[data-testid=roundtrip-result]')
  }
  await shot(name)
  ok(label)
}

await page.goto(BASE + '/testmode')
await page.click('[data-testid=run-set]')
await page.waitForSelector('[data-testid=report-cards]', { timeout: 60000 })
await page.waitForTimeout(500)
await shot('12_testmode')
ok('测评模式：内置 D1–D10 报告')

await page.goto(BASE + '/embed/workbench')
await page.waitForSelector('[data-testid=workbench]')
must(!(await page.$('header.nav')), '嵌入路由应隐藏顶部导航')
ok('嵌入路由')

console.log('前端错误 / 外部请求：', errs.length ? errs : '无')
await browser.close()
if (errs.length) process.exit(1)

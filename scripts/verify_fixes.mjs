// 本轮四项修改的浏览器验证：南网 Logo、地图加载（多种进入方式 + 失败重试）、功能清单无旧名称、指令构建器。
import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://localhost:8000'
const OUT = 'docs/screenshots'
const exe = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome'].find((p) => fs.existsSync(p))
const browser = await chromium.launch({ executablePath: exe, headless: true })
const errs = []
async function newPage(vp = { width: 1680, height: 1000 }) {
  const p = await browser.newPage({ viewport: vp })
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message))
  p.on('console', (m) => m.type() === 'error' && errs.push('console: ' + m.text()))
  p.on('requestfailed', (r) => errs.push('reqfail: ' + r.url()))
  p.on('request', (r) => { if (!r.url().startsWith(BASE) && !/^(data|blob):/.test(r.url())) errs.push('外部请求: ' + r.url()) })
  return p
}
const must = (c, m) => { if (!c) throw new Error('验收失败：' + m); console.log('✓', m) }

// 1. Logo
let p = await newPage()
await p.goto(BASE + '/workbench'); await p.waitForSelector('[data-testid=logos]'); await p.waitForTimeout(600)
const sizes = await p.$$eval('[data-testid=logos] img', (i) => i.map((x) => ({ alt: x.alt, nw: x.naturalWidth, w: x.clientWidth, h: x.clientHeight, src: x.getAttribute('src') })))
const csg = sizes.find((s) => s.alt === '中国南方电网')
must(csg && /\.svg/.test(csg.src) && csg.nw > 0, `南网 Logo 使用矢量 SVG（${csg?.src}）`)
must(sizes.every((s) => s.w > 40 && s.h > 20), '三家 Logo 都已渲染')
await p.close()

// 2. 地图：直接打开 / 从别的页面点进来 / 结果页里的标签 / 窄屏 / 失败重试
async function mapOk(page, tag) {
  await page.waitForSelector('[data-testid=map-svg] path', { timeout: 20000 })
  await page.waitForFunction(() => !document.querySelector('.loading'), null, { timeout: 20000 })
  const n = await page.$$eval('[data-testid=map-svg] path', (c) => c.length)
  const pts = await page.$$eval('[data-testid=map-svg] circle', (c) => c.length)
  must(n >= 12 && pts > 50, `${tag}：地图已渲染（${n} 个县区、${pts} 个站点）`)
}
p = await newPage()
await p.goto(BASE + '/map'); await mapOk(p, '直接打开 /map')
await p.screenshot({ path: `${OUT}/07_map.png` })
await p.click('a:has-text("测点转换")'); await p.waitForSelector('[data-testid=measure-kpis]')
await p.click('a:has-text("地图")'); await mapOk(p, '从其它页面点进地图')
await p.reload(); await mapOk(p, '刷新后')
await p.setViewportSize({ width: 1100, height: 800 }); await p.waitForTimeout(800)
must((await p.$eval('[data-testid=map-svg]', (c) => c.clientWidth)) > 200, '窄屏缩放后地图仍在')
await p.close()

// 重试：先让 /api/geo/boundary 失败，再恢复
p = await newPage()
let fail = true
await p.route('**/api/geo/boundary', (r) => (fail ? r.abort() : r.continue()))
await p.goto(BASE + '/map')
await p.waitForSelector('[data-testid=map-retry]', { timeout: 15000 })
must(true, '加载失败时显示错误与“重试”按钮（不是一直转圈）')
fail = false
await p.click('[data-testid=map-retry]'); await mapOk(p, '点“重试”后')
await p.close()

// 结果页里的地图标签
p = await newPage()
await p.goto(BASE + '/workbench'); await p.waitForSelector('[data-scenario=outage]')
await p.click('[data-scenario=outage]'); await p.waitForSelector('[data-testid=result-panel]', { timeout: 120000 })
await p.click('.el-tabs__item:has-text("电网地图")'); await mapOk(p, '结果页内的电网地图标签')
await p.close()

// 3. 功能清单
p = await newPage()
await p.goto(BASE + '/features'); await p.waitForSelector('[data-testid=feature-summary]')
const html = await p.content()
for (const w of ['铮昊', '方法组']) must(!html.includes(w), `功能清单页没有“${w}”`)
const names = await p.$$eval('[data-feature]', (r) => r.map((x) => x.textContent.replace(/\s+/g, ' ')))
must(names.some((n) => n.includes('外部动态建模引擎接入')) && names.some((n) => n.includes('外部去幻觉校验接入')), '功能清单里是中性名称')
await p.screenshot({ path: `${OUT}/09_features.png` })
await p.goto(BASE + '/data'); await p.waitForSelector('[data-testid=facts-card]')
await p.click('.el-tabs__item:has-text("外部接口")')
must(!(await p.content()).includes('铮昊'), '数据与接口页没有“铮昊”')
await p.goto(BASE + '/workbench'); await p.waitForSelector('[data-testid=lamps]')
must(!(await p.content()).includes('铮昊'), '工作台页头没有“铮昊”')
await p.close()

// 4. 指令构建器
p = await newPage()
await p.goto(BASE + '/workbench'); await p.waitForSelector('[data-testid=builder]')
await p.screenshot({ path: `${OUT}/01_home.png` })
await p.click('[data-action=heat]')
await p.click('[data-testid=b-target]')
await p.click('.el-select-dropdown__item:has-text("L875")')
await p.click('[data-testid=b-n1] , label:has-text("满足 N−1")')
await p.click('label:has-text("尽量少动开关")')
let prev = await p.textContent('[data-testid=b-preview]')
must(prev.includes('L875') && prev.includes('热稳限额下降') && prev.includes('N−1') && prev.includes('尽量少动开关'), `构建器拼出指令：${prev.trim()}`)
await p.click('[data-testid=b-fill]')
must((await p.inputValue('input[data-testid=instruction-input]')) === prev.trim(), '“填入输入框”把指令放进输入框，可继续手改')
await p.screenshot({ path: `${OUT}/01b_builder.png` })
await p.click('[data-testid=b-run]')
await p.waitForSelector('[data-testid=ask-value]', { timeout: 20000 })
must(true, '“生成并解析”后进入解析与追问（推断项幅度另问）')
await p.close()

p = await newPage()
await p.goto(BASE + '/workbench'); await p.waitForSelector('[data-testid=builder]')
await p.click('label:has-text("母线")')
await p.click('[data-testid=b-target]'); await p.click('.el-select-dropdown__item:has-text("B43")')
await p.click('[data-action=pd_up]')
prev = await p.textContent('[data-testid=b-preview]')
must(prev.trim() === '母线 43 的有功负荷提高 20%。', `母线动作拼句：${prev.trim()}`)
await p.click('[data-testid=b-run]')
await p.waitForSelector('[data-testid=level-panel]', { timeout: 20000 })
must((await p.textContent('[data-testid=level-tag]')).trim() === 'L1', '拼出的指令被正确解析为 L1')
await p.close()

console.log('前端错误 / 外部请求：', errs.length ? errs : '无')
await browser.close()
if (errs.length) process.exit(1)

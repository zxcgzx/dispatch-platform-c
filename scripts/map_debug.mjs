// 复现地图加载：打开 /map 与 工作台结果页里的地图，打印控制台、网络失败和 canvas 状态。
import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
const exe = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p))
const b = await chromium.launch({ executablePath: exe, headless: true })
const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })
p.on('pageerror', (e) => console.log('PAGEERROR', e.message))
p.on('console', (m) => ['error', 'warning'].includes(m.type()) && console.log('CONSOLE', m.type(), m.text()))
p.on('response', (r) => r.url().includes('/api/') && console.log('API', r.status(), r.url().replace('http://localhost:8000', ''), r.headers()['content-length'] || ''))
await p.goto('http://localhost:8000/map')
await p.waitForTimeout(6000)
console.log('canvas:', await p.$$eval('[data-testid=map-canvas] canvas', (c) => c.map((x) => `${x.width}x${x.height}`)))
console.log('loading text visible:', await p.$eval('.loading', (e) => e.textContent).catch(() => 'none'))
await p.screenshot({ path: '.scratch/map_dbg.png' })
await b.close()

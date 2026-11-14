// node scripts/shot.mjs <url> <out.png> [等待选择器] [等待毫秒]
import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
const [url, out, sel, wait] = process.argv.slice(2)
const exe = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p))
const b = await chromium.launch({ executablePath: exe, headless: true })
const p = await b.newPage({ viewport: { width: 1680, height: 1000 } })
const errs = []
p.on('pageerror', (e) => errs.push('pageerror: ' + e.message))
p.on('console', (m) => m.type() === 'error' && errs.push('console: ' + m.text()))
p.on('requestfailed', (r) => errs.push('reqfail: ' + r.url()))
await p.goto(url)
if (sel) await p.waitForSelector(sel, { timeout: 20000 })
await p.waitForTimeout(Number(wait || 1200))
await p.screenshot({ path: out })
console.log(errs.length ? errs.join('\n') : 'no errors')
await b.close()

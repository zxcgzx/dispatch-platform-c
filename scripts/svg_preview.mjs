// 把 frontend/src/assets 里的 logo 并排渲染成大图，检查质量。
// 用法：node scripts/svg_preview.mjs <out.png> <a.svg> [b.svg ...]
import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const [out, ...files] = process.argv.slice(2)
const exe = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p))
const url = (f) => pathToFileURL(path.resolve('frontend/src/assets', f)).href
const small = files.map((f) => `<img src="${url(f)}" style="height:60px;margin-right:30px">`).join('')
const big = files.map((f) => `<img src="${url(f)}" style="height:240px;margin-right:30px">`).join('')
const html = path.resolve('.scratch', 'svg_preview.html')
fs.mkdirSync(path.dirname(html), { recursive: true })
fs.writeFileSync(html, `<!doctype html><meta charset="utf-8"><body style="margin:20px;background:#f3f5f9">${small}<br><br>${big}</body>`)
const b = await chromium.launch({ executablePath: exe, headless: true })
const p = await b.newPage({ viewport: { width: 1500, height: 700 }, deviceScaleFactor: 2 })
await p.goto(pathToFileURL(html).href)
await p.waitForTimeout(800)
await p.screenshot({ path: out })
await b.close()

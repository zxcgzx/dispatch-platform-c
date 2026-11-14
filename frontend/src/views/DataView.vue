<script setup lang="ts">
// 数据与接口：断面库、数据事实与质量、课题 2 测点数据预览、名称↔编号登记表、外部接口说明、知识表。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'

const app = useAppStore()
const summary = ref<any>(null)
const registry = ref<{ columns: string[]; rows: string[][] }>({ columns: [], rows: [] })
const cfg = ref<any>(null)
const preview = ref<any>(null)
const tab = ref('facts')

onMounted(async () => {
  await app.init()
  if (app.defaultSnapshot) summary.value = await api.get(`/snapshots/${app.defaultSnapshot}/summary`)
  registry.value = await api.get('/name-registry')
  cfg.value = await api.get('/config')
})

const facts = computed(() => summary.value?.facts)
const levelText: Record<string, string> = { warn: '警告', info: '提示', error: '错误' }

async function onUpload(ev: Event) {
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  try {
    preview.value = await api.upload('/measurements/preview', fd)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
const sw = computed(() => facts.value?.switchable_counts ?? {})
</script>

<template>
  <div class="page">
    <h2>数据与接口</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="断面库与数据事实" name="facts">
        <div class="card card-pad" style="margin-bottom: 12px">
          <div class="card-title">断面库</div>
          <table class="table-plain" data-testid="snapshot-table">
            <thead><tr><th>文件</th><th>断面时刻</th><th>来源</th><th>Bus / Gen / Branch</th></tr></thead>
            <tbody>
              <tr v-for="s in app.snapshots" :key="s.id">
                <td class="mono">{{ s.file }}</td>
                <td>{{ s.time || '—' }}</td>
                <td>{{ s.time_source === 'dict' ? 'Dict Info time' : s.time_source === 'filename' ? '文件名' : '—' }}
                  <span v-if="s.time_mismatch" class="lv-warn">（与文件名时间戳不一致）</span></td>
                <td>{{ s.counts ? `${s.counts.bus} / ${s.counts.gen} / ${s.counts.branch}` : s.error }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="app.window?.single_snapshot" class="sub" style="margin-top: 8px">
            断面库只有 1 个文件：按 1 个时段建模；放入多个不同时刻的断面后，按时刻组成多时段窗口。
          </p>
        </div>

        <div v-if="facts" class="grid2">
          <div class="card card-pad" data-testid="facts-card">
            <div class="card-title">数据事实（程序计算）</div>
            <table class="table-plain">
              <tbody>
                <tr><th>规模</th><td>母线 {{ facts.counts.bus }} · 机组 {{ facts.counts.gen }} · 支路 {{ facts.counts.branch }}（baseMVA {{ facts.base_mva }}）</td></tr>
                <tr><th>BUS_TYPE</th><td>PQ {{ facts.bus_types['PQ'] }} · PV {{ facts.bus_types['PV'] }} · 平衡节点 {{ facts.bus_types['平衡节点'] }}（母线 {{ facts.slack_bus.join('、') }}）</td></tr>
                <tr><th>电压等级母线数</th><td><span v-for="(n, k) in facts.bus_by_kv" :key="k" class="chip">{{ k }} {{ n }}</span></td></tr>
                <tr><th>功率合计</th><td>PD ≈ {{ facts.totals.pd_mw }} MW · PG ≈ {{ facts.totals.pg_mw }} MW</td></tr>
                <tr><th>运行状态</th><td>支路全部在运：{{ facts.all_branches_in_service ? '是' : '否' }} · 机组全部在运：{{ facts.all_gens_in_service ? '是' : '否' }} · RENEWABLE 全为 0：{{ facts.renewable_all_zero ? '是（没有新能源机组信息）' : '否' }}</td></tr>
                <tr><th>连通性</th><td>网络{{ facts.connected ? '连通' : '不连通' }}</td></tr>
                <tr><th>孤岛型支路</th><td><b data-testid="n-isolating">{{ facts.isolating_branches }}</b> 条一断开就形成孤岛（是桥且没有并联）</td></tr>
                <tr><th>网状部分</th><td><b data-testid="n-meshed">{{ facts.meshed_branches }}</b> 条（<span v-for="(n, k) in facts.meshed_by_kv" :key="k" class="chip">{{ k }} {{ n }}</span>）</td></tr>
                <tr><th>并联支路</th><td>{{ facts.parallel.groups }} 组，共 {{ facts.parallel.branches }} 条（所以支路主键用行号 L{n}，不能用首末母线）</td></tr>
                <tr><th>多机母线</th><td>{{ facts.buses_with_multiple_gens }} 个母线挂了不止一台机组</td></tr>
                <tr><th>可开断集合口径</th><td>全部在运 {{ sw.all_in_service }} · 网状部分 {{ sw.meshed_in_service }} · 网状且 ≥110kV {{ sw.meshed_kv_ge_110 }}（× 16 时段 = {{ sw.all_in_service * 16 }} / {{ sw.meshed_in_service * 16 }} / {{ sw.meshed_kv_ge_110 * 16 }}）</td></tr>
              </tbody>
            </table>
          </div>
          <div class="card card-pad" data-testid="quality-card">
            <div class="card-title">数据质量</div>
            <table class="table-plain">
              <thead><tr><th>项目</th><th style="width: 60px">数量</th><th>说明 / 示例</th></tr></thead>
              <tbody>
                <tr v-for="q in summary.quality" :key="q.code">
                  <td><span :class="'lv-' + (q.level === 'warn' ? 'warn' : q.level === 'error' ? 'error' : 'info')">[{{ levelText[q.level] }}]</span> {{ q.title }}</td>
                  <td><b>{{ q.count }}</b></td>
                  <td class="sub">{{ q.detail }}<div v-if="q.examples.length" class="mono ex">{{ q.examples.join('、') }}</div></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="外部接口" name="ints">
        <div class="card card-pad">
          <table class="table-plain" data-testid="integration-table">
            <thead><tr><th>接口</th><th>状态</th><th>模式 / 地址</th><th>说明</th><th>请求</th><th>响应</th></tr></thead>
            <tbody>
              <tr v-for="i in app.integrations" :key="i.id">
                <td><b>{{ i.name }}</b><div><StatusBadge :feature="i.feature" small /></div></td>
                <td><span class="row"><i class="dot" :class="i.state" />{{ i.state_label }}</span></td>
                <td>{{ i.mode }}<div class="mono sub">{{ i.endpoint || '—' }}</div></td>
                <td class="sub">{{ i.detail }}</td>
                <td class="mono sub pre">{{ i.request }}</td>
                <td class="mono sub pre">{{ i.response }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="课题 2 测点数据" name="t2">
        <div class="card card-pad">
          <div class="card-title">测点数据上传预览 <StatusBadge feature="m1.tp_data" /></div>
          <p class="sub">只做 XLSX / CSV 预览。“测点 → 节点转换” <StatusBadge status="todo" small />，需要课题 2 提供映射、单位字典与标识范围。</p>
          <input type="file" accept=".csv,.xlsx,.xlsm" data-testid="upload-meas" @change="onUpload" />
          <div v-if="preview" style="margin-top: 12px">
            <div v-for="s in preview.sheets" :key="s.sheet" class="sheet">
              <div class="sub">{{ preview.filename }} · 工作表 {{ s.sheet }} · {{ s.rows }} 行</div>
              <table class="table-plain">
                <thead><tr><th v-for="c in s.columns" :key="c">{{ c }}</th></tr></thead>
                <tbody><tr v-for="(r, i) in s.head" :key="i"><td v-for="(v, j) in r" :key="j">{{ v }}</td></tr></tbody>
              </table>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="名称 ↔ 编号登记表" name="reg">
        <div class="card card-pad">
          <div class="card-title">名称 ↔ 编号登记表 <StatusBadge status="reserved" /></div>
          <p class="sub">文件 <code>data/name_registry.csv</code>，现为空，课题 2 后续提供。有了它，指令里的设备中文名才能映射到 B / L / G 编号；映射不到时绝不猜。</p>
          <table class="table-plain" data-testid="registry-table">
            <thead><tr><th v-for="c in registry.columns" :key="c">{{ c }}</th></tr></thead>
            <tbody>
              <tr v-if="!registry.rows.length"><td :colspan="registry.columns.length || 1" class="sub">（空）</td></tr>
              <tr v-for="(r, i) in registry.rows" :key="i"><td v-for="(v, j) in r" :key="j">{{ v }}</td></tr>
            </tbody>
          </table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="知识表与配置" name="cfg">
        <div v-if="cfg" class="grid2">
          <div class="card card-pad">
            <div class="card-title">推断知识表（config/knowledge.yaml）</div>
            <p class="sub">推断链的来源。推断项的幅度不准猜；规程默认值 <code>default_value</code> 现在全部留空。</p>
            <table class="table-plain" data-testid="knowledge-table">
              <thead><tr><th>规则</th><th>关键词</th><th>规程默认值</th></tr></thead>
              <tbody>
                <tr v-for="r in cfg.knowledge.inference_rules" :key="r.id">
                  <td>{{ r.name }}<div class="sub">{{ r.component }}.{{ r.param }} {{ r.direction }}</div></td>
                  <td class="sub">{{ r.keywords.join('、') }}</td>
                  <td>{{ r.default_value ?? '未配置' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="card card-pad">
            <div class="card-title">运行配置</div>
            <table class="table-plain">
              <tbody>
                <tr><th>建模引擎</th><td>{{ cfg.env.llm_mode }}</td></tr>
                <tr><th>LLM 地址 / 模型</th><td class="mono">{{ cfg.env.llm_base_url || '—' }} / {{ cfg.env.llm_model || '—' }}</td></tr>
                <tr><th>求解模式</th><td>{{ cfg.env.solver_mode }}</td></tr>
                <tr><th>断面目录</th><td class="mono">{{ cfg.env.snapshot_dir }}</td></tr>
                <tr><th>重载 / 越限阈值</th><td>{{ cfg.app.thresholds.overload_ratio }} / {{ cfg.app.thresholds.violation_ratio }}</td></tr>
                <tr><th>数值范围</th><td>scale ∈ (0, {{ cfg.app.ranges.scale_max }}] · 电压 ∈ [{{ cfg.app.ranges.voltage_min }}, {{ cfg.app.ranges.voltage_max }}]</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); align-items: start; }
@media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }
.chip { display: inline-block; background: var(--c-surface-2); border-radius: 10px; padding: 0 8px; margin: 1px 4px 1px 0; font-size: var(--fs-xs); }
.ex { font-size: var(--fs-xs); margin-top: 2px; word-break: break-all; }
.pre { white-space: pre-wrap; word-break: break-all; }
</style>

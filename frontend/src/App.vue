<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import logoPku from '@/assets/logo_pku.svg'
import logoCsg from '@/assets/logo_csg.svg'
import logoHr from '@/assets/logo_hrlab.svg'

const route = useRoute()
const app = useAppStore()
const embed = computed(() => !!route.meta.embed)
onMounted(() => app.init())

const menus = [
  { path: '/workbench', label: '建模工作台' },
  { path: '/map', label: '地图' },
  { path: '/cross', label: '跨课题接口' },
  { path: '/benchmark', label: '交流基准' },
  { path: '/measure', label: '测点转换' },
  { path: '/testmode', label: '测评模式' },
  { path: '/decompose', label: '聚合与分解' },
  { path: '/data', label: '数据与接口' },
  { path: '/features', label: '功能清单' },
]

// 顶栏状态灯：课题 2 数据、课题 2 大模型、动态建模与去幻觉方法、求解器、课题 3
const lamps = computed(() => {
  const order = ['t2_data', 't2_llm', 'ext_method', 'solver', 'risk']
  const short: Record<string, string> = { t2_data: '课题2数据', t2_llm: '课题2大模型', ext_method: '动态建模', solver: '求解器', risk: '课题3' }
  return order
    .map((id) => app.integrations.find((i) => i.id === id))
    .filter(Boolean)
    .map((i) => ({ id: i!.id, short: short[i!.id], state: i!.state, tip: `${i!.name}：${i!.state_label}` }))
})
</script>

<template>
  <div class="shell" :class="{ embed }">
    <header v-if="!embed" class="nav">
      <div class="row1">
        <div class="title">
          <div class="t1">运行方式智能调整平台C</div>
          <div class="t2">课题 4 · 多智能体协同的复杂运行方式智能调整</div>
        </div>
        <div class="logos" data-testid="logos">
          <img :src="logoPku" alt="北京大学" class="lg pku" />
          <i class="sep" />
          <img :src="logoCsg" alt="中国南方电网" class="lg csg" />
          <i class="sep" />
          <img :src="logoHr" alt="怀柔实验室" class="lg hr" />
        </div>
      </div>
      <div class="row2">
        <nav class="menu">
          <router-link v-for="m in menus" :key="m.path" :to="m.path" class="item" active-class="active">{{ m.label }}</router-link>
        </nav>
        <div class="lamps" data-testid="lamps">
          <span v-if="!app.backendOk" class="lamp-warn">后端未连接</span>
          <el-tooltip v-for="l in lamps" :key="l.id" :content="l.tip" placement="bottom">
            <span class="lamp"><i class="dot" :class="l.state" />{{ l.short }}</span>
          </el-tooltip>
        </div>
      </div>
    </header>
    <main class="main"><router-view /></main>
  </div>
</template>

<style scoped>
.shell { height: 100%; display: flex; flex-direction: column; }
.nav { flex: none; background: var(--c-surface); border-bottom: 1px solid var(--c-hairline); box-shadow: 0 2px 12px rgba(20, 40, 80, 0.05); position: relative; z-index: 5; padding: 0 28px; }
.nav::before { content: ''; position: absolute; left: 0; right: 0; top: 0; height: 3px; background: linear-gradient(90deg, var(--c-brand-red), var(--c-brand-blue)); }
.row1 { display: flex; align-items: center; justify-content: space-between; height: 62px; gap: 24px; }
.row2 { display: flex; align-items: center; justify-content: space-between; height: 40px; border-top: 1px solid var(--c-hairline); gap: 16px; }
.title { display: flex; flex-direction: column; line-height: 1.3; white-space: nowrap; }
.t1 { font-size: 21px; font-weight: 700; color: var(--c-brand-blue); letter-spacing: 2px; }
.t2 { font-size: 11.5px; color: var(--c-muted); letter-spacing: 0.5px; }
.menu { display: flex; gap: 2px; }
.item { padding: 6px 14px; border-radius: 8px; color: var(--c-muted); font-size: 13.5px; white-space: nowrap; transition: all 0.15s; }
.item:hover { background: var(--c-surface-2); color: var(--c-ink); }
.item.active { background: var(--c-primary-bg); color: var(--c-primary-ink); font-weight: 600; }
.lamps { display: flex; gap: 14px; align-items: center; font-size: 11.5px; color: var(--c-muted); }
.lamp { display: inline-flex; align-items: center; gap: 4px; cursor: default; white-space: nowrap; }
.lamp-warn { color: var(--c-danger); }
.logos { display: flex; align-items: center; gap: 18px; flex: none; }
.lg { display: block; object-fit: contain; flex: none; }
.lg.pku { height: 38px; } .lg.csg { height: 32px; } .lg.hr { height: 40px; }
.sep { width: 1px; height: 28px; background: var(--c-border); opacity: 0.7; }
@media (max-width: 1400px) { .lg.pku { height: 32px; } .lg.csg { height: 27px; } .lg.hr { height: 34px; } .logos { gap: 12px; } }
@media (max-width: 1100px) { .t2 { display: none; } .lamps { display: none; } .lg.pku { height: 26px; } .lg.csg { height: 22px; } .lg.hr { height: 28px; } }
.main { flex: 1; min-height: 0; overflow: auto; }
</style>

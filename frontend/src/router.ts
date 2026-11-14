import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/workbench' },
    { path: '/workbench', name: 'workbench', component: () => import('./views/WorkbenchView.vue'), meta: { title: '建模工作台' } },
    // 嵌入路由：隐藏顶部导航，只保留工作台，便于 iframe 嵌进宿主平台
    { path: '/embed/workbench', name: 'embed', component: () => import('./views/WorkbenchView.vue'), meta: { embed: true, title: '建模工作台' } },
    { path: '/map', name: 'map', component: () => import('./views/MapView.vue'), meta: { title: '地图' } },
    { path: '/benchmark', name: 'benchmark', component: () => import('./views/BenchmarkView.vue'), meta: { title: '交流基准' } },
    { path: '/measure', name: 'measure', component: () => import('./views/MeasureView.vue'), meta: { title: '测点转换' } },
    { path: '/testmode', name: 'testmode', component: () => import('./views/TestModeView.vue'), meta: { title: '测评模式' } },
    { path: '/decompose', name: 'decompose', component: () => import('./views/DecomposeView.vue'), meta: { title: '问题分解与多智能体' } },
    { path: '/data', name: 'data', component: () => import('./views/DataView.vue'), meta: { title: '数据与接口' } },
    { path: '/features', name: 'features', component: () => import('./views/FeaturesView.vue'), meta: { title: '功能清单' } },
    { path: '/:pathMatch(.*)*', redirect: '/workbench' },
  ],
})

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) || '建模工作台'} · 运行方式智能调整平台C`
})

export default router

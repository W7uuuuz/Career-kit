<script setup lang="ts">
import { computed } from 'vue'
import { loadState, roadmapUrl, showToast, store } from '../store'

const profileLine = computed(() => {
  if (!store.state) return store.loading ? '正在读取档案…' : '尚未读取档案'
  const level = store.state.start_level || '未判定'
  return `档案：${store.state.profile} · 目标档位：${level}`
})

async function refresh(): Promise<void> {
  await loadState()
  if (!store.error) showToast('已刷新')
}
</script>

<template>
  <header class="app-header">
    <div class="brand">
      <h1>Career Kit 控制台</h1>
      <p class="sub">{{ profileLine }}</p>
    </div>
    <div class="actions">
      <a class="btn ghost" :href="roadmapUrl()" target="_blank" rel="noopener">职业地图</a>
      <button class="btn primary" :disabled="store.loading" @click="refresh">
        {{ store.loading ? '刷新中…' : '刷新' }}
      </button>
    </div>
  </header>
</template>

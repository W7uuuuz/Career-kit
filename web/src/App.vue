<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { connectEvents, loadState, store } from './store'
import { startSession } from './session'
import type { Task } from './types'
import AppHeader from './components/AppHeader.vue'
import MapView from './components/MapView.vue'
import WarningsBox from './components/WarningsBox.vue'
import AlignmentCard from './components/AlignmentCard.vue'
import ResearchCard from './components/ResearchCard.vue'
import ReportsCard from './components/ReportsCard.vue'
import PhaseList from './components/PhaseList.vue'
import ApplicationCard from './components/ApplicationCard.vue'
import TaskEditDialog from './components/TaskEditDialog.vue'
import ToastHost from './components/ToastHost.vue'

const editing = ref<Task | null>(null)

onMounted(() => {
  startSession()
  void loadState()
  connectEvents()
})
</script>

<template>
  <div class="wrap">
    <AppHeader />

    <div v-if="store.closed" class="closed-overlay">
      <div class="closed-card">
        <h2>控制台已关闭</h2>
        <p class="muted">服务已经停止。需要继续时，双击桌面上的「Career Kit」重新打开。</p>
      </div>
    </div>

    <div v-if="store.error" class="warn-box">
      无法读取档案：{{ store.error }}。请从桌面快捷方式重新打开职业地图，或确认 token 是否有效。
    </div>
    <div v-if="store.sseError" class="warn-box subtle">{{ store.sseError }}</div>

    <template v-if="store.state && !store.closed">
      <MapView :state="store.state" @edit="editing = $event" />

      <WarningsBox :warnings="store.state.warnings" />
      <div v-if="store.state.sync_warning" class="warn-box subtle">
        {{ store.state.sync_warning }}
      </div>

      <details class="more-panel">
        <summary>计划详情与管理</summary>
        <div class="more-body">
          <AlignmentCard :alignment="store.state.alignment" />
          <ResearchCard :research="store.state.research" />
          <ReportsCard :reports="store.state.reports" />
          <PhaseList :phases="store.state.phases" />
          <ApplicationCard :applications="store.state.applications" />
        </div>
      </details>
    </template>

    <div v-else-if="store.loading && !store.closed" class="loading">正在读取档案…</div>

    <p class="footer">
      数据直接写入本机档案，与 MCP 共用；关闭页面会自动停止服务。
      顺序归产品，时间归用户。
    </p>
  </div>

  <TaskEditDialog v-if="editing" :task="editing" @close="editing = null" />
  <ToastHost />
</template>

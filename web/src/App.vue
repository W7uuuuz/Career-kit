<script setup lang="ts">
import { onMounted } from 'vue'
import { connectEvents, loadState, store } from './store'
import AppHeader from './components/AppHeader.vue'
import OverviewCard from './components/OverviewCard.vue'
import WarningsBox from './components/WarningsBox.vue'
import AlignmentCard from './components/AlignmentCard.vue'
import ResearchCard from './components/ResearchCard.vue'
import ReportsCard from './components/ReportsCard.vue'
import PhaseList from './components/PhaseList.vue'
import ApplicationCard from './components/ApplicationCard.vue'
import ToastHost from './components/ToastHost.vue'

onMounted(() => {
  void loadState()
  connectEvents()
})
</script>

<template>
  <div class="wrap">
    <AppHeader />

    <div v-if="store.error" class="warn-box">
      无法读取档案：{{ store.error }}。请从桌面快捷方式重新打开控制台，或确认 token 是否有效。
    </div>
    <div v-if="store.sseError" class="warn-box subtle">{{ store.sseError }}</div>

    <template v-if="store.state">
      <OverviewCard :state="store.state" />
      <WarningsBox :warnings="store.state.warnings" />
      <div v-if="store.state.sync_warning" class="warn-box subtle">
        {{ store.state.sync_warning }}
      </div>
      <AlignmentCard :alignment="store.state.alignment" />
      <ResearchCard :research="store.state.research" />
      <ReportsCard :reports="store.state.reports" />
      <PhaseList :phases="store.state.phases" />
      <ApplicationCard :applications="store.state.applications" />
    </template>

    <div v-else-if="store.loading" class="loading">正在读取档案…</div>

    <p class="footer">
      数据直接写入本机档案，与 MCP 共用；这里不需要导出打卡指令。顺序归产品，时间归用户。
    </p>
  </div>
  <ToastHost />
</template>

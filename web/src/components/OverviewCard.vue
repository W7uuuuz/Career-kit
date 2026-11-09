<script setup lang="ts">
import { computed } from 'vue'
import type { AppState } from '../types'

const props = defineProps<{ state: AppState }>()

const percent = computed(() =>
  props.state.total_tasks
    ? Math.round((props.state.total_done / props.state.total_tasks) * 100)
    : 0,
)
</script>

<template>
  <section class="overview card">
    <div class="ring" :style="{ '--p': percent }"><span>{{ percent }}%</span></div>
    <div class="overview-text">
      <div class="big">{{ percent }}%</div>
      <div class="muted">
        {{ state.all_complete ? '全部完成 · ' : '' }}{{ state.total_done }} / {{ state.total_tasks }} 个任务
      </div>
      <div v-if="state.strategy" class="strategy">{{ state.strategy }}</div>
    </div>
  </section>
</template>

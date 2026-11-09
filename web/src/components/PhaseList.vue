<script setup lang="ts">
import { ref } from 'vue'
import type { Phase, Task } from '../types'
import PhaseCard from './PhaseCard.vue'
import TaskEditDialog from './TaskEditDialog.vue'

defineProps<{ phases: Phase[] }>()

const editing = ref<Task | null>(null)
</script>

<template>
  <section class="phases">
    <PhaseCard
      v-for="phase in phases"
      :key="phase.id"
      :phase="phase"
      @edit="editing = $event"
    />
    <div v-if="!phases.length" class="card empty">
      还没有生成路线图，请先在对话里完成规划。
    </div>
  </section>

  <TaskEditDialog v-if="editing" :task="editing" @close="editing = null" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AppState, Phase, Task } from '../types'
import TaskItem from './TaskItem.vue'

const props = defineProps<{ state: AppState }>()
const emit = defineEmits<{ (e: 'edit', task: Task): void }>()

const percent = computed(() =>
  props.state.total_tasks
    ? Math.round((props.state.total_done / props.state.total_tasks) * 100)
    : 0,
)

const current = computed<Phase | null>(() => {
  const phases = props.state.phases
  return phases.find((phase) => phase.is_current) || phases[phases.length - 1] || null
})

const nextTask = computed<Task | null>(() => {
  const phase = current.value
  if (!phase) return null
  return phase.tasks.find(
    (task) => task.status !== 'completed' && task.status !== 'skipped',
  ) || null
})

const phaseDone = computed(() => {
  const phase = current.value
  if (!phase || !phase.total) return 0
  return Math.round((phase.done / phase.total) * 100)
})

function channelNames(items: { channel?: string }[] | undefined): string {
  return (items || [])
    .map((item) => item.channel || '')
    .filter(Boolean)
    .join(' / ')
}

function focusCurrentTasks(): void {
  document.getElementById('current-tasks')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function phaseClass(phase: Phase): Record<string, boolean> {
  return {
    current: phase.is_current,
    done: phase.total > 0 && phase.done >= phase.total,
  }
}
</script>

<template>
  <section class="map-hero card">
    <div class="map-hero-main">
      <p class="eyebrow">我的职业地图</p>
      <h2>{{ state.strategy || '先确认方向，再生成路线' }}</h2>
      <p class="muted">
        {{ state.total_done }} / {{ state.total_tasks }} 个任务
        <template v-if="current"> · 当前：{{ current.name }}</template>
        <template v-if="state.all_complete"> · 全部完成</template>
      </p>
      <div class="bar"><div class="fill" :style="{ width: percent + '%' }"></div></div>
    </div>
    <div class="ring" :style="{ '--p': percent }"><span>{{ percent }}%</span></div>
  </section>

  <section v-if="nextTask" class="next card">
    <div class="next-label">下一步</div>
    <div class="next-name">{{ nextTask.name }}</div>
    <div v-if="nextTask.done_criteria" class="goal">
      完成标准：{{ nextTask.done_criteria }}
    </div>
    <ol v-if="nextTask.how_to.length" class="next-steps">
      <li v-for="(step, index) in nextTask.how_to" :key="index">{{ step }}</li>
    </ol>
    <div class="next-actions">
      <button class="btn primary" type="button" @click="focusCurrentTasks">
        去打卡
      </button>
      <span v-if="current" class="muted">
        当前阶段 {{ current.done }} / {{ current.total }} · {{ phaseDone }}%
      </span>
    </div>
  </section>

  <section v-else-if="!state.total_tasks" class="next card empty">
    还没有可执行任务。回到对话里完成规划后，地图会自动出现下一步。
  </section>

  <section v-else class="next card done-all">
    当前路线的任务都已完成。回到对话里做一次复盘，再决定下一段。
  </section>

  <section class="journey card">
    <div class="card-head">
      <span class="card-title">路线</span>
      <span class="muted">{{ state.phases.length }} 个阶段 · 顺序推进，节奏自定</span>
    </div>

    <div v-if="!state.phases.length" class="empty">
      还没有生成路线图，请先在对话里完成规划。
    </div>

    <ol v-else class="stations">
      <li
        v-for="(phase, index) in state.phases"
        :key="phase.id"
        class="station"
        :class="phaseClass(phase)"
      >
        <div class="station-dot">{{ index + 1 }}</div>
        <div class="station-body">
          <div class="station-head">
            <span class="station-name">{{ phase.name }}</span>
            <span class="type-pill">{{ phase.type_label || phase.type }}</span>
            <span v-if="phase.is_current" class="badge current">当前阶段</span>
            <span class="muted station-progress">
              {{ phase.total ? `${phase.done} / ${phase.total}` : '未细化' }}
            </span>
          </div>

          <div v-if="phase.goal" class="goal">{{ phase.goal }}</div>

          <div class="station-tags">
            <span v-if="phase.company" class="chip">{{ phase.company }}</span>
            <span v-if="phase.target_level" class="chip">目标 {{ phase.target_level }}</span>
            <span v-if="phase.time_window?.window" class="chip">
              {{ phase.time_window.window }}
            </span>
            <span v-if="phase.kpi?.target" class="chip">
              {{ phase.kpi.metric || 'KPI' }}：{{ phase.kpi.target }}
            </span>
            <span v-if="phase.conversion_risk?.level" class="chip warn">
              转正风险 {{ phase.conversion_risk.level }}
            </span>
          </div>

          <div v-if="phase.kpi?.evidence" class="muted station-note">
            验收：{{ phase.kpi.evidence }}
          </div>
          <div v-if="phase.access_paths?.length" class="muted station-note">
            通道：{{ channelNames(phase.access_paths) }}
          </div>
          <div v-if="phase.fallback_paths?.length" class="muted station-note">
            保底：{{ channelNames(phase.fallback_paths) }}
          </div>
          <div v-if="phase.decision_gate?.condition" class="muted station-note">
            换道条件：{{ phase.decision_gate.condition }}
            <template v-if="phase.decision_gate.action"> → {{ phase.decision_gate.action }}</template>
          </div>

          <div v-if="phase.total" class="bar station-bar">
            <div
              class="fill"
              :style="{ width: Math.round((phase.done / phase.total) * 100) + '%' }"
            ></div>
          </div>

          <ul
            v-if="!phase.tasks.length && phase.milestone_tasks.length"
            class="ms-preview"
          >
            <li v-for="(item, index) in phase.milestone_tasks" :key="index">
              <span class="pr" :class="`pr-${item.priority || 'medium'}`"></span>
              {{ item.name }}
              <template v-if="item.done_criteria">：{{ item.done_criteria }}</template>
            </li>
          </ul>

          <div v-if="phase.is_current && phase.tasks.length" id="current-tasks" class="current-tasks">
            <TaskItem
              v-for="task in phase.tasks"
              :key="task.id"
              :task="task"
              @edit="emit('edit', $event)"
            />
          </div>
        </div>
      </li>
    </ol>
  </section>
</template>

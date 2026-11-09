<script setup lang="ts">
import { computed } from 'vue'
import type { Phase, Task } from '../types'
import TaskItem from './TaskItem.vue'

const props = defineProps<{ phase: Phase }>()
const emit = defineEmits<{ (e: 'edit', task: Task): void }>()

interface TaskGroup {
  milestoneId: string | null
  tasks: Task[]
  done: number
  total: number
}

function isDone(task: Task): boolean {
  return task.status === 'completed' || task.status === 'skipped'
}

const groups = computed<TaskGroup[]>(() => {
  const list: TaskGroup[] = []
  let current: TaskGroup | null = null
  for (const task of props.phase.tasks) {
    const milestoneId = task.milestone_id || null
    if (!current || current.milestoneId !== milestoneId) {
      current = { milestoneId, tasks: [], done: 0, total: 0 }
      list.push(current)
    }
    current.tasks.push(task)
    if (milestoneId) {
      current.total += 1
      if (isDone(task)) current.done += 1
    }
  }
  return list
})

const percent = computed(() =>
  props.phase.total ? Math.round((props.phase.done / props.phase.total) * 100) : 0,
)

function milestoneName(id: string | null): string {
  if (!id) return ''
  return props.phase.milestone_names[id] || id
}

function priorityClass(priority: string): string {
  return `pr-${priority || 'medium'}`
}
</script>

<template>
  <section class="card phase">
    <div class="card-head">
      <span class="card-title">
        {{ phase.name }}
        <span class="type-pill">{{ phase.type_label || phase.type }}</span>
        <span v-if="phase.is_current" class="badge current">当前阶段</span>
      </span>
      <span class="muted">{{ phase.done }} / {{ phase.total }} · {{ percent }}%</span>
    </div>

    <div class="bar"><div class="fill" :style="{ width: percent + '%' }"></div></div>
    <div v-if="phase.company" class="company">{{ phase.company }}</div>
    <div v-if="phase.goal" class="goal">{{ phase.goal }}</div>

    <div class="tasks">
      <template v-if="phase.tasks.length">
        <template v-for="group in groups" :key="group.milestoneId || 'none'">
          <div v-if="group.milestoneId" class="ms">
            里程碑：{{ milestoneName(group.milestoneId) }}（{{ group.done }}/{{ group.total }}）
          </div>
          <TaskItem
            v-for="task in group.tasks"
            :key="task.id"
            :task="task"
            @edit="emit('edit', $event)"
          />
        </template>
      </template>

      <template v-else-if="phase.milestone_tasks.length">
        <div class="empty">里程碑已规划；回到对话里细化当前阶段后会变成可打卡任务。</div>
        <ul class="ms-preview">
          <li v-for="(item, index) in phase.milestone_tasks" :key="index">
            <span class="pr" :class="priorityClass(item.priority)"></span>{{ item.name
            }}<template v-if="item.done_criteria">：{{ item.done_criteria }}</template>
          </li>
        </ul>
      </template>

      <div v-else class="empty">还没有细化任务。回到对话里让 AI 细化当前阶段。</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '../types'
import { checkin, store } from '../store'

const props = defineProps<{ task: Task }>()
const emit = defineEmits<{ (e: 'edit', task: Task): void }>()

const done = computed(
  () => props.task.status === 'completed' || props.task.status === 'skipped',
)

const doneLabel = computed(() => (props.task.status === 'skipped' ? '已跳过' : '已完成'))

const goal = computed(() => {
  if (props.task.checkin_goal) return props.task.checkin_goal
  return props.task.checkin_mode === 'percent' ? 100 : 0
})

const hasDetail = computed(
  () =>
    !!props.task.done_criteria ||
    !!props.task.desc ||
    props.task.how_to.length > 0 ||
    props.task.resources.length > 0,
)

const priorityClass = computed(() => `pr-${props.task.priority || 'medium'}`)

function undo(): void {
  void checkin(props.task.id, 'pending', 0)
}

function daily(): void {
  void checkin(props.task.id, 'completed', 1)
}

function skip(): void {
  void checkin(props.task.id, 'skipped', 0)
}

function onOnce(event: Event): void {
  if ((event.target as HTMLInputElement).checked) {
    void checkin(props.task.id, 'completed', 1)
  }
}

function onPercent(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  void checkin(props.task.id, 'completed', value)
}
</script>

<template>
  <div class="task-wrap">
    <div class="task">
      <div class="task-control">
        <template v-if="done">
          <span class="done-badge">{{ doneLabel }}</span>
          <button class="ck-btn ghost" :disabled="store.busy" @click="undo">撤销</button>
        </template>

        <template v-else-if="task.checkin_mode === 'daily'">
          <span class="ck-ctl">
            打卡 {{ Math.floor(task.checkin_progress) }}/{{ task.checkin_goal || '?' }} 天
          </span>
          <button class="ck-btn" :disabled="store.busy" @click="daily">今天打卡</button>
        </template>

        <template v-else-if="task.checkin_mode === 'percent'">
          <span class="ck-ctl">
            进度 {{ Math.floor(task.checkin_progress) }}%/{{ goal }}%
          </span>
          <input
            type="range"
            min="0"
            :max="goal"
            :value="Math.floor(task.checkin_progress)"
            :disabled="store.busy"
            @change="onPercent"
          />
        </template>

        <template v-else>
          <input
            type="checkbox"
            :checked="done"
            :disabled="store.busy"
            @change="onOnce"
          />
        </template>

        <button
          v-if="!done"
          class="ck-btn ghost"
          :disabled="store.busy"
          @click="skip"
        >
          跳过
        </button>
      </div>

      <span class="pr" :class="priorityClass"></span>
      <span class="task-name" :class="{ done }">{{ task.name }}</span>
      <span class="task-meta">{{ task.id }}</span>
      <button class="ck-btn ghost edit-btn" @click="emit('edit', task)">编辑</button>
    </div>

    <details v-if="hasDetail" class="task-detail">
      <summary>怎么做 / 完成标准</summary>
      <div v-if="task.done_criteria" class="task-done">完成标准：{{ task.done_criteria }}</div>
      <div v-if="task.desc" class="task-desc">{{ task.desc }}</div>
      <ol v-if="task.how_to.length">
        <li v-for="(step, index) in task.how_to" :key="index">{{ step }}</li>
      </ol>
      <div v-if="task.resources.length" class="task-res">
        资源：
        <template v-for="(resource, index) in task.resources" :key="index">
          <a
            v-if="resource.url"
            :href="resource.url"
            target="_blank"
            rel="noopener"
          >{{ resource.label || '资源' }}</a>
          <span v-else-if="resource.search">
            {{ resource.label || '资源' }}（搜索：{{ resource.search }}）
          </span>
          <span v-if="index < task.resources.length - 1" class="dot">·</span>
        </template>
      </div>
    </details>
  </div>
</template>

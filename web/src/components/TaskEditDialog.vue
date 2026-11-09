<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { Task } from '../types'
import { saveTask } from '../store'

const props = defineProps<{ task: Task }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const form = reactive({
  name: '',
  description: '',
  howTo: '',
  doneCriteria: '',
  priority: 'medium',
  mode: 'once',
  goal: 0,
})

const saving = ref(false)

watch(
  () => props.task,
  (task) => {
    form.name = task.name
    form.description = task.desc || ''
    form.howTo = (task.how_to || []).join('\n')
    form.doneCriteria = task.done_criteria || ''
    form.priority = task.priority || 'medium'
    form.mode = task.checkin_mode || 'once'
    form.goal = task.checkin_goal || 0
  },
  { immediate: true },
)

const goalLabel = () => {
  if (form.mode === 'daily') return '目标天数'
  if (form.mode === 'percent') return '目标百分比'
  return '目标'
}

async function submit(): Promise<void> {
  if (!form.name.trim() || saving.value) return
  saving.value = true
  const ok = await saveTask({
    task_id: props.task.id,
    name: form.name.trim(),
    description: form.description,
    how_to: form.howTo
      .split(/\n|；|;/)
      .map((item) => item.trim())
      .filter(Boolean),
    done_criteria: form.doneCriteria,
    priority: form.priority,
    checkin_mode: form.mode,
    checkin_goal: form.mode === 'once' ? 0 : Number(form.goal) || 0,
  })
  saving.value = false
  if (ok) emit('close')
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-label="编辑任务">
      <div class="modal-head">
        <div>
          <h2>编辑任务</h2>
          <p class="muted">{{ task.id }}</p>
        </div>
        <button class="icon-btn" aria-label="关闭" @click="emit('close')">×</button>
      </div>

      <form class="edit-form" @submit.prevent="submit">
        <label>
          <span>任务名</span>
          <input v-model="form.name" required />
        </label>

        <label>
          <span>描述</span>
          <textarea v-model="form.description" rows="2"></textarea>
        </label>

        <label>
          <span>怎么做（每行一条）</span>
          <textarea v-model="form.howTo" rows="3"></textarea>
        </label>

        <label>
          <span>完成标准</span>
          <input v-model="form.doneCriteria" />
        </label>

        <div class="edit-row">
          <label>
            <span>优先级</span>
            <select v-model="form.priority">
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </label>

          <label>
            <span>打卡方式</span>
            <select v-model="form.mode">
              <option value="once">一次完成</option>
              <option value="daily">按天打卡</option>
              <option value="percent">按比例打卡</option>
            </select>
          </label>

          <label>
            <span>{{ goalLabel() }}</span>
            <input
              v-model.number="form.goal"
              type="number"
              min="0"
              :disabled="form.mode === 'once'"
            />
          </label>
        </div>

        <div class="modal-actions">
          <button type="button" class="btn ghost" @click="emit('close')">取消</button>
          <button type="submit" class="btn primary" :disabled="saving || !form.name.trim()">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

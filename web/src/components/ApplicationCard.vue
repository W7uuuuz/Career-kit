<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { ApplicationInfo } from '../types'
import { addApplication } from '../store'

defineProps<{ applications: ApplicationInfo[] }>()

const STATUS_LABELS: Record<string, string> = {
  applied: '已投递',
  screening: '进初筛',
  interview: '进面试',
  offer: 'offer',
  rejected: '已拒绝',
  withdrawn: '已撤回',
}

const form = reactive({
  company: '',
  role: '',
  channel: '',
  status: 'applied',
})

const submitting = ref(false)

async function submit(): Promise<void> {
  if (!form.company.trim() || submitting.value) return
  submitting.value = true
  const ok = await addApplication({
    company: form.company.trim(),
    role: form.role.trim(),
    channel: form.channel.trim(),
    status: form.status,
  })
  submitting.value = false
  if (ok) {
    form.company = ''
    form.role = ''
    form.channel = ''
    form.status = 'applied'
  }
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status
}

function formatDate(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <span class="card-title">登记投递</span>
    </div>

    <form class="app-form" @submit.prevent="submit">
      <input v-model="form.company" placeholder="公司" required />
      <input v-model="form.role" placeholder="岗位" />
      <input v-model="form.channel" placeholder="渠道（BOSS / 官网 / 内推）" />
      <select v-model="form.status">
        <option value="applied">已投递</option>
        <option value="screening">进初筛</option>
        <option value="interview">进面试</option>
        <option value="offer">offer</option>
      </select>
      <button class="btn primary" type="submit" :disabled="submitting || !form.company.trim()">
        {{ submitting ? '登记中…' : '登记' }}
      </button>
    </form>

    <div v-if="applications.length" class="applications">
      <div class="card-head sub-head">
        <span class="card-title small">最近投递</span>
        <span class="muted">最近 {{ applications.length }} 条</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>公司</th>
              <th>岗位</th>
              <th>渠道</th>
              <th>状态</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="application in applications" :key="application.id">
              <td>{{ application.company }}</td>
              <td>{{ application.role || '—' }}</td>
              <td>{{ application.channel || '—' }}</td>
              <td>
                <span class="status-pill">{{ statusLabel(application.status) }}</span>
              </td>
              <td class="muted">{{ formatDate(application.applied_at) || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

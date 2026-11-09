<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ReportInfo } from '../types'
import { assetUrl } from '../store'

const props = defineProps<{ reports: ReportInfo[] }>()

const query = ref('')

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return props.reports
  return props.reports.filter((report) =>
    String(report.direction || '').toLowerCase().includes(keyword),
  )
})

function linksOf(report: ReportInfo): { label: string; href: string }[] {
  const links: { label: string; href: string }[] = []
  if (report.html) links.push({ label: '阅读版', href: assetUrl(report.html) })
  if (report.md) links.push({ label: '全文', href: assetUrl(report.md) })
  if (report.json) links.push({ label: '原始数据', href: assetUrl(report.json) })
  return links
}
</script>

<template>
  <section v-if="reports.length" class="card">
    <div class="card-head">
      <span class="card-title">
        调研报告
        <span class="type-pill">{{ reports.length }} 份</span>
      </span>
    </div>
    <input v-model="query" class="search-input" placeholder="按方向筛选，如 AI Agent" />
    <ul class="report-list">
      <li v-for="report in filtered" :key="report.direction + report.generated_at">
        <div class="report-head">
          <strong>{{ report.direction }}</strong>
          <span class="muted">{{ report.generated_at || '' }}</span>
        </div>
        <div class="muted">
          岗位 {{ report.counts?.jd_samples ?? 0 }} · 案例 {{ report.counts?.cases ?? 0 }}
          <template v-if="report.failed_sources?.length">
            · 失败源：{{ report.failed_sources.join('、') }}
          </template>
        </div>
        <div v-if="linksOf(report).length" class="task-res">
          <template v-for="(link, index) in linksOf(report)" :key="link.label">
            <a :href="link.href" target="_blank" rel="noopener">{{ link.label }}</a>
            <span v-if="index < linksOf(report).length - 1" class="dot">·</span>
          </template>
        </div>
      </li>
      <li v-if="!filtered.length" class="muted">没有匹配的报告</li>
    </ul>
  </section>
</template>

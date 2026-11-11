<script setup lang="ts">
import { computed } from 'vue'
import type { Alignment } from '../types'
import { assetUrl } from '../store'

const props = defineProps<{ alignment: Alignment }>()

const STAGE_LABELS: Record<string, string> = {
  company_pool: '企业池筛选',
  evidence: '证据采集',
  requirement: '需求分析',
  execution_plan: '执行方案',
  executing: '执行期',
}

const NEXT_TOOL_LABELS: Record<string, string> = {
  select_target_companies: '筛选并确认目标企业池',
  collect_company_evidence: '采集岗位与面经证据',
  analyze_company_requirements: '分析企业需求',
  save_requirement_profile: '保存需求分析',
  plan_execution_alignment: '准备执行方案校准',
  save_execution_alignment: '保存并应用执行方案',
}

const stageLabel = computed(() =>
  props.alignment.stage ? STAGE_LABELS[props.alignment.stage] || props.alignment.stage : '',
)

const nextLabel = computed(() => NEXT_TOOL_LABELS[props.alignment.next_tool] || '')

const started = computed(
  () =>
    !!(
      props.alignment.stage ||
      props.alignment.company_pool ||
      props.alignment.evidence ||
      props.alignment.requirement ||
      props.alignment.execution_plan
    ),
)

const poolTotal = computed(() => {
  const pool = props.alignment.company_pool
  if (!pool) return 0
  if (typeof pool.counts?.total === 'number') return pool.counts.total
  return pool.scrapable.length + pool.not_scrapable.length
})

const evidenceLinks = computed(() => {
  const evidence = props.alignment.evidence
  if (!evidence) return []
  const links: { label: string; href: string }[] = []
  if (evidence.report_md) links.push({ label: '全文', href: assetUrl(evidence.report_md) })
  if (evidence.index) links.push({ label: '原始数据', href: assetUrl(evidence.index) })
  return links
})
</script>

<template>
  <section class="card">
    <div class="card-head">
      <span class="card-title">
        企业适配
        <span v-if="stageLabel" class="type-pill">{{ stageLabel }}</span>
      </span>
      <span v-if="nextLabel" class="muted">下一步：{{ nextLabel }}</span>
    </div>

    <div v-if="!started" class="empty">尚未开始企业适配</div>

    <div v-else class="align-grid">
      <div v-if="alignment.company_pool" class="align-row">
        <span class="align-label">企业池</span>
        <span>
          {{ poolTotal }} 家 · 可抓 {{ alignment.company_pool.scrapable.length }} / 未接入
          {{ alignment.company_pool.not_scrapable.length }}
        </span>
      </div>

      <div v-if="alignment.evidence" class="align-row">
        <span class="align-label">证据</span>
        <span>
          JD {{ alignment.evidence.counts.kept_jobs ?? 0 }} 条 · 面经
          {{ alignment.evidence.counts.interviews ?? 0 }} 条 · 置信度
          {{ alignment.evidence.confidence.jd || '未知' }} /
          {{ alignment.evidence.confidence.interview || '未知' }}
          <template v-if="evidenceLinks.length">
            <span class="dot">·</span>
            <template v-for="(link, index) in evidenceLinks" :key="link.label">
              <a :href="link.href" target="_blank" rel="noopener">{{ link.label }}</a>
              <span v-if="index < evidenceLinks.length - 1" class="dot">·</span>
            </template>
          </template>
        </span>
      </div>

      <div v-if="alignment.requirement" class="align-row">
        <span class="align-label">需求</span>
        <span>
          高频项 {{ alignment.requirement.high_frequency_count }} 条 · 硬门槛
          {{ alignment.requirement.hard_requirement_count }} 条 · 置信度
          {{ alignment.requirement.confidence_jd || '未知' }} /
          {{ alignment.requirement.confidence_interview || '未知' }}
        </span>
      </div>

      <div v-if="alignment.execution_plan" class="align-row">
        <span class="align-label">执行版</span>
        <span>
          {{ alignment.execution_plan.applied ? '已应用' : '待应用' }} ·
          {{ alignment.execution_plan.phase_count }} 个阶段
          <template v-if="alignment.execution_plan.strategy_summary">
            · {{ alignment.execution_plan.strategy_summary }}
          </template>
          <template v-if="alignment.execution_plan.diff_summary">
            · {{ alignment.execution_plan.diff_summary }}
          </template>
        </span>
      </div>

      <div v-if="!alignment.company_pool && !alignment.evidence && !alignment.requirement && !alignment.execution_plan" class="empty">
        暂无适配产物
      </div>
    </div>
  </section>
</template>

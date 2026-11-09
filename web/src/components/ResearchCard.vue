<script setup lang="ts">
import { computed } from 'vue'
import type { ResearchInfo } from '../types'
import { assetUrl } from '../store'

const props = defineProps<{ research: ResearchInfo }>()

const visible = computed(() => !!(props.research && props.research.counts))

const links = computed(() => {
  const research = props.research
  const items: { label: string; href: string }[] = []
  if (research.report_html) items.push({ label: '阅读版', href: assetUrl(research.report_html) })
  if (research.report_md) items.push({ label: '可读全文', href: assetUrl(research.report_md) })
  if (research.report_json) items.push({ label: '原始数据', href: assetUrl(research.report_json) })
  return items
})
</script>

<template>
  <section v-if="visible" class="card">
    <div class="card-head">
      <span class="card-title">
        市场调研
        <span class="type-pill">来源真实</span>
      </span>
      <span class="muted">{{ research.generated_at || '' }}</span>
    </div>
    <div class="goal">
      岗位 {{ research.counts?.jd_samples ?? 0 }} 条 · 案例
      {{ research.counts?.cases ?? 0 }} 条
    </div>
    <div v-if="research.failed_sources?.length" class="muted">
      失败源：{{ research.failed_sources.join('、') }}
    </div>
    <div v-if="links.length" class="task-res">
      <template v-for="(link, index) in links" :key="link.label">
        <a :href="link.href" target="_blank" rel="noopener">{{ link.label }}</a>
        <span v-if="index < links.length - 1" class="dot">·</span>
      </template>
    </div>
  </section>
</template>

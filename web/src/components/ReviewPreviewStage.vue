<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { Download, RotateCcw } from 'lucide-vue-next'
import { useReviewStore } from '../stores/reviewStore'
import { reviewsApi } from '../api/reviews'
import type { ReviewItem, ReviewSummary } from '../api/reviews'

const store = useReviewStore()
const tenderHtml = ref('')
const reviewItems = ref<ReviewItem[]>([])
const summary = ref<ReviewSummary | null>(null)
const loading = ref(true)
const activeItemId = ref<number | null>(null)

const leftPanel = ref<HTMLElement | null>(null)
const rightPanel = ref<HTMLElement | null>(null)

onMounted(async () => {
  if (!store.currentReviewId) return
  try {
    const res = await reviewsApi.preview(store.currentReviewId)
    tenderHtml.value = res.data.tender_html
    reviewItems.value = res.data.review_items
    summary.value = res.data.summary
  } catch { /* error */ }
  finally { loading.value = false }
})

// Click highlight → scroll to annotation
function onHighlightClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('[data-review-id]')
  if (!target) return
  const ids = target.getAttribute('data-review-id')?.split(' ').map(Number).filter(Boolean) || []
  if (ids.length > 0) {
    activeItemId.value = ids[0]
    nextTick(() => {
      const el = rightPanel.value?.querySelector(`[data-annotation-id="${ids[0]}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }
}

// Click annotation → scroll to highlight
function scrollToHighlight(itemId: number) {
  activeItemId.value = itemId
  const el = leftPanel.value?.querySelector(`[data-review-id~="${itemId}"]`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function downloadReport() {
  if (!store.currentReviewId) return
  const res = await reviewsApi.download(store.currentReviewId)
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `审查报告.docx`
  a.click()
  URL.revokeObjectURL(url)
}

function resultColor(result: string) {
  return { pass: 'text-success', fail: 'text-danger', warning: 'text-warning' }[result] || 'text-text-muted'
}
function resultLabel(result: string) {
  return { pass: '合规', fail: '不合规', warning: '需注意', error: '错误' }[result] || result
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Summary bar -->
    <div v-if="summary" class="px-4 py-3 bg-surface border-b border-border flex items-center gap-4 text-sm">
      <span>共{{ summary.total }}条</span>
      <span class="text-success">通过{{ summary.pass }}</span>
      <span class="text-danger">不合规{{ summary.fail }}</span>
      <span class="text-warning">警告{{ summary.warning }}</span>
      <span v-if="summary.critical_fails" class="text-danger font-medium">废标风险: {{ summary.critical_fails }}条</span>
    </div>

    <!-- Main split view -->
    <div class="flex-1 flex overflow-hidden">
      <!-- Left: tender HTML -->
      <div ref="leftPanel" class="w-1/2 overflow-auto p-4 border-r border-border" @click="onHighlightClick">
        <div v-if="loading" class="text-center text-text-muted py-12">加载中...</div>
        <div v-else class="prose max-w-none" v-html="tenderHtml" />
      </div>

      <!-- Right: annotations -->
      <div ref="rightPanel" class="w-1/2 overflow-auto p-4 space-y-3">
        <div
          v-for="item in reviewItems.filter(i => i.result !== 'pass')"
          :key="item.id"
          :data-annotation-id="item.id"
          class="p-3 rounded-lg border cursor-pointer transition-colors"
          :class="activeItemId === item.id ? 'border-success bg-success/5' : 'border-border'"
          @click="scrollToHighlight(item.id)"
        >
          <div class="flex items-center gap-2 mb-1">
            <span :class="resultColor(item.result)" class="text-sm font-medium">{{ resultLabel(item.result) }}</span>
            <span class="text-xs text-text-muted">置信度 {{ item.confidence }}%</span>
            <span class="text-xs px-1.5 py-0.5 rounded bg-background text-text-muted">{{ item.severity }}</span>
          </div>
          <p class="text-sm text-text-primary">{{ item.clause_text }}</p>
          <p class="text-xs text-text-muted mt-1">{{ item.reason }}</p>
        </div>
      </div>
    </div>

    <!-- Bottom bar -->
    <div class="px-4 py-3 bg-surface border-t border-border flex justify-between items-center">
      <button class="text-sm text-text-muted hover:text-text-secondary flex items-center gap-1" @click="store.resetToUpload()">
        <RotateCcw class="size-4" /> 新建审查
      </button>
      <button class="px-4 py-2 bg-success text-white rounded-lg text-sm flex items-center gap-1" @click="downloadReport">
        <Download class="size-4" /> 下载审查报告
      </button>
    </div>
  </div>
</template>

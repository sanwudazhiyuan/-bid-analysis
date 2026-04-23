<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { Download, EyeOff } from 'lucide-vue-next'
import { useAnbiaoStore } from '../stores/anbiaoStore'
import { anbiaoApi } from '../api/anbiao'
import type { AnbiaoFormatResult, AnbiaoContentResult, AnbiaoSummary } from '../api/anbiao'

const store = useAnbiaoStore()
const tenderHtml = ref('')
const formatResults = ref<AnbiaoFormatResult[]>([])
const contentResults = ref<AnbiaoContentResult[]>([])
const summary = ref<AnbiaoSummary | null>(null)
const loading = ref(true)
const activeTab = ref<'format' | 'content'>('content')
const activeItemId = ref<number | null>(null)

const leftPanel = ref<HTMLElement | null>(null)
const rightPanel = ref<HTMLElement | null>(null)

onMounted(async () => {
  if (!store.currentReviewId) return
  try {
    // Load from store first, then fetch preview for HTML
    formatResults.value = store.formatResults
    contentResults.value = store.contentResults
    summary.value = store.summary
    const res = await anbiaoApi.preview(store.currentReviewId)
    tenderHtml.value = res.data.tender_html
    if (res.data.format_results?.length) formatResults.value = res.data.format_results
    if (res.data.content_results?.length) contentResults.value = res.data.content_results
    if (res.data.summary) summary.value = res.data.summary
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
  const res = await anbiaoApi.download(store.currentReviewId)
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `暗标审查报告.docx`
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
      <EyeOff class="size-4 text-purple-500" />
      <span class="px-2 py-0.5 bg-purple-100 text-purple-700 rounded text-xs font-medium">暗标</span>
      <span>共{{ summary.total }}条</span>
      <span class="text-success">通过{{ summary.pass }}</span>
      <span class="text-danger">不通过{{ summary.fail }}</span>
      <span class="text-warning">警告{{ summary.warning }}</span>
    </div>

    <!-- Tab selector -->
    <div class="px-4 py-2 bg-surface border-b border-border flex gap-2">
      <button
        class="px-3 py-1 rounded text-sm"
        :class="activeTab === 'format' ? 'bg-purple-100 text-purple-700 font-medium' : 'text-text-secondary hover:bg-background'"
        @click="activeTab = 'format'"
      >
        格式审查 ({{ formatResults.length }})
      </button>
      <button
        class="px-3 py-1 rounded text-sm"
        :class="activeTab === 'content' ? 'bg-purple-100 text-purple-700 font-medium' : 'text-text-secondary hover:bg-background'"
        @click="activeTab = 'content'"
      >
        内容审查 ({{ contentResults.length }})
      </button>
    </div>

    <!-- Main split view -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Left: document preview -->
      <div ref="leftPanel" class="w-1/2 overflow-y-auto p-4" @click="onHighlightClick">
        <div v-if="loading" class="text-center text-text-muted py-8">加载中...</div>
        <div v-else class="tender-preview" v-html="tenderHtml" />
      </div>

      <!-- Right: review results -->
      <div ref="rightPanel" class="w-1/2 overflow-y-auto p-4 border-l border-border space-y-3">
        <!-- Format tab -->
        <template v-if="activeTab === 'format'">
          <div
            v-for="item in formatResults" :key="item.rule_index"
            class="p-3 rounded-lg border border-border"
            :class="{ 'ring-2 ring-purple-300': activeItemId === item.rule_index }"
            :data-annotation-id="item.rule_index"
          >
            <div class="flex items-center gap-2 mb-1">
              <span :class="resultColor(item.result)" class="font-medium">{{ resultLabel(item.result) }}</span>
              <span v-if="item.is_mandatory" class="text-xs px-1 bg-danger/10 text-danger rounded">强制</span>
              <span v-else class="text-xs px-1 bg-warning/10 text-warning rounded">建议</span>
            </div>
            <p class="text-sm text-text-primary mb-1">{{ item.rule_text }}</p>
            <p class="text-xs text-text-muted">{{ item.reason }}</p>
            <div v-if="item.details?.length" class="mt-2 space-y-1">
              <div v-for="d in item.details" :key="d.location" class="text-xs text-text-muted">
                {{ d.location }}: {{ d.issue }}
              </div>
            </div>
          </div>
        </template>

        <!-- Content tab -->
        <template v-if="activeTab === 'content'">
          <div
            v-for="item in contentResults" :key="item.clause_index"
            class="p-3 rounded-lg border border-border"
            :class="{ 'ring-2 ring-purple-300': activeItemId === item.clause_index }"
            :data-annotation-id="item.clause_index"
          >
            <div class="flex items-center gap-2 mb-1">
              <span :class="resultColor(item.result)" class="font-medium">{{ resultLabel(item.result) }}</span>
              <span class="text-xs text-text-muted">置信度 {{ item.confidence }}%</span>
              <span v-if="item.is_mandatory" class="text-xs px-1 bg-danger/10 text-danger rounded">强制</span>
              <span v-else class="text-xs px-1 bg-warning/10 text-warning rounded">建议</span>
            </div>
            <p class="text-sm text-text-primary mb-1">{{ item.clause_text }}</p>
            <p class="text-xs text-text-muted">{{ item.reason }}</p>
            <button
              v-if="item.tender_locations?.length"
              class="text-xs text-purple-500 hover:underline mt-1"
              @click="scrollToHighlight(item.clause_index)"
            >
              查看标书对应位置
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- Bottom actions -->
    <div class="px-4 py-3 bg-surface border-t border-border flex gap-3">
      <button class="px-4 py-2 border border-border rounded-lg text-sm text-text-secondary hover:bg-background" @click="store.resetToUpload()">
        新建审查
      </button>
      <button class="px-4 py-2 bg-purple-600 text-white rounded-lg text-sm flex items-center gap-2" @click="downloadReport">
        <Download class="size-4" />
        下载审查报告
      </button>
    </div>
  </div>
</template>
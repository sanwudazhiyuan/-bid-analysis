<script setup lang="ts">
import { ref, watch } from 'vue'
import { Download, RotateCcw } from 'lucide-vue-next'
import client from '../api/client'

const props = defineProps<{
  taskId: string
  filename: string
}>()

const emit = defineEmits<{ reset: [] }>()

const tabs = [
  { key: 'report', label: '分析报告' },
  { key: 'format', label: '投标文件大纲' },
  { key: 'checklist', label: '资料清单' },
]

const activeTab = ref('report')
const previewHtml = ref('')
const loading = ref(false)

watch(activeTab, loadPreview, { immediate: true })

async function loadPreview() {
  loading.value = true
  try {
    const res = await client.get(`/files/${activeTab.value}s/${props.taskId}/preview`)
    previewHtml.value = res.data.html || ''
  } catch {
    previewHtml.value = '<p class="text-text-muted">预览加载失败</p>'
  } finally {
    loading.value = false
  }
}

async function downloadFile(fileType: string) {
  try {
    const res = await client.get(`/files/${fileType}s/${props.taskId}/download`, { responseType: 'blob' })
    const disposition = res.headers['content-disposition'] || ''
    const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)/i)
    const filename = filenameMatch ? decodeURIComponent(filenameMatch[1]) : `${props.filename}_${fileType}.docx`
    const url = URL.createObjectURL(res.data)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch {
    // ignore
  }
}

function downloadAll() {
  for (const tab of tabs) {
    downloadFile(tab.key)
  }
}
</script>

<template>
  <div class="flex flex-col h-full animate-fade-in">
    <!-- Tab bar -->
    <div class="flex items-center border-b border-border bg-surface px-4">
      <div class="flex gap-1">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          @click="activeTab = tab.key"
          :class="[
            'px-4 py-3 text-sm font-medium transition-all duration-200 relative',
            activeTab === tab.key
              ? 'text-primary'
              : 'text-text-muted hover:text-text-secondary'
          ]"
        >
          {{ tab.label }}
          <span
            v-if="activeTab === tab.key"
            class="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full"
          />
        </button>
      </div>
    </div>

    <!-- Preview area -->
    <div class="flex-1 overflow-auto p-6 bg-background">
      <div v-if="loading" class="text-center text-text-muted py-12 animate-pulse-soft">加载中...</div>
      <div v-else class="bg-surface rounded-xl border border-border p-6 shadow-xs">
        <div class="prose max-w-none" v-html="previewHtml" />
      </div>
    </div>

    <!-- Bottom bar -->
    <div class="border-t border-border px-5 py-3 flex items-center justify-between bg-surface">
      <button
        data-testid="new-analysis"
        class="text-sm text-text-muted hover:text-text-secondary transition-colors inline-flex items-center gap-1.5"
        @click="emit('reset')"
      >
        <RotateCcw class="size-3.5" />
        开始新的解读
      </button>
      <div class="flex gap-2.5">
        <button
          class="px-4 py-2 text-sm border border-border rounded-xl text-text-secondary hover:bg-background hover:border-text-muted transition-all duration-200 active:scale-[0.98]"
          @click="downloadFile(activeTab)"
        >
          下载当前
        </button>
        <button
          class="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-xl font-medium hover:bg-primary-hover hover:shadow-md transition-all duration-200 active:scale-[0.98] inline-flex items-center gap-1.5"
          @click="downloadAll"
        >
          <Download class="size-3.5" />
          全部下载
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import client from '../api/client'

const props = defineProps<{
  taskId: string
  filename: string
}>()

const emit = defineEmits<{ reset: [] }>()

const tabs = [
  { key: 'report', label: '分析报告' },
  { key: 'format', label: '投标文件格式' },
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
  <div class="flex flex-col h-full">
    <!-- Tab bar -->
    <div class="flex border-b border-border bg-surface">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'px-5 py-2.5 text-sm transition-colors',
          activeTab === tab.key
            ? 'border-b-2 border-success text-success font-medium'
            : 'text-text-muted hover:text-text-secondary'
        ]"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Preview area -->
    <div class="flex-1 overflow-auto p-6 bg-surface">
      <div v-if="loading" class="text-center text-text-muted py-12">加载中...</div>
      <div v-else class="prose max-w-none" v-html="previewHtml" />
    </div>

    <!-- Bottom bar -->
    <div class="border-t border-border px-4 py-3 flex items-center justify-between bg-surface">
      <span class="text-xs text-text-muted">{{ filename }}</span>
      <div class="flex gap-2">
        <button
          class="px-4 py-2 text-sm border border-border rounded-lg text-text-secondary hover:bg-background"
          @click="downloadFile(activeTab)"
        >下载当前</button>
        <button
          class="px-4 py-2 text-sm bg-success text-white rounded-lg hover:bg-success/90"
          @click="downloadAll"
        >全部下载</button>
      </div>
    </div>

    <!-- New analysis -->
    <div class="px-4 pb-3 flex justify-end bg-surface">
      <button
        data-testid="new-analysis"
        class="text-sm text-text-muted hover:text-text-secondary"
        @click="emit('reset')"
      >
        开始新的解读
      </button>
    </div>
  </div>
</template>

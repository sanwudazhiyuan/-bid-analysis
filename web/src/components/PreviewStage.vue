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
    previewHtml.value = '<p class="text-gray-400">预览加载失败</p>'
  } finally {
    loading.value = false
  }
}

function downloadFile(fileType: string) {
  const link = document.createElement('a')
  link.href = `/api/files/${fileType}s/${props.taskId}/download`
  link.download = ''
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
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
    <div class="flex border-b border-gray-200 bg-white">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'px-5 py-2.5 text-sm transition-colors',
          activeTab === tab.key
            ? 'border-b-2 border-emerald-500 text-emerald-600 font-medium'
            : 'text-gray-400 hover:text-gray-600'
        ]"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Preview area -->
    <div class="flex-1 overflow-auto p-6 bg-white">
      <div v-if="loading" class="text-center text-gray-400 py-12">加载中...</div>
      <div v-else class="prose max-w-none" v-html="previewHtml" />
    </div>

    <!-- Bottom bar -->
    <div class="border-t border-gray-200 px-4 py-3 flex items-center justify-between bg-white">
      <span class="text-xs text-gray-400">{{ filename }}</span>
      <div class="flex gap-2">
        <button
          class="px-4 py-2 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
          @click="downloadFile(activeTab)"
        >下载当前</button>
        <button
          class="px-4 py-2 text-sm bg-emerald-500 text-white rounded-lg hover:bg-emerald-600"
          @click="downloadAll"
        >全部下载</button>
      </div>
    </div>

    <!-- New analysis -->
    <div class="px-4 pb-3 flex justify-end bg-white">
      <button
        data-testid="new-analysis"
        class="text-sm text-gray-500 hover:text-gray-700"
        @click="emit('reset')"
      >
        开始新的解读
      </button>
    </div>
  </div>
</template>

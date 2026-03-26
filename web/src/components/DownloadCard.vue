<script setup lang="ts">
import { ref } from 'vue'
import client from '../api/client'

const props = defineProps<{ taskId: string; fileType: string; label: string }>()
const downloading = ref(false)

async function download() {
  downloading.value = true
  try {
    const res = await client.get(`/tasks/${props.taskId}/download/${props.fileType}`, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    const disposition = res.headers['content-disposition']
    const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || props.label
    a.download = filename
    a.click()
    window.URL.revokeObjectURL(url)
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <div class="flex items-center justify-between bg-surface border rounded-lg px-4 py-3">
    <span class="text-sm font-medium">{{ label }}</span>
    <button @click="download" :disabled="downloading" class="text-info hover:underline text-sm disabled:opacity-50">
      {{ downloading ? '下载中...' : '下载' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { FileItem } from '../api/files'

defineProps<{
  file: FileItem
  fileType: string
  icon: string
}>()

const emit = defineEmits<{
  preview: [id: string | number]
  download: [id: string | number]
  delete: [id: string | number]
}>()

function formatSize(bytes: number | null) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <div class="bg-white border border-gray-200 rounded-lg px-4 py-3.5 flex items-center gap-3 hover:shadow-sm transition-shadow">
    <div class="w-10 h-10 bg-purple-50 rounded-lg flex items-center justify-center text-lg flex-shrink-0">
      {{ icon }}
    </div>
    <div class="flex-1 min-w-0">
      <div class="text-sm font-medium text-gray-800 truncate">{{ file.filename }}</div>
      <div class="text-xs text-gray-400 mt-0.5">
        {{ formatSize(file.file_size) }} · {{ file.created_at }} · 来源任务: {{ file.task_name }}
      </div>
    </div>
    <div class="flex gap-1.5 flex-shrink-0">
      <button
        v-if="fileType !== 'bid-documents'"
        class="px-2.5 py-1.5 text-xs border border-gray-300 rounded-md text-gray-500 hover:bg-gray-50"
        @click="emit('preview', file.id)"
      >预览</button>
      <button
        class="px-2.5 py-1.5 text-xs border border-gray-300 rounded-md text-gray-500 hover:bg-gray-50"
        @click="emit('download', file.id)"
      >下载</button>
      <button
        v-if="fileType !== 'bid-documents'"
        class="px-2.5 py-1.5 text-xs border border-red-200 rounded-md text-red-500 hover:bg-red-50"
        @click="emit('delete', file.id)"
      >删除</button>
    </div>
  </div>
</template>

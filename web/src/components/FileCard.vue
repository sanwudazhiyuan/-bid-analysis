<script setup lang="ts">
import type { FileItem } from '../api/files'

defineProps<{
  file: FileItem
  fileType: string
  icon: any
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
  <div class="bg-surface border border-border rounded-lg px-4 py-3.5 flex items-center gap-3 hover:shadow-sm transition-shadow">
    <div class="w-10 h-10 bg-primary-light rounded-lg flex items-center justify-center text-lg flex-shrink-0">
      <component :is="icon" class="size-5" />
    </div>
    <div class="flex-1 min-w-0">
      <div class="text-sm font-medium text-text-primary truncate">{{ file.filename }}</div>
      <div class="text-xs text-text-muted mt-0.5">
        {{ formatSize(file.file_size) }} · {{ file.created_at }} · 来源任务: {{ file.task_name }}
      </div>
    </div>
    <div class="flex gap-1.5 flex-shrink-0">
      <button
        class="px-2.5 py-1.5 text-xs border border-border rounded-md text-text-muted hover:bg-background"
        @click="emit('preview', file.id)"
      >预览</button>
      <button
        class="px-2.5 py-1.5 text-xs border border-border rounded-md text-text-muted hover:bg-background"
        @click="emit('download', file.id)"
      >下载</button>
      <button
        class="px-2.5 py-1.5 text-xs border border-danger/30 rounded-md text-danger hover:bg-danger-light"
        @click="emit('delete', file.id)"
      >删除</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { tasksApi } from '../api/tasks'
import { useRouter } from 'vue-router'

const router = useRouter()
const dragging = ref(false)
const uploading = ref(false)
const error = ref('')

function onDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadFile(file)
}

function onSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) uploadFile(file)
}

async function uploadFile(file: File) {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['doc', 'docx', 'pdf'].includes(ext || '')) {
    error.value = '仅支持 .doc / .docx / .pdf 文件'
    return
  }
  error.value = ''
  uploading.value = true
  try {
    const res = await tasksApi.upload(file)
    router.push(`/tasks/${res.data.id}`)
  } catch (e: unknown) {
    const axiosError = e as { response?: { data?: { detail?: string } } }
    error.value = axiosError.response?.data?.detail || '上传失败'
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div
    @dragover.prevent="dragging = true"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
    :class="['border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors',
      dragging ? 'border-primary bg-primary-light' : 'border-border hover:border-text-muted']"
  >
    <div class="text-text-muted">
      <p class="text-lg font-medium">拖拽上传招标文件</p>
      <p class="text-sm mt-1">支持 .doc / .docx / .pdf</p>
      <label class="mt-4 inline-block px-4 py-2 bg-primary text-white rounded-md hover:bg-primary-hover cursor-pointer">
        {{ uploading ? '上传中...' : '点击选择文件' }}
        <input type="file" class="hidden" accept=".doc,.docx,.pdf" @change="onSelect" :disabled="uploading" />
      </label>
    </div>
    <p v-if="error" class="text-danger text-sm mt-2">{{ error }}</p>
  </div>
</template>

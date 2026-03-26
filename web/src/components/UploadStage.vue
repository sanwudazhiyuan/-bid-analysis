<script setup lang="ts">
import { ref } from 'vue'
import { FileText } from 'lucide-vue-next'
import { useAnalysisStore } from '../stores/analysisStore'

const store = useAnalysisStore()
const dragging = ref(false)
const uploading = ref(false)

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
    store.error = '仅支持 .doc / .docx / .pdf 文件'
    return
  }
  uploading.value = true
  try {
    await store.startUpload(file)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] px-6">
    <div class="text-center max-w-lg">
      <h1 class="text-xl font-semibold text-text-primary mb-2">招标文件深度解析</h1>
      <p class="text-text-muted text-sm mb-8">上传招标文件，AI智能解析生成分析报告</p>

      <div
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
        :class="[
          'border-2 border-dashed rounded-xl p-12 transition-colors cursor-pointer bg-surface',
          dragging ? 'border-primary bg-primary-light' : 'border-border hover:border-text-muted',
        ]"
      >
        <FileText class="size-10 text-text-muted mb-3 mx-auto" />
        <p class="text-text-secondary mb-1">拖拽文件到此处，或点击上传</p>
        <p class="text-text-muted text-xs mb-4">支持 .doc / .docx / .pdf 格式</p>
        <label
          :class="[
            'inline-block px-6 py-2.5 rounded-lg text-white text-sm cursor-pointer transition-colors',
            uploading ? 'bg-primary/70' : 'bg-primary hover:bg-primary-hover',
          ]"
        >
          {{ uploading ? '上传中...' : '选择文件' }}
          <input type="file" class="hidden" accept=".doc,.docx,.pdf" @change="onSelect" :disabled="uploading" />
        </label>
      </div>

      <p v-if="store.error" class="text-danger text-sm mt-4">{{ store.error }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
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
      <h1 class="text-xl font-semibold text-gray-800 mb-2">招标文件深度解析</h1>
      <p class="text-gray-500 text-sm mb-8">上传招标文件，AI智能解析生成分析报告</p>

      <div
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
        :class="[
          'border-2 border-dashed rounded-xl p-12 transition-colors cursor-pointer bg-white',
          dragging ? 'border-purple-500 bg-purple-50' : 'border-gray-300 hover:border-gray-400',
        ]"
      >
        <div class="text-4xl mb-3">📄</div>
        <p class="text-gray-600 mb-1">拖拽文件到此处，或点击上传</p>
        <p class="text-gray-400 text-xs mb-4">支持 .doc / .docx / .pdf 格式</p>
        <label
          :class="[
            'inline-block px-6 py-2.5 rounded-lg text-white text-sm cursor-pointer transition-colors',
            uploading ? 'bg-purple-400' : 'bg-purple-600 hover:bg-purple-700',
          ]"
        >
          {{ uploading ? '上传中...' : '选择文件' }}
          <input type="file" class="hidden" accept=".doc,.docx,.pdf" @change="onSelect" :disabled="uploading" />
        </label>
      </div>

      <p v-if="store.error" class="text-red-500 text-sm mt-4">{{ store.error }}</p>
    </div>
  </div>
</template>

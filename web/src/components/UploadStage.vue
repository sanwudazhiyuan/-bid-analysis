<script setup lang="ts">
import { ref, computed } from 'vue'
import { FileText, Plus, X, Play } from 'lucide-vue-next'
import { useAnalysisStore } from '../stores/analysisStore'
import { tasksApi } from '../api/tasks'
import type { TaskFile } from '../types/task'

const store = useAnalysisStore()

interface UploadedFile {
  id: string
  filename: string
  file_size: number | null
  is_primary: boolean
  sort_order: number
}

const dragging = ref(false)
const uploading = ref(false)
const fileList = ref<UploadedFile[]>([])
const error = ref<string | null>(null)
const taskId = ref<string | null>(null)
const MAX_FILES = 4

const canUpload = computed(() => fileList.value.length < MAX_FILES)

function onDrop(e: DragEvent) {
  dragging.value = false
  const files = e.dataTransfer?.files
  if (files) uploadFiles(Array.from(files))
}

function onSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const files = input.files
  if (files) uploadFiles(Array.from(files))
}

function validateFile(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['doc', 'docx', 'pdf'].includes(ext || '')) {
    error.value = `${file.name}: 仅支持 .doc / .docx / .pdf 文件`
    return false
  }
  if (file.size > 500 * 1024 * 1024) {
    error.value = `${file.name}: 文件大小超过 500MB 限制`
    return false
  }
  return true
}

async function uploadFiles(files: File[]) {
  error.value = null

  for (const file of files) {
    if (!validateFile(file)) continue
    if (fileList.value.length >= MAX_FILES) {
      error.value = `最多上传 ${MAX_FILES} 份文件`
      break
    }

    uploading.value = true
    try {
      if (fileList.value.length === 0) {
        // First file: creates a new pending task
        const res = await tasksApi.upload(file)
        taskId.value = res.data.id
        localStorage.setItem('current_task_id', res.data.id)
        fileList.value.push({
          id: res.data.id,
          filename: res.data.filename,
          file_size: res.data.file_size,
          is_primary: true,
          sort_order: 0,
        })
      } else {
        // Additional files: append to existing task
        const res = await tasksApi.uploadFile(taskId.value!, file)
        fileList.value.push(res.data)
      }
    } catch (e: any) {
      error.value = e.response?.data?.detail || `${file.name} 上传失败`
    }
  }
  uploading.value = false
}

function removeFile(index: number) {
  if (index === 0) {
    error.value = '不能删除主文件'
    return
  }
  fileList.value.splice(index, 1)
  fileList.value.forEach((f, i) => { f.sort_order = i })
}

async function startParsing() {
  error.value = null
  if (!taskId.value || fileList.value.length === 0) return

  uploading.value = true
  try {
    await tasksApi.confirm(taskId.value)
    store.currentTaskId = taskId.value
    store.stage = 'processing'
    store.progress = 0
  } catch (e: any) {
    error.value = e.response?.data?.detail || '启动解析失败'
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] px-6">
    <div class="text-center max-w-lg w-full">
      <h1 class="text-xl font-semibold text-text-primary mb-2">招标文件深度解析</h1>
      <p class="text-text-muted text-sm mb-8">上传招标文件（最多4份），AI智能解析生成分析报告</p>

      <!-- Upload area -->
      <div
        v-if="canUpload"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
        :class="[
          'border-2 border-dashed rounded-xl p-8 transition-colors cursor-pointer bg-surface mb-4',
          dragging ? 'border-primary bg-primary-light' : 'border-border hover:border-text-muted',
        ]"
      >
        <FileText class="size-10 text-text-muted mb-3 mx-auto" />
        <p class="text-text-secondary mb-1">拖拽文件到此处，或点击上传</p>
        <p class="text-text-muted text-xs mb-4">支持 .doc / .docx / .pdf，最多 {{ MAX_FILES }} 份</p>
        <label
          :class="[
            'inline-block px-6 py-2.5 rounded-lg text-white text-sm cursor-pointer transition-colors',
            uploading ? 'bg-primary/70' : 'bg-primary hover:bg-primary-hover',
          ]"
        >
          {{ uploading ? '上传中...' : '选择文件' }}
          <input type="file" class="hidden" accept=".doc,.docx,.pdf" multiple @change="onSelect" :disabled="uploading" />
        </label>
      </div>

      <!-- File list -->
      <div v-if="fileList.length > 0" class="bg-surface rounded-xl border border-border p-4 mb-4">
        <h3 class="text-sm font-medium text-text-primary mb-3">
          已上传文件 ({{ fileList.length }}/{{ MAX_FILES }})
        </h3>
        <ul class="space-y-2">
          <li
            v-for="(f, i) in fileList"
            :key="f.id"
            class="flex items-center justify-between px-3 py-2 rounded-lg bg-background"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-xs text-text-muted shrink-0">#{{ i + 1 }}</span>
              <span class="text-sm text-text-primary truncate" :title="f.filename">{{ f.filename }}</span>
              <span v-if="f.is_primary" class="text-xs px-1.5 py-0.5 rounded bg-info-light text-info-foreground shrink-0">主文件</span>
            </div>
            <button
              v-if="i > 0"
              @click="removeFile(i)"
              class="text-text-muted hover:text-danger shrink-0 ml-2"
              :disabled="uploading"
            >
              <X class="size-4" />
            </button>
          </li>
        </ul>
      </div>

      <!-- Start parsing button -->
      <div v-if="fileList.length > 0" class="flex gap-3 justify-center mb-4">
        <label
          v-if="canUpload"
          :class="[
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm cursor-pointer transition-colors',
            uploading ? 'bg-primary/70 text-white cursor-not-allowed' : 'bg-primary hover:bg-primary-hover text-white',
          ]"
        >
          <Plus class="size-4" />
          继续添加
          <input type="file" class="hidden" accept=".doc,.docx,.pdf" multiple @change="onSelect" :disabled="uploading" />
        </label>
        <button
          @click="startParsing"
          :class="[
            'inline-flex items-center gap-2 px-6 py-2 rounded-lg text-white text-sm transition-colors',
            uploading ? 'bg-success/70 cursor-not-allowed' : 'bg-success hover:bg-success-hover',
          ]"
          :disabled="uploading"
        >
          <Play class="size-4" />
          开始解析
        </button>
      </div>

      <p v-if="error" class="text-danger text-sm mt-4">{{ error }}</p>
    </div>
  </div>
</template>

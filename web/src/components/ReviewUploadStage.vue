<script setup lang="ts">
import { ref, watch } from 'vue'
import { Search, Upload, ShieldCheck, Sparkles } from 'lucide-vue-next'
import client from '../api/client'
import { useReviewStore } from '../stores/reviewStore'

const reviewStore = useReviewStore()

// --- Bid task search ---
const searchQuery = ref('')
const searchResults = ref<Array<{ id: string; filename: string; status: string }>>([])
const searching = ref(false)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(searchQuery, (q) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!q.trim()) { searchResults.value = []; return }
  debounceTimer = setTimeout(() => searchBidTasks(q), 300)
})

async function searchBidTasks(q: string) {
  searching.value = true
  try {
    const res = await client.get('/tasks', { params: { status: 'completed', q, page_size: 5 } })
    searchResults.value = res.data.items || []
  } catch { searchResults.value = [] }
  finally { searching.value = false }
}

function selectBidTask(task: { id: string; filename: string }) {
  reviewStore.selectedBidTask = task
  searchQuery.value = task.filename
  searchResults.value = []
}

// --- Tender file upload ---
const tenderFile = ref<File | null>(null)
const dragOver = ref(false)

function handleDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file && (file.name.endsWith('.docx') || file.name.endsWith('.doc'))) {
    tenderFile.value = file
  }
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) tenderFile.value = input.files[0]
}

// --- Start review ---
const submitting = ref(false)

async function startReview() {
  if (!reviewStore.selectedBidTask || !tenderFile.value) return
  submitting.value = true
  try {
    await reviewStore.startReview(reviewStore.selectedBidTask.id, tenderFile.value)
  } catch { /* error shown via store */ }
  finally { submitting.value = false }
}
</script>

<template>
  <div class="max-w-2xl mx-auto py-8 space-y-6">
    <h2 class="text-xl font-semibold text-text-primary">标书审查</h2>

    <!-- Bid task search -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">选择招标文件</label>
      <div class="relative">
        <Search class="absolute left-3 top-2.5 size-4 text-text-muted" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索已解析的招标文件..."
          class="w-full pl-10 pr-4 py-2 border border-border rounded-lg bg-surface text-sm"
        />
        <div v-if="searchResults.length" class="absolute z-10 w-full mt-1 bg-surface border border-border rounded-lg shadow-lg">
          <button
            v-for="task in searchResults" :key="task.id"
            class="w-full px-4 py-2 text-sm text-left hover:bg-background"
            @click="selectBidTask(task)"
          >{{ task.filename }}</button>
        </div>
      </div>
      <div v-if="reviewStore.selectedBidTask" class="text-xs text-success">
        已选择: {{ reviewStore.selectedBidTask.filename }}
      </div>
    </div>

    <!-- Tender file upload -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">上传投标文件</label>
      <div
        class="border-2 border-dashed rounded-lg p-8 text-center transition-colors"
        :class="dragOver ? 'border-success bg-success/5' : 'border-border'"
        @dragover.prevent="dragOver = true"
        @dragleave="dragOver = false"
        @drop.prevent="handleDrop"
      >
        <Upload class="size-8 mx-auto text-text-muted mb-2" />
        <p class="text-sm text-text-muted">拖拽投标文件到此处，或
          <label class="text-success cursor-pointer hover:underline">
            点击选择
            <input type="file" accept=".docx,.doc" class="hidden" @change="handleFileSelect" />
          </label>
        </p>
        <p v-if="tenderFile" class="mt-2 text-sm text-text-primary">{{ tenderFile.name }}</p>
      </div>
    </div>

    <!-- Review mode selector -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">审核模式</label>
      <div class="grid grid-cols-2 gap-3">
        <button
          class="flex items-center gap-2 px-4 py-3 border rounded-lg text-sm transition-colors"
          :class="reviewStore.reviewMode === 'fixed'
            ? 'border-success bg-success/10 text-success'
            : 'border-border text-text-secondary hover:border-text-muted'"
          @click="reviewStore.reviewMode = 'fixed'"
        >
          <ShieldCheck class="size-4" />
          <div class="text-left">
            <div class="font-medium">固定审核</div>
            <div class="text-xs opacity-70">规则映射 + LLM 逐条审查</div>
          </div>
        </button>
        <button
          class="flex items-center gap-2 px-4 py-3 border rounded-lg text-sm transition-colors"
          :class="reviewStore.reviewMode === 'smart'
            ? 'border-success bg-success/10 text-success'
            : 'border-border text-text-secondary hover:border-text-muted'"
          @click="reviewStore.reviewMode = 'smart'"
        >
          <Sparkles class="size-4" />
          <div class="text-left">
            <div class="font-medium">智能审核</div>
            <div class="text-xs opacity-70">AI 智能体自主导航审查</div>
          </div>
        </button>
      </div>
    </div>

    <!-- Error -->
    <p v-if="reviewStore.error" class="text-sm text-danger">{{ reviewStore.error }}</p>

    <!-- Start button -->
    <button
      :disabled="!reviewStore.selectedBidTask || !tenderFile || submitting"
      class="w-full py-3 bg-success text-white rounded-lg font-medium disabled:opacity-50 flex items-center justify-center gap-2"
      @click="startReview"
    >
      <ShieldCheck class="size-5" />
      {{ submitting ? '提交中...' : '开始审查' }}
    </button>
  </div>
</template>

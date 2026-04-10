<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Trash2, Download, Eye } from 'lucide-vue-next'
import { reviewsApi } from '../api/reviews'
import type { ReviewTask } from '../api/reviews'

const router = useRouter()
const items = ref<ReviewTask[]>([])
const total = ref(0)
const page = ref(1)
const searchQuery = ref('')
const loading = ref(false)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => loadReviews())
watch(page, () => loadReviews())
watch(searchQuery, () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => { page.value = 1; loadReviews() }, 300)
})

async function loadReviews() {
  loading.value = true
  try {
    const res = await reviewsApi.list(page.value, 20, searchQuery.value || undefined)
    items.value = res.data.items
    total.value = res.data.total
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function viewDetail(id: string) {
  router.push({ name: 'review-detail', params: { id } })
}

async function downloadReview(id: string) {
  const res = await reviewsApi.download(id)
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url; a.download = '审查报告.docx'; a.click()
  URL.revokeObjectURL(url)
}

async function deleteReview(id: string) {
  if (!confirm('确定删除此审查记录？')) return
  await reviewsApi.delete(id)
  loadReviews()
}

function resultSummaryText(r: ReviewTask) {
  if (!r.review_summary) return '处理中'
  const s = r.review_summary
  return `通过${s.pass} 不合规${s.fail} 警告${s.warning}`
}
</script>

<template>
  <div class="p-6 space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="text-lg font-semibold text-text-primary">审查结果</h1>
      <div class="relative w-64">
        <Search class="absolute left-3 top-2.5 size-4 text-text-muted" />
        <input v-model="searchQuery" placeholder="搜索..." class="w-full pl-10 pr-4 py-2 border border-border rounded-lg text-sm" />
      </div>
    </div>

    <div v-if="loading" class="text-center text-text-muted py-12">加载中...</div>
    <div v-else-if="items.length === 0" class="text-center py-16">
      <div class="border border-dashed border-border rounded-lg p-8 text-text-muted text-sm">
        暂无审查记录，请在「标书审查」中创建审查任务
      </div>
    </div>
    <div v-else class="space-y-2">
      <div
        v-for="item in items" :key="item.id"
        class="bg-surface border border-border rounded-lg px-4 py-3 flex items-center gap-3"
      >
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium text-text-primary truncate">{{ item.bid_filename }} → {{ item.tender_filename }}</div>
          <div class="text-xs text-text-muted mt-0.5 flex items-center gap-1.5">
            <span v-if="item.review_mode === 'smart'" class="inline-block px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-[10px] font-medium">智能</span>
            <span>版本{{ item.version }} · {{ item.created_at }} · {{ resultSummaryText(item) }}</span>
          </div>
        </div>
        <div class="flex gap-1.5">
          <button class="px-2.5 py-1.5 text-xs border border-border rounded-md hover:bg-background" @click="viewDetail(item.id)">
            <Eye class="size-3.5" />
          </button>
          <button class="px-2.5 py-1.5 text-xs border border-border rounded-md hover:bg-background" @click="downloadReview(item.id)">
            <Download class="size-3.5" />
          </button>
          <button class="px-2.5 py-1.5 text-xs border border-danger/30 rounded-md text-danger hover:bg-danger-light" @click="deleteReview(item.id)">
            <Trash2 class="size-3.5" />
          </button>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="total > 20" class="flex justify-center gap-2">
      <button :disabled="page <= 1" class="px-3 py-1 text-sm border rounded" @click="page--">上一页</button>
      <span class="px-3 py-1 text-sm">{{ page }} / {{ Math.ceil(total / 20) }}</span>
      <button :disabled="page >= Math.ceil(total / 20)" class="px-3 py-1 text-sm border rounded" @click="page++">下一页</button>
    </div>
  </div>
</template>

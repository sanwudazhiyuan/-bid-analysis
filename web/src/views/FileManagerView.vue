<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { filesApi, type FileItem } from '../api/files'
import FileCard from '../components/FileCard.vue'

const props = defineProps<{ fileType: string }>()
const router = useRouter()

const items = ref<FileItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const searchQuery = ref('')
const loading = ref(false)

const typeConfig: Record<string, { title: string; icon: string }> = {
  'bid-documents': { title: '招标文件', icon: '📁' },
  reports: { title: '解析报告', icon: '📊' },
  formats: { title: '文件格式', icon: '📐' },
  checklists: { title: '资料清单', icon: '📋' },
}

const config = computed(() => typeConfig[props.fileType] || { title: props.fileType, icon: '📄' })

async function loadFiles() {
  loading.value = true
  try {
    const res = await filesApi.list(props.fileType, {
      page: page.value,
      page_size: pageSize,
      q: searchQuery.value || undefined,
    })
    items.value = res.data.items
    total.value = res.data.total
  } catch {
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

watch(() => props.fileType, () => { page.value = 1; loadFiles() })
watch(page, loadFiles)
onMounted(loadFiles)

let searchTimeout: ReturnType<typeof setTimeout>
function onSearch() {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => { page.value = 1; loadFiles() }, 300)
}

function handlePreview(id: string | number) {
  router.push(`/files/${props.fileType}/${id}/preview`)
}

async function handleDownload(id: string | number) {
  try {
    const res = await filesApi.download(props.fileType, id)
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = ''
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    // ignore
  }
}

async function handleDelete(id: string | number) {
  if (!confirm('确定删除此文件？')) return
  try {
    await filesApi.delete(props.fileType, id)
    await loadFiles()
  } catch {
    // ignore
  }
}

const totalPages = computed(() => Math.ceil(total.value / pageSize))
</script>

<template>
  <div class="h-full flex flex-col">
    <div class="px-6 py-4 bg-white border-b border-gray-200 flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold text-gray-800">{{ config.title }}</h1>
        <p class="text-xs text-gray-400 mt-0.5">共 {{ total }} 个文件</p>
      </div>
      <input
        v-model="searchQuery"
        @input="onSearch"
        class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm w-52"
        placeholder="搜索文件名..."
      />
    </div>

    <div class="flex-1 overflow-y-auto p-6">
      <div v-if="loading" class="text-center text-gray-400 py-12">加载中...</div>
      <div v-else-if="items.length === 0" class="text-center py-16">
        <div class="border border-dashed border-gray-300 rounded-lg p-8 text-gray-400 text-sm">
          暂无文件，请在「招标解读」中上传并完成解析
        </div>
      </div>
      <div v-else class="space-y-2.5">
        <FileCard
          v-for="file in items"
          :key="file.id"
          :file="file"
          :file-type="fileType"
          :icon="config.icon"
          @preview="handlePreview"
          @download="handleDownload"
          @delete="handleDelete"
        />
      </div>
    </div>

    <div v-if="totalPages > 1" class="px-6 py-3 border-t border-gray-200 bg-white flex items-center justify-between">
      <span class="text-xs text-gray-400">显示 {{ (page - 1) * pageSize + 1 }}-{{ Math.min(page * pageSize, total) }} 共 {{ total }} 条</span>
      <div class="flex gap-1">
        <button
          class="px-2.5 py-1 text-xs border border-gray-300 rounded text-gray-500 disabled:opacity-50"
          :disabled="page <= 1"
          @click="page--"
        >上一页</button>
        <button
          v-for="p in totalPages"
          :key="p"
          :class="['px-2.5 py-1 text-xs rounded', p === page ? 'bg-purple-600 text-white' : 'border border-gray-300 text-gray-500']"
          @click="page = p"
        >{{ p }}</button>
        <button
          class="px-2.5 py-1 text-xs border border-gray-300 rounded text-gray-500 disabled:opacity-50"
          :disabled="page >= totalPages"
          @click="page++"
        >下一页</button>
      </div>
    </div>
  </div>
</template>

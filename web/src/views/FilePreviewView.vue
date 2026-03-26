<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { filesApi } from '../api/files'

const props = defineProps<{ fileType: string; id: string }>()
const router = useRouter()

const html = ref('')
const filename = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const res = await filesApi.preview(props.fileType, props.id)
    html.value = res.data.html
    filename.value = res.data.filename
  } catch {
    html.value = '<p class="text-danger">预览加载失败</p>'
  } finally {
    loading.value = false
  }
})

function goBack() {
  router.push(`/files/${props.fileType}`)
}

async function download() {
  try {
    const res = await filesApi.download(props.fileType, props.id)
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = filename.value
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    // ignore
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <div class="px-6 py-3 bg-surface border-b border-border flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button class="text-text-muted hover:text-text-secondary" @click="goBack">← 返回</button>
        <span class="text-sm text-text-primary font-medium">{{ filename }}</span>
      </div>
      <button
        class="px-4 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover"
        @click="download"
      >下载</button>
    </div>
    <div class="flex-1 overflow-auto p-8 bg-surface">
      <div v-if="loading" class="text-center text-text-muted py-12">加载中...</div>
      <div v-else class="prose max-w-none" v-html="html" />
    </div>
  </div>
</template>

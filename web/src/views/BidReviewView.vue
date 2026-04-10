<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useReviewStore } from '../stores/reviewStore'
import { useSSE } from '../composables/useSSE'
import ReviewUploadStage from '../components/ReviewUploadStage.vue'
import ProcessingStage from '../components/ProcessingStage.vue'
import ReviewPreviewStage from '../components/ReviewPreviewStage.vue'

const store = useReviewStore()

const reviewSteps = [
  { key: 'indexing', label: '索引' },
  { key: 'describing', label: '图片描述' },
  { key: 'building', label: '构建文件夹' },
  { key: 'extracting', label: '条款提取' },
  { key: 'mapping', label: '条款映射' },
  { key: 'reviewing', label: '审查' },
  { key: 'generating', label: '生成报告' },
]

// Restore state on page refresh if there's an active review
onMounted(async () => {
  if (store.currentReviewId && store.stage === 'upload') {
    await store.loadReviewState()
  }
})

let sseInstance: ReturnType<typeof useSSE> | null = null

function connectSSE(reviewId: string) {
  if (sseInstance) sseInstance.disconnect()

  sseInstance = useSSE(reviewId, `/api/reviews/${reviewId}/progress`)

  watch(sseInstance.progress, (event) => {
    if (event) {
      store.handleProgressEvent(event)
    }
  })

  sseInstance.connect()
}

function disconnectSSE() {
  if (sseInstance) {
    sseInstance.disconnect()
    sseInstance = null
  }
}

watch(() => store.stage, (stage) => {
  if (stage === 'processing' && store.currentReviewId) {
    connectSSE(store.currentReviewId)
  } else if (stage !== 'processing') {
    disconnectSSE()
  }
}, { immediate: true })

onUnmounted(() => disconnectSSE())
</script>

<template>
  <div class="h-full">
    <!-- Upload stage -->
    <ReviewUploadStage v-if="store.stage === 'upload'" />

    <!-- Processing stage -->
    <ProcessingStage
      v-else-if="store.stage === 'processing'"
      :filename="'投标文件审查'"
      :progress="store.progress"
      :step="store.currentStep"
      :detail="store.detail"
      mode="processing"
      :custom-steps="reviewSteps"
      :error="store.error"
      @retry="store.currentReviewId && connectSSE(store.currentReviewId)"
    />

    <!-- Preview stage -->
    <ReviewPreviewStage v-else-if="store.stage === 'preview'" />
  </div>
</template>

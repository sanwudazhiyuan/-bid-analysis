<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useAnbiaoStore } from '../stores/anbiaoStore'
import { useSSE } from '../composables/useSSE'
import AnbiaoUploadStage from '../components/AnbiaoUploadStage.vue'
import ProcessingStage from '../components/ProcessingStage.vue'
import AnbiaoPreviewStage from '../components/AnbiaoPreviewStage.vue'

const store = useAnbiaoStore()

const anbiaoSteps = [
  { key: 'parsing_rules', label: '解析规则' },
  { key: 'parsing_tender', label: '解析标书' },
  { key: 'format_review', label: '格式审查' },
  { key: 'content_review', label: '内容审查' },
  { key: 'generating', label: '生成报告' },
]

onMounted(async () => {
  if (store.currentReviewId && store.stage === 'upload') {
    await store.loadReviewState()
  }
})

let sseInstance: ReturnType<typeof useSSE> | null = null

function connectSSE(reviewId: string) {
  if (sseInstance) sseInstance.disconnect()
  sseInstance = useSSE(reviewId, `/api/anbiao-reviews/${reviewId}/progress`)
  watch(sseInstance.progress, (event) => {
    if (event) store.handleProgressEvent(event)
  })
  sseInstance.connect()
}

function disconnectSSE() {
  if (sseInstance) { sseInstance.disconnect(); sseInstance = null }
}

watch(() => store.stage, (s) => {
  if (s === 'processing' && store.currentReviewId) connectSSE(store.currentReviewId)
  else if (s !== 'processing') disconnectSSE()
}, { immediate: true })

onUnmounted(() => disconnectSSE())
</script>

<template>
  <div class="h-full">
    <AnbiaoUploadStage v-if="store.stage === 'upload'" />
    <ProcessingStage
      v-else-if="store.stage === 'processing'"
      :filename="'暗标审查'"
      :progress="store.progress"
      :step="store.currentStep"
      :detail="store.detail"
      mode="processing"
      :custom-steps="anbiaoSteps"
      :error="store.error"
      @retry="store.currentReviewId && connectSSE(store.currentReviewId)"
    />
    <AnbiaoPreviewStage v-else-if="store.stage === 'preview'" />
  </div>
</template>
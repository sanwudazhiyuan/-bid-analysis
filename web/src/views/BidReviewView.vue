<script setup lang="ts">
import { onUnmounted, watch } from 'vue'
import { useReviewStore } from '../stores/reviewStore'
import ReviewUploadStage from '../components/ReviewUploadStage.vue'
import ReviewPreviewStage from '../components/ReviewPreviewStage.vue'

const store = useReviewStore()

// SSE connection for processing stage
let eventSource: EventSource | null = null

watch(() => store.stage, (stage) => {
  if (stage === 'processing' && store.currentReviewId) {
    connectSSE(store.currentReviewId)
  } else {
    disconnectSSE()
  }
})

function connectSSE(reviewId: string) {
  disconnectSSE()
  const token = localStorage.getItem('access_token')
  eventSource = new EventSource(
    `/api/reviews/${reviewId}/progress?token=${token}`
  )
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      store.handleProgressEvent(data)
    } catch { /* ignore parse errors */ }
  }
  eventSource.onerror = () => {
    disconnectSSE()
  }
}

function disconnectSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

onUnmounted(() => disconnectSSE())
</script>

<template>
  <div class="h-full">
    <!-- Upload stage -->
    <ReviewUploadStage v-if="store.stage === 'upload'" />

    <!-- Processing stage -->
    <div v-else-if="store.stage === 'processing'" class="flex flex-col items-center justify-center h-full gap-4">
      <div class="w-64 bg-background rounded-full h-3 overflow-hidden">
        <div
          class="h-full bg-success transition-all duration-300 rounded-full"
          :style="{ width: `${store.progress}%` }"
        />
      </div>
      <p class="text-sm text-text-secondary">{{ store.currentStep || '准备中...' }}</p>
      <p v-if="store.detail" class="text-xs text-text-muted">{{ store.detail }}</p>
      <p v-if="store.error" class="text-sm text-danger">{{ store.error }}</p>
    </div>

    <!-- Preview stage -->
    <ReviewPreviewStage v-else-if="store.stage === 'preview'" />
  </div>
</template>

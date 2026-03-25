<script setup lang="ts">
import { onMounted, onUnmounted, watch, ref } from 'vue'
import { useAnalysisStore } from '../stores/analysisStore'
import { useSSE } from '../composables/useSSE'
import { useAnnotation } from '../composables/useAnnotation'
import { tasksApi } from '../api/tasks'
import UploadStage from '../components/UploadStage.vue'
import ProcessingStage from '../components/ProcessingStage.vue'
import ReviewStage from '../components/ReviewStage.vue'
import PreviewStage from '../components/PreviewStage.vue'

const store = useAnalysisStore()
const paragraphs = ref<Array<{ index: number; text: string; style: string }>>([])
const filename = ref('')

let sseInstance: ReturnType<typeof useSSE> | null = null
let annotationHelper: ReturnType<typeof useAnnotation> | null = null

onMounted(async () => {
  if (store.currentTaskId) {
    await store.loadTaskState()
    if (store.currentTaskId) {
      await loadTaskDetails()
      if (['processing', 'generating', 'reprocessing'].includes(store.stage)) {
        connectSSE()
      }
      if (store.stage === 'review') {
        await loadReviewData()
      }
    }
  }
})

onUnmounted(() => {
  if (sseInstance) sseInstance.disconnect()
})

async function loadTaskDetails() {
  if (!store.currentTaskId) return
  try {
    const res = await tasksApi.get(store.currentTaskId)
    filename.value = res.data.filename
    store.extractedData = (res.data as any).extracted_data || null
  } catch {
    // ignore
  }
}

function connectSSE() {
  if (!store.currentTaskId) return
  if (sseInstance) sseInstance.disconnect()

  sseInstance = useSSE(store.currentTaskId)

  watch(sseInstance.progress, (event) => {
    if (event) {
      store.handleProgressEvent(event)
      if (event.step === 'review') {
        loadReviewData()
      }
    }
  })

  sseInstance.connect()
}

async function loadReviewData() {
  if (!store.currentTaskId) return
  try {
    const [taskRes, parsedRes] = await Promise.all([
      tasksApi.get(store.currentTaskId),
      tasksApi.parsed(store.currentTaskId),
    ])
    store.extractedData = (taskRes.data as any).extracted_data || null
    paragraphs.value = parsedRes.data.paragraphs
    filename.value = taskRes.data.filename

    annotationHelper = useAnnotation(store.currentTaskId)
    await annotationHelper.load()
  } catch {
    // ignore
  }
}

watch(() => store.stage, (newStage) => {
  if (['processing', 'generating', 'reprocessing'].includes(newStage)) {
    connectSSE()
  }
})

async function handleAddAnnotation(moduleKey: string, content: string) {
  if (annotationHelper) {
    await annotationHelper.add(moduleKey, moduleKey, null, content)
  }
}

async function handleRemoveAnnotation(annId: number) {
  if (annotationHelper) {
    await annotationHelper.remove(annId)
  }
}

async function handleSkipReview() {
  await store.skipReview()
}

async function handleSubmitAnnotations() {
  await store.submitAnnotations()
}

function handleReset() {
  if (sseInstance) sseInstance.disconnect()
  store.resetToUpload()
}
</script>

<template>
  <div class="h-full">
    <UploadStage v-if="store.stage === 'upload'" />

    <ProcessingStage
      v-else-if="['processing', 'generating', 'reprocessing'].includes(store.stage)"
      :filename="filename"
      :progress="store.progress"
      :step="store.currentStep"
      :detail="store.currentStep"
      :mode="store.stage as 'processing' | 'generating' | 'reprocessing'"
      :error="store.error"
      @retry="connectSSE"
    />

    <ReviewStage
      v-else-if="store.stage === 'review' && store.extractedData"
      :extracted-data="store.extractedData"
      :paragraphs="paragraphs"
      :annotations="annotationHelper?.annotations.value || []"
      :task-id="store.currentTaskId!"
      @skip="handleSkipReview"
      @submit="handleSubmitAnnotations"
      @add-annotation="handleAddAnnotation"
      @remove-annotation="handleRemoveAnnotation"
    />

    <PreviewStage
      v-else-if="store.stage === 'preview' && store.currentTaskId"
      :task-id="store.currentTaskId"
      :filename="filename"
      @reset="handleReset"
    />
  </div>
</template>

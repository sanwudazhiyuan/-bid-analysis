<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useReviewStore } from '../stores/reviewStore'
import ReviewPreviewStage from '../components/ReviewPreviewStage.vue'

const route = useRoute()
const store = useReviewStore()

onMounted(async () => {
  const reviewId = route.params.id as string
  await store.loadReviewResult(reviewId)
})
</script>

<template>
  <ReviewPreviewStage v-if="store.stage === 'preview'" />
  <div v-else class="text-center text-text-muted py-12">加载审查结果...</div>
</template>

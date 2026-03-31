import { defineStore } from 'pinia'
import { ref } from 'vue'
import { reviewsApi } from '../api/reviews'
import type { ReviewSummary, ReviewItem } from '../api/reviews'

export type ReviewStage = 'upload' | 'processing' | 'preview'

export const useReviewStore = defineStore('review', () => {
  const stage = ref<ReviewStage>('upload')
  const selectedBidTask = ref<{ id: string; filename: string } | null>(null)
  const currentReviewId = ref<string | null>(null)
  const progress = ref(0)
  const currentStep = ref('')
  const detail = ref('')
  const reviewSummary = ref<ReviewSummary | null>(null)
  const reviewItems = ref<ReviewItem[]>([])
  const error = ref<string | null>(null)

  async function startReview(bidTaskId: string, tenderFile: File) {
    error.value = null
    try {
      const res = await reviewsApi.create(bidTaskId, tenderFile)
      currentReviewId.value = res.data.id
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '创建审查任务失败'
      throw e
    }
  }

  const REVIEW_STEP_LABELS: Record<string, string> = {
    indexing: '索引',
    extracting: '条款提取',
    p0_review: '废标审查',
    p1_review: '资格审查',
    p2_review: '评分审查',
    generating: '生成报告',
  }

  function handleProgressEvent(event: { progress: number; step: string; detail?: string; error?: string }) {
    progress.value = event.progress
    currentStep.value = event.step
    detail.value = event.detail || REVIEW_STEP_LABELS[event.step] || ''
    error.value = event.error || null

    if (event.step === 'completed') {
      stage.value = 'preview'
    } else if (event.step === 'failed') {
      error.value = event.error || '审查失败'
    }
  }

  async function loadReviewResult(reviewId?: string) {
    const id = reviewId || currentReviewId.value
    if (!id) return
    currentReviewId.value = id
    try {
      const res = await reviewsApi.get(id)
      reviewSummary.value = res.data.review_summary
      reviewItems.value = res.data.review_items || []
      if (res.data.status === 'completed') {
        stage.value = 'preview'
      }
    } catch {
      error.value = '加载审查结果失败'
    }
  }

  function resetToUpload() {
    stage.value = 'upload'
    selectedBidTask.value = null
    currentReviewId.value = null
    progress.value = 0
    currentStep.value = ''
    detail.value = ''
    reviewSummary.value = null
    reviewItems.value = []
    error.value = null
  }

  return {
    stage, selectedBidTask, currentReviewId, progress, currentStep, detail,
    reviewSummary, reviewItems, error,
    startReview, handleProgressEvent, loadReviewResult, resetToUpload,
  }
})

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { anbiaoApi } from '../api/anbiao'
import type { AnbiaoFormatResult, AnbiaoContentResult, AnbiaoSummary } from '../api/anbiao'

export type AnbiaoStage = 'upload' | 'processing' | 'preview'

export const useAnbiaoStore = defineStore('anbiao', () => {
  const stage = ref<AnbiaoStage>('upload')
  const currentReviewId = ref<string | null>(localStorage.getItem('current_anbiao_id'))
  const progress = ref(0)
  const currentStep = ref('')
  const detail = ref('')
  const error = ref<string | null>(null)

  const formatResults = ref<AnbiaoFormatResult[]>([])
  const contentResults = ref<AnbiaoContentResult[]>([])
  const summary = ref<AnbiaoSummary | null>(null)

  async function startReview(tenderFile: File, ruleFile: File | null, useDefaultRules: boolean) {
    error.value = null
    try {
      const res = await anbiaoApi.create(tenderFile, ruleFile, useDefaultRules)
      currentReviewId.value = res.data.id
      localStorage.setItem('current_anbiao_id', res.data.id)
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '创建暗标审查任务失败'
      throw e
    }
  }

  const STEP_LABELS: Record<string, string> = {
    parsing_rules: '解析规则',
    parsing_tender: '解析标书',
    merging: '合并规则',
    format_review: '格式审查',
    content_review: '内容审查',
    generating: '生成报告',
  }

  function handleProgressEvent(event: { progress: number; step: string; detail?: string; error?: string }) {
    progress.value = event.progress
    currentStep.value = event.step
    detail.value = event.detail || STEP_LABELS[event.step] || ''
    error.value = event.error || null
    if (event.step === 'completed') stage.value = 'preview'
    else if (event.step === 'failed') error.value = event.error || '审查失败'
  }

  async function loadReviewState() {
    if (!currentReviewId.value) return
    try {
      const res = await anbiaoApi.get(currentReviewId.value)
      const review = res.data
      progress.value = review.progress || 0
      currentStep.value = review.current_step || ''
      formatResults.value = review.format_results || []
      contentResults.value = review.content_results || []
      summary.value = review.review_summary || null
      error.value = review.error_message || null

      const statusMap: Record<string, AnbiaoStage> = {
        pending: 'processing', indexing: 'processing', reviewing: 'processing',
        completed: 'preview', failed: 'upload',
      }
      stage.value = statusMap[review.status] || 'processing'
    } catch {
      resetToUpload()
    }
  }

  async function loadPreview() {
    if (!currentReviewId.value) return
    try {
      const res = await anbiaoApi.preview(currentReviewId.value)
      const data = res.data
      formatResults.value = data.format_results || []
      contentResults.value = data.content_results || []
      summary.value = data.summary || null
    } catch {
      // ignore — already loaded from GET endpoint
    }
  }

  function resetToUpload() {
    stage.value = 'upload'
    currentReviewId.value = null
    localStorage.removeItem('current_anbiao_id')
    progress.value = 0
    currentStep.value = ''
    detail.value = ''
    formatResults.value = []
    contentResults.value = []
    summary.value = null
    error.value = null
  }

  return {
    stage, currentReviewId, progress, currentStep, detail, error,
    formatResults, contentResults, summary,
    startReview, handleProgressEvent, loadReviewState, loadPreview, resetToUpload,
  }
})
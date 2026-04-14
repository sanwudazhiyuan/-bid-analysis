import { defineStore } from 'pinia'
import { ref } from 'vue'
import { tasksApi } from '../api/tasks'
import type { TaskFile, ProgressEvent } from '../types/task'

export type AnalysisStage = 'upload' | 'processing' | 'review' | 'reprocessing' | 'generating' | 'preview'

export const useAnalysisStore = defineStore('analysis', () => {
  const stage = ref<AnalysisStage>('upload')
  const currentTaskId = ref<string | null>(localStorage.getItem('current_task_id'))
  const progress = ref(0)
  const currentStep = ref('')
  const extractedData = ref<Record<string, any> | null>(null)
  const error = ref<string | null>(null)
  const uploadedFiles = ref<TaskFile[]>([])

  async function startUpload(file: File) {
    error.value = null
    try {
      const res = await tasksApi.upload(file)
      currentTaskId.value = res.data.id
      localStorage.setItem('current_task_id', res.data.id)
      // DON'T switch stage — stay on upload, wait for confirm
      progress.value = 0
      uploadedFiles.value = [{
        id: res.data.id,
        filename: res.data.filename,
        file_size: res.data.file_size,
        is_primary: true,
        sort_order: 0,
      }]
    } catch (e: any) {
      error.value = e.response?.data?.detail || '上传失败'
      throw e
    }
  }

  async function uploadAdditionalFile(file: File) {
    if (!currentTaskId.value) throw new Error('No active task')
    error.value = null
    try {
      const res = await tasksApi.uploadFile(currentTaskId.value, file)
      uploadedFiles.value.push(res.data)
    } catch (e: any) {
      error.value = e.response?.data?.detail || '上传失败'
      throw e
    }
  }

  function removeUploadedFile(index: number) {
    if (index === 0) throw new Error('Cannot remove primary file')
    uploadedFiles.value.splice(index, 1)
    uploadedFiles.value.forEach((f, i) => { f.sort_order = i })
  }

  async function startParsing() {
    if (!currentTaskId.value) return
    error.value = null
    try {
      await tasksApi.confirm(currentTaskId.value)
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '启动解析失败'
    }
  }

  function handleProgressEvent(event: ProgressEvent) {
    progress.value = event.progress
    currentStep.value = event.step
    error.value = event.error || null

    if (event.step === 'review') {
      stage.value = 'review'
    } else if (event.step === 'completed') {
      stage.value = 'preview'
    } else if (event.step === 'failed') {
      error.value = event.error || '处理失败'
    }
  }

  async function skipReview() {
    if (!currentTaskId.value) return
    error.value = null
    try {
      await tasksApi.continue(currentTaskId.value)
      stage.value = 'generating'
      progress.value = 90
    } catch (e: any) {
      error.value = e.response?.data?.detail || '操作失败'
    }
  }

  async function submitAnnotations() {
    if (!currentTaskId.value) return
    error.value = null
    try {
      await tasksApi.bulkReextract(currentTaskId.value)
      stage.value = 'reprocessing'
    } catch (e: any) {
      error.value = e.response?.data?.detail || '提交失败'
    }
  }

  async function loadTaskState() {
    if (!currentTaskId.value) return
    try {
      const res = await tasksApi.get(currentTaskId.value)
      const task = res.data
      extractedData.value = (task as any).extracted_data || null
      progress.value = task.progress

      const statusMap: Record<string, AnalysisStage> = {
        pending: 'upload',  // pending tasks stay in upload stage
        review: 'review',
        generating: 'generating',
        reprocessing: 'reprocessing',
        completed: 'preview',
      }
      stage.value = statusMap[task.status] || 'processing'
    } catch {
      resetToUpload()
    }
  }

  function resetToUpload() {
    stage.value = 'upload'
    currentTaskId.value = null
    progress.value = 0
    currentStep.value = ''
    extractedData.value = null
    error.value = null
    uploadedFiles.value = []
    localStorage.removeItem('current_task_id')
  }

  return {
    stage, currentTaskId, progress, currentStep, extractedData, error, uploadedFiles,
    startUpload, uploadAdditionalFile, removeUploadedFile, startParsing,
    handleProgressEvent, skipReview, submitAnnotations,
    loadTaskState, resetToUpload,
  }
})

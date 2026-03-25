import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAnalysisStore } from '../analysisStore'

vi.mock('../../api/tasks', () => ({
  tasksApi: {
    upload: vi.fn().mockResolvedValue({ data: { id: 'task-123', status: 'pending' } }),
    get: vi.fn().mockResolvedValue({ data: { id: 'task-123', status: 'review', progress: 90, extracted_data: {} } }),
    continue: vi.fn().mockResolvedValue({ data: { status: 'generating' } }),
    bulkReextract: vi.fn().mockResolvedValue({ data: { status: 'reprocessing', modules: ['module_a'] } }),
  },
}))

describe('analysisStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('starts in upload stage', () => {
    const store = useAnalysisStore()
    expect(store.stage).toBe('upload')
    expect(store.currentTaskId).toBeNull()
  })

  it('transitions to processing after upload', async () => {
    const store = useAnalysisStore()
    await store.startUpload(new File(['test'], 'test.docx'))
    expect(store.stage).toBe('processing')
    expect(store.currentTaskId).toBe('task-123')
  })

  it('persists taskId to localStorage', async () => {
    const store = useAnalysisStore()
    await store.startUpload(new File(['test'], 'test.docx'))
    expect(localStorage.getItem('current_task_id')).toBe('task-123')
  })

  it('resets to upload stage', () => {
    const store = useAnalysisStore()
    store.stage = 'preview'
    store.currentTaskId = 'task-123'
    store.resetToUpload()
    expect(store.stage).toBe('upload')
    expect(store.currentTaskId).toBeNull()
    expect(localStorage.getItem('current_task_id')).toBeNull()
  })

  it('handles SSE review event', () => {
    const store = useAnalysisStore()
    store.stage = 'processing'
    store.handleProgressEvent({ step: 'review', progress: 90 })
    expect(store.stage).toBe('review')
  })

  it('handles SSE completed event', () => {
    const store = useAnalysisStore()
    store.stage = 'generating'
    store.handleProgressEvent({ step: 'completed', progress: 100 })
    expect(store.stage).toBe('preview')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BidAnalysisView from '../BidAnalysisView.vue'

vi.mock('../../api/tasks', () => ({
  tasksApi: {
    upload: vi.fn(),
    get: vi.fn().mockResolvedValue({ data: { id: 'task-1', status: 'pending', filename: 'test.docx', progress: 0 } }),
    parsed: vi.fn().mockResolvedValue({ data: { paragraphs: [] } }),
    continue: vi.fn(),
    bulkReextract: vi.fn(),
  },
}))

vi.mock('../../api/annotations', () => ({
  annotationsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}))

vi.mock('../../composables/useSSE', () => ({
  useSSE: vi.fn(() => ({
    progress: { value: null },
    connected: { value: false },
    done: { value: false },
    connect: vi.fn(),
    disconnect: vi.fn(),
  })),
}))

describe('BidAnalysisView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('shows upload stage by default', () => {
    const wrapper = mount(BidAnalysisView)
    expect(wrapper.text()).toContain('招标文件深度解析')
  })

  it('transitions to processing stage', async () => {
    const { useAnalysisStore } = await import('../../stores/analysisStore')
    const store = useAnalysisStore()
    const wrapper = mount(BidAnalysisView)
    store.stage = 'processing'
    store.currentTaskId = 'task-1'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain('招标文件深度解析')
  })
})

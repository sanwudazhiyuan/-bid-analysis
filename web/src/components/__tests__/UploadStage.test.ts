import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import UploadStage from '../UploadStage.vue'

vi.mock('../../stores/analysisStore', () => ({
  useAnalysisStore: vi.fn(() => ({
    startUpload: vi.fn(),
    error: null,
  })),
}))

describe('UploadStage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders upload area with drag-and-drop', () => {
    const wrapper = mount(UploadStage)
    expect(wrapper.text()).toContain('招标文件深度解析')
    expect(wrapper.text()).toContain('.doc / .docx / .pdf')
  })

  it('has a file input accepting correct types', () => {
    const wrapper = mount(UploadStage)
    const input = wrapper.find('input[type="file"]')
    expect(input.exists()).toBe(true)
    expect(input.attributes('accept')).toBe('.doc,.docx,.pdf')
  })

  it('shows error message when present', async () => {
    const { useAnalysisStore } = await import('../../stores/analysisStore')
    vi.mocked(useAnalysisStore).mockReturnValue({
      startUpload: vi.fn(),
      error: '文件格式不支持',
    } as any)

    const wrapper = mount(UploadStage)
    expect(wrapper.text()).toContain('文件格式不支持')
  })
})

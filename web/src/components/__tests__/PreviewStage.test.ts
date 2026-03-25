import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PreviewStage from '../PreviewStage.vue'

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { html: '<p>Preview</p>', filename: 'test.docx' } }),
  },
}))

describe('PreviewStage', () => {
  it('renders three file tabs', () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    expect(wrapper.text()).toContain('分析报告')
    expect(wrapper.text()).toContain('投标文件格式')
    expect(wrapper.text()).toContain('资料清单')
  })

  it('has download and download-all buttons', () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    expect(wrapper.text()).toContain('下载当前')
    expect(wrapper.text()).toContain('全部下载')
  })

  it('has new analysis button', () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    expect(wrapper.text()).toContain('开始新的解读')
  })

  it('emits reset event on new analysis click', async () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    await wrapper.find('[data-testid="new-analysis"]').trigger('click')
    expect(wrapper.emitted('reset')).toBeTruthy()
  })
})

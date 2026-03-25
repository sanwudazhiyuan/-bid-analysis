import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReviewStage from '../ReviewStage.vue'

const mockExtracted = {
  schema_version: '1.0',
  modules: {
    module_a: {
      sections: [{ id: 's1', title: '基本信息', rows: [{ label: '项目名称', value: '测试项目' }] }],
    },
    module_b: {
      sections: [{ id: 's2', title: '资格要求', rows: [{ label: '要求1', value: '具有独立法人资格' }] }],
    },
  },
}

const mockParagraphs = [
  { index: 0, text: '一、项目简介', style: 'heading1' },
  { index: 1, text: '项目名称：测试项目', style: 'body' },
]

describe('ReviewStage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders module tabs', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('基本信息')
    expect(wrapper.text()).toContain('资格要求')
  })

  it('renders table data for active module', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('项目名称')
    expect(wrapper.text()).toContain('测试项目')
  })

  it('shows original text in left panel', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('一、项目简介')
  })

  it('has skip and submit buttons', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('跳过人工审核')
    expect(wrapper.text()).toContain('提交修改')
  })

  it('emits skip event', async () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    await wrapper.find('[data-testid="skip-review"]').trigger('click')
    expect(wrapper.emitted('skip')).toBeTruthy()
  })
})

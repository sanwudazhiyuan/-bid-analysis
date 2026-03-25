import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProcessingStage from '../ProcessingStage.vue'

describe('ProcessingStage', () => {
  it('renders progress bar', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 45, step: 'extracting', detail: '提取模块C', mode: 'processing' },
    })
    expect(wrapper.text()).toContain('test.docx')
    expect(wrapper.text()).toContain('45%')
  })

  it('shows step indicators', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 45, step: 'extracting', detail: '', mode: 'processing' },
    })
    expect(wrapper.text()).toContain('解析')
    expect(wrapper.text()).toContain('索引')
    expect(wrapper.text()).toContain('提取')
    expect(wrapper.text()).toContain('生成')
  })

  it('displays reprocessing mode text', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 50, step: 'reprocessing', detail: '重提取 module_a', mode: 'reprocessing' },
    })
    expect(wrapper.text()).toContain('重提取')
  })

  it('displays generating mode text', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 95, step: 'generating', detail: '生成分析报告', mode: 'generating' },
    })
    expect(wrapper.text()).toContain('生成')
  })

  it('shows error message and retry button', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: -1, step: 'failed', detail: '', mode: 'processing', error: 'API timeout' },
    })
    expect(wrapper.text()).toContain('API timeout')
  })
})

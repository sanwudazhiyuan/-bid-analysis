import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import FileManagerView from '../FileManagerView.vue'

vi.mock('../../api/files', () => ({
  filesApi: {
    list: vi.fn().mockResolvedValue({
      data: {
        items: [
          { id: '1', filename: '招标文件.docx', file_size: 1024, created_at: '2026-03-24', task_name: '招标文件' },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    }),
    delete: vi.fn().mockResolvedValue({}),
    download: vi.fn().mockResolvedValue({ data: new Blob() }),
  },
}))

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/files/:fileType', component: FileManagerView, props: true },
    { path: '/files/:fileType/:id/preview', component: { template: '<div />' } },
  ],
})

describe('FileManagerView', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await router.push('/files/bid-documents')
    await router.isReady()
  })

  it('renders file list', async () => {
    const wrapper = mount(FileManagerView, {
      props: { fileType: 'bid-documents' },
      global: { plugins: [createPinia(), router] },
    })
    await new Promise(r => setTimeout(r, 100))
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('招标文件')
  })

  it('renders search input', () => {
    const wrapper = mount(FileManagerView, {
      props: { fileType: 'bid-documents' },
      global: { plugins: [createPinia(), router] },
    })
    expect(wrapper.find('input[placeholder*="搜索"]').exists()).toBe(true)
  })
})

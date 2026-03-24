import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'
import type { PreviewData } from '../types/preview'

export const usePreviewStore = defineStore('preview', () => {
  const data = ref<PreviewData | null>(null)
  const currentModule = ref('')
  const currentSection = ref('')
  const loading = ref(false)

  async function loadPreview(taskId: string) {
    loading.value = true
    try {
      const res = await client.get<PreviewData>(`/tasks/${taskId}/preview`)
      data.value = res.data
      const modules = Object.keys(res.data.extracted_data.modules || {})
      if (modules.length) currentModule.value = modules[0]
    } finally {
      loading.value = false
    }
  }

  async function toggleCheckbox(taskId: string, moduleKey: string, sectionId: string, rowIndex: number, checked: boolean) {
    await client.put(`/tasks/${taskId}/preview/checkbox`, {
      module_key: moduleKey, section_id: sectionId, row_index: rowIndex, checked,
    })
    if (data.value) {
      const cb = data.value.checkbox_data
      if (!cb[moduleKey]) cb[moduleKey] = {}
      if (!cb[moduleKey][sectionId]) cb[moduleKey][sectionId] = {}
      cb[moduleKey][sectionId][String(rowIndex)] = checked
    }
  }

  return { data, currentModule, currentSection, loading, loadPreview, toggleCheckbox }
})

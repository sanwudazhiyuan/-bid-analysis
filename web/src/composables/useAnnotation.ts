import { ref } from 'vue'
import { annotationsApi } from '../api/annotations'
import type { Annotation } from '../types/annotation'

export function useAnnotation(taskId: string) {
  const annotations = ref<Annotation[]>([])

  async function load() {
    const res = await annotationsApi.list(taskId)
    annotations.value = res.data
  }

  async function add(moduleKey: string, sectionId: string, rowIndex: number | null, content: string) {
    const res = await annotationsApi.create(taskId, {
      module_key: moduleKey, section_id: sectionId, row_index: rowIndex ?? undefined, content
    })
    annotations.value.unshift(res.data)
  }

  async function remove(annId: number) {
    await annotationsApi.delete(taskId, annId)
    annotations.value = annotations.value.filter(a => a.id !== annId)
  }

  function getForRow(moduleKey: string, sectionId: string, rowIndex: number) {
    return annotations.value.filter(a =>
      a.module_key === moduleKey && a.section_id === sectionId && a.row_index === rowIndex
    )
  }

  function getPendingBySection() {
    const grouped: Record<string, { module_key: string; section_id: string; ids: number[] }> = {}
    for (const ann of annotations.value) {
      if (ann.status !== 'pending') continue
      const key = `${ann.module_key}:${ann.section_id}`
      if (!grouped[key]) grouped[key] = { module_key: ann.module_key, section_id: ann.section_id, ids: [] }
      grouped[key].ids.push(ann.id)
    }
    return Object.values(grouped)
  }

  return { annotations, load, add, remove, getForRow, getPendingBySection }
}

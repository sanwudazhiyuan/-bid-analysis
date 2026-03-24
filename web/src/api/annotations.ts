import client from './client'
import type { Annotation } from '../types/annotation'

export const annotationsApi = {
  list: (taskId: string) => client.get<Annotation[]>(`/tasks/${taskId}/annotations`),
  create: (taskId: string, data: { module_key: string; section_id: string; row_index?: number; content: string; annotation_type?: string }) =>
    client.post<Annotation>(`/tasks/${taskId}/annotations`, data),
  update: (taskId: string, annId: number, content: string) =>
    client.put<Annotation>(`/tasks/${taskId}/annotations/${annId}`, { content }),
  delete: (taskId: string, annId: number) =>
    client.delete(`/tasks/${taskId}/annotations/${annId}`),
  reextract: (taskId: string, data: { module_key: string; section_id: string; annotation_ids: number[] }) =>
    client.post<{ celery_task_id: string }>(`/tasks/${taskId}/reextract`, data),
}

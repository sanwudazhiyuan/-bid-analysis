import client from './client'
import type { Task, TaskFile } from '../types/task'

export const tasksApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return client.post<Task>('/tasks', form)
  },
  uploadFile: (taskId: string, file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return client.post<TaskFile>(`/tasks/${taskId}/files`, form)
  },
  getFiles: (taskId: string) =>
    client.get<{ files: TaskFile[] }>(`/tasks/${taskId}/files`),
  confirm: (id: string) =>
    client.post<{ task_id: string; status: string }>(`/tasks/${id}/confirm`),
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    client.get('/tasks', { params }),
  get: (id: string) => client.get<Task>(`/tasks/${id}`),
  delete: (id: string) => client.delete(`/tasks/${id}`),
  continue: (id: string) => client.post<{ task_id: string; status: string }>(`/tasks/${id}/continue`),
  parsed: (id: string) => client.get<{ paragraphs: Array<{ index: number; text: string; style: string; source_file?: string }> }>(`/tasks/${id}/parsed`),
  bulkReextract: (id: string) => client.post<{ task_id: string; status: string; modules: string[] }>(`/tasks/${id}/bulk-reextract`),
}

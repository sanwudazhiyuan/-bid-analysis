import client from './client'
import type { Task } from '../types/task'

export const tasksApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return client.post<Task>('/tasks', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    client.get('/tasks', { params }),
  get: (id: string) => client.get<Task>(`/tasks/${id}`),
  delete: (id: string) => client.delete(`/tasks/${id}`),
}

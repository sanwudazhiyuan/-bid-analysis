import client from './client'

export interface FileItem {
  id: string | number
  filename: string
  file_size: number | null
  created_at: string | null
  task_name: string
}

export interface FileListResponse {
  items: FileItem[]
  total: number
  page: number
  page_size: number
}

export const filesApi = {
  list: (fileType: string, params?: { page?: number; page_size?: number; q?: string }) =>
    client.get<FileListResponse>('/files', { params: { file_type: fileType, ...params } }),
  download: (fileType: string, id: string | number) =>
    client.get(`/files/${fileType}/${id}/download`, { responseType: 'blob' }),
  preview: (fileType: string, id: string | number) =>
    client.get<{ html: string; filename: string }>(`/files/${fileType}/${id}/preview`),
  delete: (fileType: string, id: string | number) =>
    client.delete(`/files/${fileType}/${id}`),
}

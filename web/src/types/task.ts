export interface TaskFile {
  id: string
  filename: string
  file_size: number | null
  is_primary: boolean
  sort_order: number
}

export interface Task {
  id: string
  filename: string
  file_size: number | null
  status: string
  current_step: string | null
  progress: number
  error_message: string | null
  extracted_data: Record<string, any> | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  files?: TaskFile[]
}

export interface ProgressEvent {
  step: string
  detail?: string
  progress: number
  current_module?: string
  modules_done?: number
  modules_total?: number
  error?: string
}

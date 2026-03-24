export interface Annotation {
  id: number
  task_id: string
  user_id: number
  module_key: string
  section_id: string
  row_index: number | null
  annotation_type: string
  content: string
  status: string
  llm_response: string | null
  created_at: string
}

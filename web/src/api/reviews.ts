import client from './client'

export interface ReviewItem {
  id: number
  source_module: string
  clause_index: number
  clause_text: string
  result: 'pass' | 'fail' | 'warning' | 'error'
  confidence: number
  reason: string
  severity: 'critical' | 'major' | 'minor'
  tender_locations: Array<{
    chapter: string
    para_indices: number[]
    text_snippet: string
  }>
}

export interface ReviewSummary {
  total: number
  pass: number
  fail: number
  warning: number
  critical_fails: number
  avg_confidence: number
  by_severity?: Record<string, { total: number; pass: number; fail: number; warning: number }>
}

export interface ReviewTask {
  id: string
  bid_task_id: string
  bid_filename: string
  tender_filename: string
  version: number
  status: string
  review_mode: 'fixed' | 'smart'
  progress: number
  current_step: string | null
  error_message: string | null
  review_summary: ReviewSummary | null
  review_items: ReviewItem[] | null
  created_at: string
}

export const reviewsApi = {
  create(bidTaskId: string, tenderFile: File, reviewMode: 'fixed' | 'smart' = 'fixed') {
    const form = new FormData()
    form.append('bid_task_id', bidTaskId)
    form.append('tender_file', tenderFile)
    form.append('review_mode', reviewMode)
    return client.post<{ id: string; status: string; version: number }>('/reviews', form)
  },
  list(page = 1, pageSize = 20, q?: string) {
    return client.get('/reviews', { params: { page, page_size: pageSize, q } })
  },
  get(id: string) {
    return client.get<ReviewTask>(`/reviews/${id}`)
  },
  delete(id: string) {
    return client.delete(`/reviews/${id}`)
  },
  preview(id: string) {
    return client.get<{ tender_html: string; review_items: ReviewItem[]; summary: ReviewSummary }>(
      `/reviews/${id}/preview`
    )
  },
  download(id: string) {
    return client.get(`/reviews/${id}/download`, { responseType: 'blob' })
  },
}

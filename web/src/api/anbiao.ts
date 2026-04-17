import client from './client'

export interface AnbiaoFormatResult {
  rule_index: number
  rule_text: string
  rule_type: 'format'
  result: 'pass' | 'fail' | 'warning' | 'error'
  reason: string
  details: Array<{ location: string; issue: string }>
  is_mandatory: boolean
}

export interface AnbiaoContentResult {
  clause_index: number
  clause_text: string
  rule_type: 'content'
  result: 'pass' | 'fail' | 'warning' | 'error'
  confidence: number
  reason: string
  is_mandatory: boolean
  tender_locations: Array<{
    global_para_indices: number[]
    text_snippet: string
    per_para_reasons: Record<number, string>
  }>
}

export interface AnbiaoSummary {
  total: number
  pass: number
  fail: number
  warning: number
  format_total: number
  content_total: number
}

export interface AnbiaoReviewTask {
  id: string
  tender_file_name: string
  rule_file_name: string | null
  status: string
  progress: number
  current_step: string | null
  error_message: string | null
  format_results: AnbiaoFormatResult[] | null
  content_results: AnbiaoContentResult[] | null
  review_summary: AnbiaoSummary | null
  created_at: string
}

export const anbiaoApi = {
  create(tenderFile: File, ruleFile: File | null, useDefaultRules: boolean = true) {
    const form = new FormData()
    form.append('tender_file', tenderFile)
    if (ruleFile) form.append('rule_file', ruleFile)
    form.append('use_default_rules', String(useDefaultRules))
    return client.post<{ id: string; status: string }>('/anbiao-reviews', form)
  },
  list(page = 1, pageSize = 20, q?: string) {
    return client.get('/anbiao-reviews', { params: { page, page_size: pageSize, q } })
  },
  get(id: string) {
    return client.get<AnbiaoReviewTask>(`/anbiao-reviews/${id}`)
  },
  delete(id: string) {
    return client.delete(`/anbiao-reviews/${id}`)
  },
  preview(id: string) {
    return client.get<{
      tender_html: string
      format_results: AnbiaoFormatResult[]
      content_results: AnbiaoContentResult[]
      summary: AnbiaoSummary
    }>(`/anbiao-reviews/${id}/preview`)
  },
  download(id: string) {
    return client.get(`/anbiao-reviews/${id}/download`, { responseType: 'blob' })
  },
}
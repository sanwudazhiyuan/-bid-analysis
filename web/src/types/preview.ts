export interface Section {
  id: string
  title: string
  type: string
  columns?: string[]
  rows?: string[][]
  content?: string
  note?: string
  sections?: Section[]
}

export interface Module {
  title: string
  sections: Section[]
  status?: string
  error?: string
}

export interface PreviewData {
  extracted_data: {
    modules: Record<string, Module | null>
  }
  checkbox_data: Record<string, Record<string, Record<string, boolean>>>
}

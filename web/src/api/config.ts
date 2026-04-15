import client from './client'

export interface OllamaLlmConfig {
  server_url: string
  model_name: string
  context_length: number | null
  context_length_manual: boolean
  temperature: number
  max_output_tokens: number
  retry: number
  timeout: number
}

export interface OllamaEmbeddingConfig {
  server_url: string
  model_name: string
  context_length: number | null
  context_length_manual: boolean
  dimensions: number | null
  dimensions_manual: boolean
  batch_size: number | null
}

export interface OllamaHahaCodeConfig {
  anthropic_base_url: string
  anthropic_model: string
  anthropic_sonnet_model: string
  anthropic_haiku_model: string
  anthropic_auth_token: string
}

export interface CloudConfig {
  api: Record<string, any>
  embedding: Record<string, any>
  haha_code: Record<string, any>
}

export interface SystemConfig {
  mode: string
  cloud_config: CloudConfig
  local_llm_config: OllamaLlmConfig | null
  local_embedding_config: OllamaEmbeddingConfig | null
  local_haha_code_config: OllamaHahaCodeConfig | null
  updated_at: string | null
  updated_by: number | null
}

export const configApi = {
  getConfig: () => client.get<SystemConfig>('/admin/config'),

  updateConfig: (data: Partial<SystemConfig>) => client.put<SystemConfig>('/admin/config', data),

  listOllamaModels: (serverUrl: string) =>
    client.get<{ models: string[] }>('/admin/config/ollama/models', { params: { server_url: serverUrl } }),

  getOllamaModelInfo: (serverUrl: string, model: string) =>
    client.get<{ context_length: number | null; dimensions: number | null }>('/admin/config/ollama/info', {
      params: { server_url: serverUrl, model },
    }),

  testOllamaConnection: (serverUrl: string, model?: string) =>
    client.get<{ connected: boolean; models: string[]; error?: string }>('/admin/config/ollama/test', {
      params: { server_url: serverUrl, model },
    }),
}
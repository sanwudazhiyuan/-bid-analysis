<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { configApi, type SystemConfig } from '../api/config'

const loading = ref(false)
const saving = ref(false)
const config = reactive<SystemConfig>({
  mode: 'cloud',
  cloud_config: { api: {}, embedding: {}, haha_code: {} },
  local_llm_config: null,
  local_embedding_config: null,
  local_haha_code_config: null,
  updated_at: null,
  updated_by: null,
})

// LLM state
const llmServerUrl = ref('http://10.165.25.39:11434')
const llmModels = ref<string[]>([])
const llmConnected = ref<'unknown' | 'connected' | 'error'>('unknown')
const llmModelInfoLoading = ref(false)

// Embedding state
const embServerUrl = ref('http://10.165.44.28:11434')
const embModels = ref<string[]>([])
const embConnected = ref<'unknown' | 'connected' | 'error'>('unknown')

// Dimension change warning
const dimensionWarning = ref(false)

// Ensure local configs exist when switching to local mode
function ensureLocalConfigs() {
  if (!config.local_llm_config) {
    config.local_llm_config = {
      server_url: llmServerUrl.value,
      model_name: '',
      context_length: null,
      context_length_manual: false,
      temperature: 0.1,
      max_output_tokens: 8192,
      retry: 3,
      timeout: 600,
    }
  }
  if (!config.local_embedding_config) {
    config.local_embedding_config = {
      server_url: embServerUrl.value,
      model_name: '',
      context_length: null,
      context_length_manual: false,
      dimensions: null,
      dimensions_manual: false,
      batch_size: null,
    }
  }
  if (!config.local_haha_code_config) {
    config.local_haha_code_config = {
      anthropic_base_url: llmServerUrl.value.replace(/\/+$/, '') + '/v1',
      anthropic_model: '',
      anthropic_sonnet_model: '',
      anthropic_haiku_model: '',
      anthropic_auth_token: 'ollama',
    }
  }
}

async function loadConfig() {
  loading.value = true
  try {
    const res = await configApi.getConfig()
    Object.assign(config, res.data)
    if (config.local_llm_config) {
      llmServerUrl.value = config.local_llm_config.server_url
    }
    if (config.local_embedding_config) {
      embServerUrl.value = config.local_embedding_config.server_url
    }
  } finally {
    loading.value = false
  }
}

async function testLlmConnection() {
  llmConnected.value = 'unknown'
  try {
    const res = await configApi.testOllamaConnection(llmServerUrl.value)
    if (res.data.connected) {
      llmConnected.value = 'connected'
      llmModels.value = res.data.models
    } else {
      llmConnected.value = 'error'
    }
  } catch {
    llmConnected.value = 'error'
  }
}

async function testEmbConnection() {
  embConnected.value = 'unknown'
  try {
    const res = await configApi.testOllamaConnection(embServerUrl.value)
    if (res.data.connected) {
      embConnected.value = 'connected'
      embModels.value = res.data.models
    } else {
      embConnected.value = 'error'
    }
  } catch {
    embConnected.value = 'error'
  }
}

async function onLlmModelChange(modelName: string) {
  llmModelInfoLoading.value = true
  try {
    const res = await configApi.getOllamaModelInfo(llmServerUrl.value, modelName)
    if (config.local_llm_config) {
      if (res.data.context_length) {
        config.local_llm_config.context_length = res.data.context_length
        config.local_llm_config.context_length_manual = false
      }
    }
    // Also update haha-code config when LLM model changes
    if (config.local_haha_code_config) {
      const base = llmServerUrl.value.replace(/\/+$/, '') + '/v1'
      config.local_haha_code_config.anthropic_base_url = base
      config.local_haha_code_config.anthropic_model = modelName
      config.local_haha_code_config.anthropic_sonnet_model = modelName
    }
  } finally {
    llmModelInfoLoading.value = false
  }
}

async function onEmbModelChange(modelName: string) {
  try {
    const res = await configApi.getOllamaModelInfo(embServerUrl.value, modelName)
    if (config.local_embedding_config) {
      if (res.data.context_length) {
        config.local_embedding_config.context_length = res.data.context_length
        config.local_embedding_config.context_length_manual = false
      }
      if (res.data.dimensions) {
        const oldDim = config.local_embedding_config.dimensions
        if (oldDim && oldDim !== res.data.dimensions) {
          dimensionWarning.value = true
        }
        config.local_embedding_config.dimensions = res.data.dimensions
        config.local_embedding_config.dimensions_manual = false
      }
      // Recalculate batch_size
      if (config.local_embedding_config.context_length) {
        const available = config.local_embedding_config.context_length - 200
        config.local_embedding_config.batch_size = Math.max(1, Math.min(50, Math.floor(available / 500)))
      }
    }
  } catch {}
}

async function saveConfig() {
  if (dimensionWarning.value) {
    if (!confirm('嵌入维度变更将导致所有已有索引失效，需要重新解析和索引所有招标文件。是否继续？')) {
      return
    }
  }
  saving.value = true
  try {
    await configApi.updateConfig(config)
    dimensionWarning.value = false
    alert('配置已生效')
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-xl font-bold">模型配置</h1>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="text-center text-text-muted py-12">加载中...</div>

    <template v-if="!loading">
      <!-- Mode Switch -->
      <div class="bg-surface p-4 rounded-lg shadow mb-6">
        <div class="text-xs text-text-muted uppercase mb-3">运行模式</div>
        <div class="flex gap-4">
          <button
            @click="config.mode = 'cloud'"
            :class="config.mode === 'cloud' ? 'bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium' : 'border border-border px-4 py-2 rounded-md text-sm text-text-secondary hover:bg-background'"
          >云端模式 (DashScope)</button>
          <button
            @click="config.mode = 'local'; ensureLocalConfigs()"
            :class="config.mode === 'local' ? 'bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium' : 'border border-border px-4 py-2 rounded-md text-sm text-text-secondary hover:bg-background'"
          >本地模式 (Ollama)</button>
        </div>
      </div>

      <!-- Cloud mode summary (shown when cloud) -->
      <div v-if="config.mode === 'cloud'" class="bg-surface p-4 rounded-lg shadow mb-6">
        <div class="text-xs text-text-muted uppercase mb-3">当前云端配置</div>
        <div class="text-sm text-text-secondary space-y-1">
          <p>LLM 模型: {{ config.cloud_config?.api?.model || '-' }}</p>
          <p>Embedding 模型: {{ config.cloud_config?.embedding?.model || '-' }}</p>
          <p>API 地址: {{ config.cloud_config?.api?.base_url || '-' }}</p>
        </div>
      </div>

      <!-- Local mode config blocks (shown when local) -->
      <template v-if="config.mode === 'local'">
        <!-- LLM Config -->
        <div class="bg-surface p-4 rounded-lg shadow mb-6 space-y-3">
          <div class="text-xs text-text-muted uppercase">LLM 大语言模型</div>
          <div class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">服务器地址</span>
            <input v-model="llmServerUrl" @change="config.local_llm_config!.server_url = llmServerUrl" class="flex-1 border rounded px-3 py-2 text-sm" placeholder="http://10.165.25.39:11434" />
            <button @click="testLlmConnection" class="px-3 py-2 bg-primary text-primary-foreground rounded text-sm">连接测试</button>
            <span v-if="llmConnected === 'connected'" class="text-sm text-success">&#10003; 已连接</span>
            <span v-if="llmConnected === 'error'" class="text-sm text-danger">&#10007; 连接失败</span>
          </div>
          <div v-if="llmModels.length" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">模型选择</span>
            <select v-model="config.local_llm_config!.model_name" @change="onLlmModelChange(config.local_llm_config!.model_name)" class="flex-1 border rounded px-3 py-2 text-sm">
              <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
            </select>
            <span class="text-xs text-text-muted">已拉取 {{ llmModels.length }} 个可用模型</span>
          </div>
          <div v-if="config.local_llm_config?.context_length" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">上下文长度</span>
            <span class="text-sm text-success">{{ config.local_llm_config.context_length }} (自动获取)</span>
          </div>
          <div v-if="!config.local_llm_config?.context_length && config.mode === 'local'" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">上下文长度</span>
            <input type="number" v-model.number="config.local_llm_config!.context_length" class="flex-1 border rounded px-3 py-2 text-sm" placeholder="手动填写" />
            <span class="text-xs text-warning">手动设定</span>
          </div>
          <div class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">最大输出 Tokens</span>
            <input type="number" v-model.number="config.local_llm_config!.max_output_tokens" class="flex-1 border rounded px-3 py-2 text-sm" />
          </div>
          <div class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">Temperature</span>
            <input type="number" v-model.number="config.local_llm_config!.temperature" step="0.1" class="flex-1 border rounded px-3 py-2 text-sm" />
          </div>
        </div>

        <!-- Embedding Config -->
        <div class="bg-surface p-4 rounded-lg shadow mb-6 space-y-3">
          <div class="text-xs text-text-muted uppercase">Embedding 嵌入模型</div>
          <div class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">服务器地址</span>
            <input v-model="embServerUrl" @change="config.local_embedding_config!.server_url = embServerUrl" class="flex-1 border rounded px-3 py-2 text-sm" placeholder="http://10.165.44.28:11434" />
            <button @click="testEmbConnection" class="px-3 py-2 bg-primary text-primary-foreground rounded text-sm">连接测试</button>
            <span v-if="embConnected === 'connected'" class="text-sm text-success">&#10003; 已连接</span>
            <span v-if="embConnected === 'error'" class="text-sm text-danger">&#10007; 连接失败</span>
          </div>
          <div v-if="embModels.length" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">模型选择</span>
            <select v-model="config.local_embedding_config!.model_name" @change="onEmbModelChange(config.local_embedding_config!.model_name)" class="flex-1 border rounded px-3 py-2 text-sm">
              <option v-for="m in embModels" :key="m" :value="m">{{ m }}</option>
            </select>
            <span class="text-xs text-text-muted">已拉取 {{ embModels.length }} 个可用模型</span>
          </div>
          <div v-if="config.local_embedding_config?.context_length" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">上下文长度</span>
            <span class="text-sm text-success">{{ config.local_embedding_config.context_length }} (自动获取)</span>
          </div>
          <div v-if="!config.local_embedding_config?.context_length && config.mode === 'local'" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">上下文长度</span>
            <input type="number" v-model.number="config.local_embedding_config!.context_length" class="flex-1 border rounded px-3 py-2 text-sm" />
            <span class="text-xs text-warning">手动设定</span>
          </div>
          <div v-if="config.local_embedding_config?.dimensions" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">嵌入维度</span>
            <span class="text-sm text-success">{{ config.local_embedding_config.dimensions }} (自动获取)</span>
          </div>
          <div v-if="!config.local_embedding_config?.dimensions && config.mode === 'local'" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">嵌入维度</span>
            <input type="number" v-model.number="config.local_embedding_config!.dimensions" class="flex-1 border rounded px-3 py-2 text-sm" />
            <span class="text-xs text-warning">手动设定</span>
          </div>
          <div v-if="config.local_embedding_config?.batch_size" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-24">Batch Size</span>
            <span class="text-sm text-success">{{ config.local_embedding_config.batch_size }} (动态计算)</span>
          </div>
        </div>

        <!-- Smart Review Config -->
        <div class="bg-surface p-4 rounded-lg shadow mb-6 space-y-3">
          <div class="text-xs text-text-muted uppercase">Smart Review (haha-code)</div>
          <div class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-28">Anthropic 端点</span>
            <span class="text-sm">{{ config.local_haha_code_config?.anthropic_base_url || '-' }}</span>
          </div>
          <div v-if="llmModels.length" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-28">Sonnet 模型</span>
            <select v-model="config.local_haha_code_config!.anthropic_sonnet_model" class="flex-1 border rounded px-3 py-2 text-sm">
              <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
            </select>
            <span class="text-xs text-text-muted">主力审评模型</span>
          </div>
          <div v-if="llmModels.length" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-28">Haiku 模型</span>
            <select v-model="config.local_haha_code_config!.anthropic_haiku_model" class="flex-1 border rounded px-3 py-2 text-sm">
              <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
            </select>
            <span class="text-xs text-text-muted">轻量快速模型</span>
          </div>
          <div v-if="llmModels.length" class="flex gap-3 items-center">
            <span class="text-sm text-text-secondary w-28">默认模型</span>
            <select v-model="config.local_haha_code_config!.anthropic_model" class="flex-1 border rounded px-3 py-2 text-sm">
              <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
            </select>
            <span class="text-xs text-text-muted">haha-code 主模型</span>
          </div>
        </div>

        <!-- Dimension change warning -->
        <div v-if="dimensionWarning" class="bg-warning-light border border-warning p-3 rounded-lg mb-6">
          <span class="text-sm text-warning-foreground">&#9888; 嵌入维度变更将导致所有已有索引失效，需要重新解析和索引所有招标文件。</span>
        </div>
      </template>

      <!-- Save button -->
      <div class="text-center">
        <button @click="saveConfig" :disabled="saving" class="px-6 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary-hover disabled:opacity-50">
          {{ saving ? '保存中...' : '保存配置' }}
        </button>
      </div>
    </template>
  </div>
</template>
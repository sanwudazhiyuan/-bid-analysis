<script setup lang="ts">
import { FileText } from 'lucide-vue-next'

const defaultSteps = [
  { key: 'parsing', label: '解析' },
  { key: 'indexing', label: '索引' },
  { key: 'embedding', label: '向量' },
  { key: 'extracting', label: '提取' },
  { key: 'generating', label: '生成' },
]

const props = defineProps<{
  filename: string
  progress: number
  step: string
  detail: string
  mode: 'processing' | 'reprocessing' | 'generating'
  error?: string | null
  customSteps?: Array<{ key: string; label: string }>
}>()

const emit = defineEmits<{
  retry: []
}>()

const steps = props.customSteps || defaultSteps

const modeLabels = {
  processing: '处理中',
  reprocessing: '修改中',
  generating: '生成中',
}

function stepStatus(stepKey: string) {
  const order = steps.map(s => s.key)
  const stepIdx = order.indexOf(stepKey)

  // 尝试多种匹配方式找到当前步骤索引
  let currentIdx = order.indexOf(props.step)

  // 方法1: 用 step label 反向匹配（如"索引"→"indexing"）
  if (currentIdx === -1 && props.step) {
    const matchIdx = steps.findIndex(s =>
      s.label === props.step || props.step.includes(s.label),
    )
    if (matchIdx !== -1) currentIdx = matchIdx
  }

  // 方法2: 关键词匹配
  if (currentIdx === -1 && props.step) {
    const keywordMap: Record<string, string> = {
      '索引': 'indexing',
      '图片': 'describing',
      '构建': 'building',
      '提取': 'extracting',
      '映射': 'mapping',
      '审查': 'reviewing',
      '生成': 'generating',
    }
    for (const [kw, key] of Object.entries(keywordMap)) {
      if (props.step.includes(kw)) {
        const idx = steps.findIndex(s => s.key === key)
        if (idx !== -1) { currentIdx = idx; break }
      }
    }
  }

  // 方法3: 进度推断 fallback
  if (currentIdx === -1) {
    let activeByProgress = 0
    if (props.progress >= 95) activeByProgress = steps.findIndex(s => s.key === 'generating')
    else if (props.progress >= 15) activeByProgress = steps.findIndex(s => s.key === 'reviewing')
    else if (props.progress >= 13) activeByProgress = steps.findIndex(s => s.key === 'building')
    else if (props.progress >= 12) activeByProgress = steps.findIndex(s => s.key === 'describing')
    else if (props.progress >= 11) activeByProgress = steps.findIndex(s => s.key === 'mapping')
    else if (props.progress >= 10) activeByProgress = steps.findIndex(s => s.key === 'extracting')
    else activeByProgress = steps.findIndex(s => s.key === 'indexing')
    if (activeByProgress < 0) activeByProgress = 0
    currentIdx = activeByProgress
  }

  if (stepIdx < currentIdx) return 'done'
  if (stepIdx === currentIdx) return 'active'
  return 'pending'
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] px-6">
    <div class="w-full max-w-lg bg-surface rounded-xl border border-border p-6">
      <div class="flex items-center gap-2 mb-4">
        <FileText class="size-4 text-text-primary" />
        <span class="text-sm text-text-primary">{{ filename }}</span>
        <span class="text-xs px-2 py-0.5 rounded bg-warning-light text-warning-foreground">{{ modeLabels[mode] }}</span>
      </div>

      <div class="bg-border rounded-full h-2 mb-2">
        <div
          class="bg-gradient-to-r from-primary to-info h-full rounded-full transition-all duration-300"
          :style="{ width: `${Math.max(0, progress)}%` }"
        />
      </div>

      <div class="flex justify-between text-xs text-text-muted mb-4">
        <span>{{ detail || step }}</span>
        <span>{{ Math.max(0, progress) }}%</span>
      </div>

      <div v-if="mode === 'processing'" class="flex gap-2 mt-4">
        <div
          v-for="s in steps"
          :key="s.key"
          :class="[
            'text-xs px-3 py-1 rounded',
            stepStatus(s.key) === 'done' ? 'bg-success-light text-success-foreground' :
            stepStatus(s.key) === 'active' ? 'bg-warning-light text-warning-foreground' :
            'bg-background text-text-muted'
          ]"
        >
          {{ s.label }}
        </div>
      </div>

      <div v-if="error" class="mt-4 p-3 bg-danger-light border border-danger/30 rounded-lg">
        <p class="text-sm text-danger">{{ error }}</p>
        <button
          class="mt-2 text-sm text-danger underline hover:text-danger-foreground"
          @click="emit('retry')"
        >
          重试
        </button>
      </div>
    </div>
  </div>
</template>

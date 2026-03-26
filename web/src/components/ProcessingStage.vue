<script setup lang="ts">
import { FileText } from 'lucide-vue-next'

const props = defineProps<{
  filename: string
  progress: number
  step: string
  detail: string
  mode: 'processing' | 'reprocessing' | 'generating'
  error?: string | null
}>()

const emit = defineEmits<{
  retry: []
}>()

const steps = [
  { key: 'parsing', label: '解析' },
  { key: 'indexing', label: '索引' },
  { key: 'extracting', label: '提取' },
  { key: 'generating', label: '生成' },
]

const modeLabels = {
  processing: '解析中',
  reprocessing: '修改中',
  generating: '生成中',
}

function stepStatus(stepKey: string) {
  const order = steps.map(s => s.key)
  const currentIdx = order.indexOf(props.step)
  const stepIdx = order.indexOf(stepKey)
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

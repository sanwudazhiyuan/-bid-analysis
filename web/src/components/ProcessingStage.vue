<script setup lang="ts">
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
    <div class="w-full max-w-lg bg-white rounded-xl border border-gray-200 p-6">
      <div class="flex items-center gap-2 mb-4">
        <span class="text-sm text-gray-800">📄 {{ filename }}</span>
        <span class="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-700">{{ modeLabels[mode] }}</span>
      </div>

      <div class="bg-gray-200 rounded-full h-2 mb-2">
        <div
          class="bg-gradient-to-r from-purple-600 to-purple-400 h-full rounded-full transition-all duration-300"
          :style="{ width: `${Math.max(0, progress)}%` }"
        />
      </div>

      <div class="flex justify-between text-xs text-gray-400 mb-4">
        <span>{{ detail || step }}</span>
        <span>{{ Math.max(0, progress) }}%</span>
      </div>

      <div v-if="mode === 'processing'" class="flex gap-2 mt-4">
        <div
          v-for="s in steps"
          :key="s.key"
          :class="[
            'text-xs px-3 py-1 rounded',
            stepStatus(s.key) === 'done' ? 'bg-green-100 text-green-700' :
            stepStatus(s.key) === 'active' ? 'bg-amber-100 text-amber-700' :
            'bg-gray-100 text-gray-400'
          ]"
        >
          {{ s.label }}
        </div>
      </div>

      <div v-if="error" class="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
        <p class="text-sm text-red-600">{{ error }}</p>
        <button
          class="mt-2 text-sm text-red-600 underline hover:text-red-800"
          @click="emit('retry')"
        >
          重试
        </button>
      </div>
    </div>
  </div>
</template>

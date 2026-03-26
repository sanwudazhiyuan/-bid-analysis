<script setup lang="ts">
import { watch, onMounted } from 'vue'
import { useSSE } from '../composables/useSSE'

const props = defineProps<{ taskId: string }>()
const emit = defineEmits<{ completed: [] }>()
const { progress, connect, done } = useSSE(props.taskId)

onMounted(connect)

const steps = [
  { key: 'parsing', label: '文档解析' },
  { key: 'indexing', label: '智能索引' },
  { key: 'extracting', label: '结构提取' },
  { key: 'generating', label: '文档生成' },
]

function stepStatus(stepKey: string) {
  if (!progress.value) return 'pending'
  const order = steps.map(s => s.key)
  const currentIdx = order.indexOf(progress.value.step)
  const thisIdx = order.indexOf(stepKey)
  if (progress.value.step === 'completed') return 'done'
  if (progress.value.step === 'failed') return thisIdx <= currentIdx ? 'failed' : 'pending'
  if (thisIdx < currentIdx) return 'done'
  if (thisIdx === currentIdx) return 'active'
  return 'pending'
}

watch(() => progress.value?.step, (step) => {
  if (step === 'completed') emit('completed')
})

// suppress unused warning for done
void done
</script>

<template>
  <div class="space-y-4">
    <div class="w-full bg-border rounded-full h-3">
      <div class="bg-info h-3 rounded-full transition-all duration-500"
        :style="{ width: `${Math.max(progress?.progress || 0, 0)}%` }"></div>
    </div>
    <p class="text-sm text-text-muted text-right">{{ progress?.progress || 0 }}%</p>

    <div class="space-y-3">
      <div v-for="step in steps" :key="step.key" class="flex items-center gap-3">
        <span v-if="stepStatus(step.key) === 'done'" class="text-success">&#10003;</span>
        <span v-else-if="stepStatus(step.key) === 'active'" class="text-info animate-pulse">&#9679;</span>
        <span v-else-if="stepStatus(step.key) === 'failed'" class="text-danger">&#10007;</span>
        <span v-else class="text-border">&#9675;</span>
        <span :class="stepStatus(step.key) === 'active' ? 'font-medium' : 'text-text-muted'">{{ step.label }}</span>
        <span v-if="stepStatus(step.key) === 'active' && progress?.detail" class="text-sm text-text-muted ml-2">
          {{ progress.detail }}
        </span>
      </div>
    </div>

    <div v-if="progress?.step === 'failed'" class="bg-danger-light text-danger-foreground p-3 rounded-md text-sm mt-4">
      {{ progress.error || '分析失败' }}
    </div>
  </div>
</template>

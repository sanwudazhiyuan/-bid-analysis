<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Annotation } from '../types/annotation'

const props = defineProps<{
  extractedData: Record<string, any>
  paragraphs: Array<{ index: number; text: string; style: string }>
  annotations: Annotation[]
  taskId: string
}>()

const emit = defineEmits<{
  skip: []
  submit: []
  addAnnotation: [moduleKey: string, content: string]
  removeAnnotation: [annId: number]
}>()

const moduleKeys = computed(() => Object.keys(props.extractedData?.modules || {}))
const activeModule = ref(moduleKeys.value[0] || '')
const showAnnotationInput = ref<string | null>(null)
const annotationText = ref('')

const MODULE_LABELS: Record<string, string> = {
  module_a: 'A 基本信息', module_b: 'B 资格要求', module_c: 'C 评标办法',
  module_d: 'D 废标条款', module_e: 'E 投标要求', module_f: 'F 合同条款',
  module_g: 'G 其他', bid_format: '投标文件格式', checklist: '资料清单',
}

const currentModuleData = computed(() => {
  return props.extractedData?.modules?.[activeModule.value] || {}
})

const moduleAnnotations = computed(() => {
  return props.annotations.filter(a => a.module_key === activeModule.value && a.status === 'pending')
})

const pendingCount = computed(() => {
  return props.annotations.filter(a => a.status === 'pending').length
})

function hasAnnotations(key: string) {
  return props.annotations.some(a => a.module_key === key && a.status === 'pending')
}

function startAnnotation(moduleKey: string) {
  showAnnotationInput.value = moduleKey
  annotationText.value = ''
}

function submitAnnotation() {
  if (annotationText.value.trim() && showAnnotationInput.value) {
    emit('addAnnotation', showAnnotationInput.value, annotationText.value.trim())
    annotationText.value = ''
    showAnnotationInput.value = null
  }
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left panel: original text (1/3) -->
    <div class="w-1/3 min-w-[320px] border-r border-border bg-background flex flex-col">
      <div class="px-3 py-2.5 border-b border-border bg-surface text-sm font-medium text-text-muted">
        招标原文
      </div>
      <div class="flex-1 overflow-y-auto p-3 text-sm text-text-secondary leading-relaxed">
        <p
          v-for="p in paragraphs"
          :key="p.index"
          :class="p.style?.includes('heading') ? 'font-semibold text-text-primary mt-3 mb-1' : 'mb-1 text-text-muted'"
        >
          {{ p.text }}
        </p>
      </div>
    </div>

    <!-- Right panel: extracted data (2/3) -->
    <div class="flex-1 flex flex-col">
      <!-- Module tabs -->
      <div class="flex border-b border-border bg-surface overflow-x-auto">
        <button
          v-for="key in moduleKeys"
          :key="key"
          @click="activeModule = key"
          :class="[
            'px-4 py-2.5 text-sm whitespace-nowrap relative transition-colors',
            activeModule === key
              ? 'border-b-2 border-primary text-primary font-medium'
              : 'text-text-muted hover:text-text-secondary'
          ]"
        >
          {{ MODULE_LABELS[key] || key }}
          <span
            v-if="hasAnnotations(key)"
            class="absolute top-1.5 right-1 w-1.5 h-1.5 bg-warning rounded-full"
          />
        </button>
      </div>

      <!-- Content area -->
      <div class="flex-1 overflow-y-auto p-4 bg-background">
        <div
          :class="[
            'bg-surface rounded-lg overflow-hidden mb-4',
            moduleAnnotations.length > 0
              ? 'border border-warning shadow-sm'
              : 'border border-border'
          ]"
        >
          <!-- Table header for annotated modules -->
          <div
            v-if="moduleAnnotations.length > 0"
            class="px-3 py-2 bg-warning-light flex items-center justify-between"
          >
            <span class="text-sm font-medium text-warning-foreground">
              {{ MODULE_LABELS[activeModule] || activeModule }}
            </span>
            <span class="text-xs bg-warning text-white px-2 py-0.5 rounded-full">
              {{ moduleAnnotations.length }}条批注
            </span>
          </div>

          <!-- Table content -->
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-background">
                <th class="px-3 py-2 text-left text-text-muted font-medium border-b border-border w-[30%]">字段</th>
                <th class="px-3 py-2 text-left text-text-muted font-medium border-b border-border">内容</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="currentModuleData?.sections">
                <template v-for="section in currentModuleData.sections" :key="section.id">
                  <tr v-for="(row, ri) in (section.rows || [])" :key="ri" class="border-b border-border/50">
                    <td class="px-3 py-2 text-text-secondary font-medium">{{ Array.isArray(row) ? row[0] : (row.label || row.key || '') }}</td>
                    <td class="px-3 py-2 text-text-secondary">{{ Array.isArray(row) ? row.slice(1).join(' | ') : (row.value || '') }}</td>
                  </tr>
                </template>
              </template>
              <template v-else>
                <tr v-for="(value, key) in currentModuleData" :key="key" class="border-b border-border/50">
                  <td class="px-3 py-2 text-text-secondary font-medium">{{ key }}</td>
                  <td class="px-3 py-2 text-text-secondary">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</td>
                </tr>
              </template>
            </tbody>
          </table>

          <!-- Annotations for this module -->
          <div v-if="moduleAnnotations.length > 0" class="border-t border-warning/30 bg-warning-light p-3">
            <div
              v-for="ann in moduleAnnotations"
              :key="ann.id"
              class="flex gap-2 items-start mb-2 last:mb-0"
            >
              <div class="w-5 h-5 bg-warning rounded-full flex items-center justify-center text-white text-xs flex-shrink-0 mt-0.5">
                {{ ann.user_id }}
              </div>
              <div class="flex-1">
                <div class="text-xs text-warning-foreground">{{ ann.created_at }}</div>
                <div class="text-sm text-warning-foreground">{{ ann.content }}</div>
              </div>
              <button
                class="text-warning hover:text-warning-foreground text-sm"
                @click="emit('removeAnnotation', ann.id)"
              >✕</button>
            </div>
          </div>

          <!-- Annotation input -->
          <div v-if="showAnnotationInput === activeModule" class="border-t border-border p-3">
            <textarea
              v-model="annotationText"
              placeholder="输入修改意见..."
              class="w-full border border-border rounded-lg p-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary"
              rows="3"
            />
            <div class="flex justify-end gap-2 mt-2">
              <button
                class="px-3 py-1.5 text-sm text-text-muted hover:text-text-secondary"
                @click="showAnnotationInput = null"
              >取消</button>
              <button
                class="px-3 py-1.5 text-sm bg-primary text-white rounded-md hover:bg-primary-hover"
                @click="submitAnnotation"
              >添加批注</button>
            </div>
          </div>

          <!-- Add annotation button -->
          <div class="border-t border-border p-2 flex justify-end">
            <button
              class="px-3 py-1.5 text-xs text-text-muted border border-border rounded-md hover:bg-background"
              @click="startAnnotation(activeModule)"
            >
              {{ moduleAnnotations.length > 0 ? '追加批注' : '对此表批注' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Bottom action bar -->
      <div class="border-t border-border px-4 py-3 flex items-center justify-between bg-surface">
        <span class="text-xs text-text-muted">
          共 {{ moduleKeys.length }} 个模块，{{ pendingCount }} 条待处理批注
        </span>
        <div class="flex gap-2">
          <button
            data-testid="skip-review"
            class="px-5 py-2 text-sm border border-border rounded-lg text-text-secondary hover:bg-background"
            @click="emit('skip')"
          >跳过人工审核</button>
          <button
            class="px-5 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover disabled:opacity-50"
            :disabled="pendingCount === 0"
            @click="emit('submit')"
          >提交修改 ({{ pendingCount }}条批注)</button>
        </div>
      </div>
    </div>
  </div>
</template>

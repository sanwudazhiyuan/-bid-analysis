<script setup lang="ts">
import { ref, computed } from 'vue'
import { MessageSquarePlus, X, Send } from 'lucide-vue-next'
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

const BID_OUTLINE_MODULE_KEY = 'bid_format'

const MODULE_LABELS: Record<string, string> = {
  module_a: 'A 基本信息', module_b: 'B 资格要求', module_c: 'C 评标办法',
  module_d: 'D 废标条款', module_e: 'E 投标要求', module_f: 'F 合同条款',
  module_g: 'G 其他', bid_format: '投标文件大纲', checklist: '资料清单',
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
  <div class="flex h-full animate-fade-in">
    <!-- Left panel: original text -->
    <div class="w-1/3 min-w-[320px] border-r border-border bg-background flex flex-col">
      <div class="px-4 py-3 border-b border-border bg-surface text-sm font-medium text-text-secondary">
        招标原文
      </div>
      <div class="flex-1 overflow-y-auto p-4 text-sm text-text-secondary leading-relaxed custom-scrollbar">
        <p
          v-for="p in paragraphs"
          :key="p.index"
          :class="p.style?.includes('heading') ? 'font-semibold text-text-primary mt-4 mb-1.5 text-[15px]' : 'mb-1.5 text-text-muted'"
        >
          {{ p.text }}
        </p>
      </div>
    </div>

    <!-- Right panel: extracted data -->
    <div class="flex-1 flex flex-col">
      <!-- Module tabs -->
      <div class="flex border-b border-border bg-surface overflow-x-auto custom-scrollbar px-2">
        <button
          v-for="key in moduleKeys"
          :key="key"
          @click="activeModule = key"
          :class="[
            'px-4 py-3 text-sm whitespace-nowrap relative transition-all duration-200 font-medium',
            activeModule === key
              ? 'text-primary'
              : 'text-text-muted hover:text-text-secondary'
          ]"
        >
          {{ MODULE_LABELS[key] || key }}
          <span
            v-if="activeModule === key"
            class="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full"
          />
          <span
            v-if="hasAnnotations(key)"
            class="absolute top-2 right-0.5 w-2 h-2 bg-warning rounded-full ring-2 ring-surface"
          />
        </button>
      </div>

      <!-- Content area -->
      <div class="flex-1 overflow-y-auto p-5 bg-background custom-scrollbar">
        <div
          :class="[
            'bg-surface rounded-xl overflow-hidden',
            moduleAnnotations.length > 0
              ? 'border border-warning shadow-sm'
              : 'border border-border shadow-xs'
          ]"
        >
          <!-- Table header for annotated modules -->
          <div
            v-if="moduleAnnotations.length > 0"
            class="px-4 py-2.5 bg-warning-light flex items-center justify-between"
          >
            <span class="text-sm font-medium text-warning-foreground">
              {{ MODULE_LABELS[activeModule] || activeModule }}
            </span>
            <span class="text-[11px] bg-warning text-white px-2 py-0.5 rounded-md font-medium">
              {{ moduleAnnotations.length }}条批注
            </span>
          </div>

          <!-- Table content -->
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-background">
                <th class="px-4 py-2.5 text-left text-xs text-text-muted font-medium border-b border-border w-[30%] uppercase tracking-wider">字段</th>
                <th class="px-4 py-2.5 text-left text-xs text-text-muted font-medium border-b border-border uppercase tracking-wider">内容</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="currentModuleData?.sections">
                <template v-for="section in currentModuleData.sections" :key="section.id">
                  <tr v-for="(row, ri) in (section.rows || [])" :key="ri" class="border-b border-border/50 hover:bg-background/50 transition-colors">
                    <td class="px-4 py-2.5 text-text-secondary font-medium">{{ Array.isArray(row) ? row[0] : (row.label || row.key || '') }}</td>
                    <td class="px-4 py-2.5 text-text-secondary">{{ Array.isArray(row) ? row.slice(1).join(' | ') : (row.value || '') }}</td>
                  </tr>
                </template>
              </template>
              <template v-else>
                <tr v-for="(value, key) in currentModuleData" :key="key" class="border-b border-border/50 hover:bg-background/50 transition-colors">
                  <td class="px-4 py-2.5 text-text-secondary font-medium">{{ key }}</td>
                  <td class="px-4 py-2.5 text-text-secondary">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</td>
                </tr>
              </template>
            </tbody>
          </table>

          <!-- Annotations for this module -->
          <div v-if="moduleAnnotations.length > 0" class="border-t border-warning/30 bg-warning-light p-3.5">
            <div
              v-for="ann in moduleAnnotations"
              :key="ann.id"
              class="flex gap-2.5 items-start mb-2.5 last:mb-0"
            >
              <div class="w-6 h-6 bg-warning rounded-lg flex items-center justify-center text-white text-[11px] font-medium flex-shrink-0 mt-0.5">
                {{ ann.user_id }}
              </div>
              <div class="flex-1">
                <div class="text-[11px] text-warning-foreground/70">{{ ann.created_at }}</div>
                <div class="text-sm text-warning-foreground">{{ ann.content }}</div>
              </div>
              <button
                class="text-warning hover:text-warning-foreground transition-colors p-1 rounded-lg hover:bg-warning/20"
                @click="emit('removeAnnotation', ann.id)"
              >
                <X class="size-3.5" />
              </button>
            </div>
          </div>

          <!-- Annotation input -->
          <div v-if="showAnnotationInput === activeModule" class="border-t border-border p-4 animate-slide-down">
            <textarea
              v-model="annotationText"
              placeholder="输入修改意见..."
              class="w-full border border-border rounded-xl p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all duration-200"
              rows="3"
            />
            <div class="flex justify-end gap-2 mt-2.5">
              <button
                class="px-4 py-2 text-sm text-text-muted hover:text-text-secondary rounded-xl hover:bg-background transition-all duration-200"
                @click="showAnnotationInput = null"
              >取消</button>
              <button
                class="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-xl font-medium hover:bg-primary-hover transition-all duration-200 active:scale-[0.98] inline-flex items-center gap-1.5"
                @click="submitAnnotation"
              >
                <Send class="size-3.5" />
                添加批注
              </button>
            </div>
          </div>

          <!-- Add annotation button -->
          <div v-if="activeModule !== BID_OUTLINE_MODULE_KEY" class="border-t border-border p-2.5 flex justify-end">
            <button
              class="px-3.5 py-1.5 text-xs text-text-muted border border-border rounded-xl hover:bg-background hover:border-text-muted transition-all duration-200 inline-flex items-center gap-1.5"
              @click="startAnnotation(activeModule)"
            >
              <MessageSquarePlus class="size-3" />
              {{ moduleAnnotations.length > 0 ? '追加批注' : '对此表批注' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Bottom action bar -->
      <div class="border-t border-border px-5 py-3 flex items-center justify-between bg-surface">
        <span class="text-xs text-text-muted">
          共 {{ moduleKeys.length }} 个模块，{{ pendingCount }} 条待处理批注
        </span>
        <div class="flex gap-2.5">
          <button
            data-testid="skip-review"
            class="px-5 py-2 text-sm border border-border rounded-xl text-text-secondary hover:bg-background hover:border-text-muted transition-all duration-200 active:scale-[0.98]"
            @click="emit('skip')"
          >跳过人工审核</button>
          <button
            class="px-5 py-2 text-sm bg-primary text-primary-foreground rounded-xl font-medium hover:bg-primary-hover hover:shadow-md transition-all duration-200 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="pendingCount === 0"
            @click="emit('submit')"
          >提交修改 ({{ pendingCount }}条批注)</button>
        </div>
      </div>
    </div>
  </div>
</template>

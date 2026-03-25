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
    <div class="w-1/3 border-r border-gray-200 bg-gray-50 flex flex-col">
      <div class="px-3 py-2.5 border-b border-gray-200 bg-white text-sm font-medium text-gray-500">
        招标原文
      </div>
      <div class="flex-1 overflow-y-auto p-3 text-sm text-gray-600 leading-relaxed">
        <p
          v-for="p in paragraphs"
          :key="p.index"
          :class="p.style?.includes('heading') ? 'font-semibold text-gray-800 mt-3 mb-1' : 'mb-1 text-gray-500'"
        >
          {{ p.text }}
        </p>
      </div>
    </div>

    <!-- Right panel: extracted data (2/3) -->
    <div class="flex-1 flex flex-col">
      <!-- Module tabs -->
      <div class="flex border-b border-gray-200 bg-white overflow-x-auto">
        <button
          v-for="key in moduleKeys"
          :key="key"
          @click="activeModule = key"
          :class="[
            'px-4 py-2.5 text-sm whitespace-nowrap relative transition-colors',
            activeModule === key
              ? 'border-b-2 border-purple-600 text-purple-700 font-medium'
              : 'text-gray-400 hover:text-gray-600'
          ]"
        >
          {{ MODULE_LABELS[key] || key }}
          <span
            v-if="hasAnnotations(key)"
            class="absolute top-1.5 right-1 w-1.5 h-1.5 bg-amber-500 rounded-full"
          />
        </button>
      </div>

      <!-- Content area -->
      <div class="flex-1 overflow-y-auto p-4 bg-gray-50">
        <div
          :class="[
            'bg-white rounded-lg overflow-hidden mb-4',
            moduleAnnotations.length > 0
              ? 'border border-amber-400 shadow-sm'
              : 'border border-gray-200'
          ]"
        >
          <!-- Table header for annotated modules -->
          <div
            v-if="moduleAnnotations.length > 0"
            class="px-3 py-2 bg-amber-50 flex items-center justify-between"
          >
            <span class="text-sm font-medium text-amber-800">
              {{ MODULE_LABELS[activeModule] || activeModule }}
            </span>
            <span class="text-xs bg-amber-500 text-white px-2 py-0.5 rounded-full">
              {{ moduleAnnotations.length }}条批注
            </span>
          </div>

          <!-- Table content -->
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50">
                <th class="px-3 py-2 text-left text-gray-500 font-medium border-b border-gray-200 w-[30%]">字段</th>
                <th class="px-3 py-2 text-left text-gray-500 font-medium border-b border-gray-200">内容</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="currentModuleData?.sections">
                <template v-for="section in currentModuleData.sections" :key="section.id">
                  <tr v-for="(row, ri) in (section.rows || [])" :key="ri" class="border-b border-gray-100">
                    <td class="px-3 py-2 text-gray-700 font-medium">{{ row.label || row.key || '' }}</td>
                    <td class="px-3 py-2 text-gray-600">{{ row.value || '' }}</td>
                  </tr>
                </template>
              </template>
              <template v-else>
                <tr v-for="(value, key) in currentModuleData" :key="key" class="border-b border-gray-100">
                  <td class="px-3 py-2 text-gray-700 font-medium">{{ key }}</td>
                  <td class="px-3 py-2 text-gray-600">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</td>
                </tr>
              </template>
            </tbody>
          </table>

          <!-- Annotations for this module -->
          <div v-if="moduleAnnotations.length > 0" class="border-t border-amber-200 bg-amber-50 p-3">
            <div
              v-for="ann in moduleAnnotations"
              :key="ann.id"
              class="flex gap-2 items-start mb-2 last:mb-0"
            >
              <div class="w-5 h-5 bg-amber-500 rounded-full flex items-center justify-center text-white text-xs flex-shrink-0 mt-0.5">
                {{ ann.user_id }}
              </div>
              <div class="flex-1">
                <div class="text-xs text-amber-700">{{ ann.created_at }}</div>
                <div class="text-sm text-amber-900">{{ ann.content }}</div>
              </div>
              <button
                class="text-amber-600 hover:text-amber-800 text-sm"
                @click="emit('removeAnnotation', ann.id)"
              >✕</button>
            </div>
          </div>

          <!-- Annotation input -->
          <div v-if="showAnnotationInput === activeModule" class="border-t border-gray-200 p-3">
            <textarea
              v-model="annotationText"
              placeholder="输入修改意见..."
              class="w-full border border-gray-300 rounded-lg p-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-purple-500"
              rows="3"
            />
            <div class="flex justify-end gap-2 mt-2">
              <button
                class="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700"
                @click="showAnnotationInput = null"
              >取消</button>
              <button
                class="px-3 py-1.5 text-sm bg-purple-600 text-white rounded-md hover:bg-purple-700"
                @click="submitAnnotation"
              >添加批注</button>
            </div>
          </div>

          <!-- Add annotation button -->
          <div class="border-t border-gray-200 p-2 flex justify-end">
            <button
              class="px-3 py-1.5 text-xs text-gray-500 border border-gray-300 rounded-md hover:bg-gray-50"
              @click="startAnnotation(activeModule)"
            >
              {{ moduleAnnotations.length > 0 ? '追加批注' : '对此表批注' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Bottom action bar -->
      <div class="border-t border-gray-200 px-4 py-3 flex items-center justify-between bg-white">
        <span class="text-xs text-gray-400">
          共 {{ moduleKeys.length }} 个模块，{{ pendingCount }} 条待处理批注
        </span>
        <div class="flex gap-2">
          <button
            data-testid="skip-review"
            class="px-5 py-2 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
            @click="emit('skip')"
          >跳过人工审核</button>
          <button
            class="px-5 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-purple-300"
            :disabled="pendingCount === 0"
            @click="emit('submit')"
          >提交修改 ({{ pendingCount }}条批注)</button>
        </div>
      </div>
    </div>
  </div>
</template>

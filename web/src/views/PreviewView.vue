<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePreviewStore } from '../stores/previewStore'
import ModuleNav from '../components/ModuleNav.vue'
import SectionTable from '../components/SectionTable.vue'
import AnnotationPanel from '../components/AnnotationPanel.vue'
import { useAnnotation } from '../composables/useAnnotation'
import { annotationsApi } from '../api/annotations'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id as string
const store = usePreviewStore()

const { annotations, load: loadAnnotations, add: addAnnotation, remove: removeAnnotation, getForRow, getPendingBySection } = useAnnotation(taskId)

const selectedRow = ref<{ sectionId: string; rowIndex: number } | null>(null)
const submitting = ref(false)
const regenerating = ref(false)

onMounted(async () => {
  await store.loadPreview(taskId)
  await loadAnnotations()
})

const modules = computed(() => store.data?.extracted_data?.modules || {})
const currentModuleData = computed(() => {
  const mod = modules.value[store.currentModule]
  return mod || null
})
const checkboxData = computed(() => store.data?.checkbox_data || {})

function getCheckboxForSection(sectionId: string) {
  return checkboxData.value[store.currentModule]?.[sectionId] || {}
}

function getAnnotationCountsForSection(sectionId: string): Record<number, number> {
  const counts: Record<number, number> = {}
  for (const ann of annotations.value) {
    if (ann.module_key === store.currentModule && ann.section_id === sectionId && ann.row_index !== null) {
      counts[ann.row_index] = (counts[ann.row_index] ?? 0) + 1
    }
  }
  return counts
}

function onSelectRow(sectionId: string, rowIndex: number) {
  if (selectedRow.value?.sectionId === sectionId && selectedRow.value?.rowIndex === rowIndex) {
    selectedRow.value = null
  } else {
    selectedRow.value = { sectionId, rowIndex }
  }
}

function getSelectedRowContent(): string {
  if (!selectedRow.value || !currentModuleData.value) return ''
  const sec = currentModuleData.value.sections?.find((s: any) => s.id === selectedRow.value!.sectionId)
  if (!sec?.rows) return ''
  const row = sec.rows[selectedRow.value.rowIndex]
  return Array.isArray(row) ? row.join(' ') : String(row ?? '')
}

async function submitAnnotations() {
  submitting.value = true
  try {
    const pending = getPendingBySection()
    for (const group of pending) {
      await annotationsApi.reextract(taskId, {
        module_key: group.module_key,
        section_id: group.section_id,
        annotation_ids: group.ids,
      })
    }
    await loadAnnotations()
  } finally {
    submitting.value = false
  }
}

async function regenerate() {
  regenerating.value = true
  try {
    await loadAnnotations()
  } finally {
    regenerating.value = false
  }
}
</script>

<template>
  <div class="flex h-screen">
    <!-- Left nav -->
    <ModuleNav :modules="modules" />

    <!-- Main content -->
    <div class="flex-1 overflow-y-auto p-6">
      <div class="flex items-center justify-between mb-6">
        <button @click="router.back()" class="text-sm text-blue-600 hover:underline">&larr; 返回</button>
        <div class="flex gap-2">
          <button
            @click="submitAnnotations"
            :disabled="submitting"
            class="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {{ submitting ? '提交中...' : '提交修改' }}
          </button>
          <button
            @click="regenerate"
            :disabled="regenerating"
            class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {{ regenerating ? '处理中...' : '重新生成' }}
          </button>
        </div>
      </div>

      <div v-if="store.loading" class="text-center text-gray-400 py-20">加载中...</div>

      <div v-else-if="currentModuleData">
        <h2 class="text-lg font-bold mb-4">{{ currentModuleData.title }}</h2>
        <SectionTable
          v-for="sec in currentModuleData.sections"
          :key="sec.id"
          :section="sec"
          :module-key="store.currentModule"
          :task-id="taskId"
          :checkbox-data="getCheckboxForSection(sec.id)"
          :annotation-counts="getAnnotationCountsForSection(sec.id)"
          :selected-row="selectedRow?.sectionId === sec.id ? selectedRow.rowIndex : null"
          @select-row="onSelectRow(sec.id, $event)"
        />

        <!-- Annotation panel for selected row -->
        <div v-if="selectedRow" class="mt-6">
          <AnnotationPanel
            :annotations="getForRow(store.currentModule, selectedRow.sectionId, selectedRow.rowIndex)"
            :module-key="store.currentModule"
            :section-id="selectedRow.sectionId"
            :row-index="selectedRow.rowIndex"
            :row-content="getSelectedRowContent()"
            @add="addAnnotation(store.currentModule, selectedRow!.sectionId, selectedRow!.rowIndex, $event)"
            @remove="removeAnnotation($event)"
          />
        </div>
      </div>

      <div v-else class="text-center text-gray-400 py-20">请从左侧选择模块</div>
    </div>
  </div>
</template>

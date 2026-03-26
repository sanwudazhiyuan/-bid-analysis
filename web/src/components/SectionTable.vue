<script setup lang="ts">
import { usePreviewStore } from '../stores/previewStore'
import type { Section } from '../types/preview'
import AnnotationBadge from './AnnotationBadge.vue'

defineOptions({ name: 'SectionTable' })

const props = defineProps<{
  section: Section
  moduleKey: string
  taskId: string
  checkboxData: Record<string, boolean>
  annotationCounts?: Record<number, number>
  selectedRow?: number | null
}>()

const emit = defineEmits<{
  'select-row': [rowIndex: number]
}>()

const store = usePreviewStore()

function isChecked(rowIndex: number): boolean {
  return props.checkboxData?.[String(rowIndex)] || false
}

function toggle(rowIndex: number) {
  const current = isChecked(rowIndex)
  store.toggleCheckbox(props.taskId, props.moduleKey, props.section.id, rowIndex, !current)
}

function getAnnotationCount(rowIndex: number): number {
  return props.annotationCounts?.[rowIndex] ?? 0
}

function handleRowClick(rowIndex: number) {
  emit('select-row', rowIndex)
}
</script>

<template>
  <div class="mb-6">
    <h3 class="text-sm font-semibold text-text-secondary mb-2">{{ section.id }} {{ section.title }}</h3>

    <!-- Table type sections -->
    <div class="overflow-x-auto">
      <table v-if="section.columns && section.rows" class="w-full text-sm border-collapse border">
        <thead>
          <tr class="bg-background">
            <th v-for="col in section.columns" :key="col" class="border px-3 py-2 text-left font-medium text-text-secondary">
              {{ col }}
            </th>
            <th class="border px-3 py-2 w-12 text-center font-medium text-text-secondary">确认</th>
            <th class="border px-3 py-2 w-12 text-center font-medium text-text-secondary">标注</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, rowIdx) in section.rows"
            :key="rowIdx"
            class="hover:bg-info-light cursor-pointer"
            :class="{ 'bg-highlight': selectedRow === rowIdx }"
            @click="handleRowClick(rowIdx)"
          >
            <td v-for="(cell, cellIdx) in row" :key="cellIdx" class="border px-3 py-2 text-text-secondary">
              {{ cell }}
            </td>
            <td class="border px-3 py-2 text-center">
              <input type="checkbox" :checked="isChecked(rowIdx)" @click.stop="toggle(rowIdx)"
                class="w-4 h-4 text-info rounded" />
            </td>
            <td class="border px-3 py-2 text-center">
              <AnnotationBadge :count="getAnnotationCount(rowIdx)" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Text type sections -->
    <div v-else-if="section.content" class="bg-background p-3 rounded text-sm text-text-secondary">
      {{ section.content }}
    </div>

    <!-- Note field -->
    <p v-if="section.note" class="text-xs text-text-muted mt-1">{{ section.note }}</p>

    <!-- Nested sections (parent type) -->
    <div v-if="section.sections" class="ml-4 mt-3">
      <SectionTable
        v-for="sub in section.sections" :key="sub.id"
        :section="sub" :module-key="moduleKey" :task-id="taskId"
        :checkbox-data="checkboxData"
        :annotation-counts="annotationCounts"
        :selected-row="selectedRow"
        @select-row="emit('select-row', $event)"
      />
    </div>
  </div>
</template>

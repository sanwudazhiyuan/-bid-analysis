<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePreviewStore } from '../stores/previewStore'
import ModuleNav from '../components/ModuleNav.vue'
import SectionTable from '../components/SectionTable.vue'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id as string
const store = usePreviewStore()

onMounted(() => store.loadPreview(taskId))

const modules = computed(() => store.data?.extracted_data?.modules || {})
const currentModuleData = computed(() => {
  const mod = modules.value[store.currentModule]
  return mod || null
})
const checkboxData = computed(() => store.data?.checkbox_data || {})

function getCheckboxForSection(sectionId: string) {
  return checkboxData.value[store.currentModule]?.[sectionId] || {}
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
          <button class="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm">提交修改</button>
          <button class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm">重新生成</button>
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
        />
      </div>

      <div v-else class="text-center text-gray-400 py-20">请从左侧选择模块</div>
    </div>
  </div>
</template>

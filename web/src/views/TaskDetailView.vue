<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import TaskProgress from '../components/TaskProgress.vue'
import DownloadCard from '../components/DownloadCard.vue'
import { tasksApi } from '../api/tasks'
import type { Task } from '../types/task'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id as string
const task = ref<Task | null>(null)

onMounted(async () => {
  try {
    const res = await tasksApi.get(taskId)
    task.value = res.data
  } catch {
    router.push('/')
  }
})

function onCompleted() {
  tasksApi.get(taskId).then(res => { task.value = res.data })
}

const fileTypes = [
  { type: 'report', label: '分析报告.docx' },
  { type: 'format', label: '投标文件格式.docx' },
  { type: 'checklist', label: '资料清单.docx' },
]
</script>

<template>
  <DefaultLayout>
    <div class="mb-4">
      <button @click="router.push('/')" class="text-sm text-blue-600 hover:underline">&larr; 返回</button>
    </div>
    <h1 class="text-xl font-bold mb-6">{{ task?.filename }}</h1>

    <div v-if="task && !['completed', 'failed'].includes(task.status)" class="bg-white rounded-lg shadow p-6">
      <h2 class="text-lg font-semibold mb-4">分析进度</h2>
      <TaskProgress :task-id="taskId" @completed="onCompleted" />
    </div>

    <div v-if="task?.status === 'completed'" class="space-y-4">
      <div class="flex gap-3">
        <router-link :to="`/tasks/${taskId}/preview`"
          class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">预览分析结果</router-link>
      </div>
      <div class="space-y-2">
        <h2 class="text-lg font-semibold">生成文件</h2>
        <DownloadCard v-for="ft in fileTypes" :key="ft.type" :task-id="taskId" :file-type="ft.type" :label="ft.label" />
      </div>
    </div>

    <div v-if="task?.status === 'failed'" class="bg-red-50 text-red-700 p-4 rounded-md">
      {{ task.error_message || '分析失败' }}
    </div>
  </DefaultLayout>
</template>

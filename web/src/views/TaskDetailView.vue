<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TaskProgress from '../components/TaskProgress.vue'
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
</script>

<template>
  <div class="max-w-4xl mx-auto p-6">
    <div class="mb-4">
      <button @click="router.push('/')" class="text-sm text-blue-600 hover:underline">&larr; 返回仪表板</button>
    </div>
    <h1 class="text-xl font-bold mb-6">{{ task?.filename || '加载中...' }}</h1>

    <div v-if="task && !['completed', 'failed'].includes(task.status)" class="bg-white rounded-lg shadow p-6">
      <h2 class="text-lg font-semibold mb-4">分析进度</h2>
      <TaskProgress :task-id="taskId" @completed="onCompleted" />
    </div>

    <div v-if="task?.status === 'completed'" class="bg-green-50 text-green-700 p-4 rounded-md">
      分析已完成 — 下载功能将在 Phase 3 实现
    </div>

    <div v-if="task?.status === 'failed'" class="bg-red-50 text-red-700 p-4 rounded-md">
      {{ task.error_message || '分析失败' }}
    </div>
  </div>
</template>

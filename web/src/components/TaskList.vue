<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { tasksApi } from '../api/tasks'
import type { Task } from '../types/task'

const tasks = ref<Task[]>([])
const total = ref(0)
const page = ref(1)
const statusFilter = ref('')
const loading = ref(false)

async function loadTasks() {
  loading.value = true
  try {
    const res = await tasksApi.list({ page: page.value, status: statusFilter.value || undefined })
    tasks.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

onMounted(loadTasks)
watch([page, statusFilter], loadTasks)

const statusMap: Record<string, { label: string; cls: string }> = {
  pending: { label: '等待中', cls: 'text-gray-500' },
  parsing: { label: '解析中', cls: 'text-blue-500' },
  indexing: { label: '索引中', cls: 'text-blue-500' },
  extracting: { label: '提取中', cls: 'text-blue-500' },
  generating: { label: '生成中', cls: 'text-blue-500' },
  completed: { label: '已完成', cls: 'text-green-600' },
  failed: { label: '失败', cls: 'text-red-500' },
}

defineExpose({ loadTasks })
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold">我的分析任务</h2>
      <select v-model="statusFilter" class="border rounded px-2 py-1 text-sm">
        <option value="">全部</option>
        <option value="completed">已完成</option>
        <option value="failed">失败</option>
        <option value="extracting">进行中</option>
      </select>
    </div>
    <div class="bg-white rounded-lg shadow overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-left">
          <tr>
            <th class="px-4 py-3">文件名</th>
            <th class="px-4 py-3">状态</th>
            <th class="px-4 py-3">进度</th>
            <th class="px-4 py-3">时间</th>
            <th class="px-4 py-3">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id" class="border-t hover:bg-gray-50">
            <td class="px-4 py-3 truncate max-w-xs">{{ task.filename }}</td>
            <td class="px-4 py-3">
              <span :class="statusMap[task.status]?.cls || ''">{{ statusMap[task.status]?.label || task.status }}</span>
            </td>
            <td class="px-4 py-3">{{ task.progress }}%</td>
            <td class="px-4 py-3 text-gray-500">{{ new Date(task.created_at).toLocaleDateString() }}</td>
            <td class="px-4 py-3">
              <router-link :to="`/tasks/${task.id}`" class="text-blue-600 hover:underline">查看</router-link>
            </td>
          </tr>
          <tr v-if="tasks.length === 0">
            <td colspan="5" class="px-4 py-8 text-center text-gray-400">暂无任务</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="total > 20" class="flex justify-center gap-2 mt-4">
      <button @click="page--" :disabled="page <= 1" class="px-3 py-1 border rounded disabled:opacity-50">上一页</button>
      <span class="px-3 py-1 text-sm text-gray-500">第 {{ page }} 页</span>
      <button @click="page++" :disabled="page * 20 >= total" class="px-3 py-1 border rounded disabled:opacity-50">下一页</button>
    </div>
  </div>
</template>

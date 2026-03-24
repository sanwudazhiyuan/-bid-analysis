<script setup lang="ts">
import { ref } from 'vue'
import type { Annotation } from '../types/annotation'

const props = defineProps<{
  annotations: Annotation[]
  moduleKey: string
  sectionId: string
  rowIndex: number
  rowContent: string
}>()

const emit = defineEmits<{
  add: [content: string]
  remove: [annId: number]
}>()

const newContent = ref('')

function submit() {
  if (!newContent.value.trim()) return
  emit('add', newContent.value.trim())
  newContent.value = ''
}
</script>

<template>
  <div class="bg-gray-50 border rounded-lg p-4">
    <div class="text-sm font-medium text-gray-700 mb-2">
      第{{ rowIndex + 1 }}行「{{ rowContent }}」
    </div>
    <div class="space-y-2 mb-3">
      <div v-for="ann in annotations" :key="ann.id"
        class="flex items-start justify-between bg-white p-2 rounded border text-sm">
        <div>
          <span class="text-gray-500 text-xs">{{ ann.annotation_type }}</span>
          <p class="text-gray-700">{{ ann.content }}</p>
          <span v-if="ann.status === 'resolved'" class="text-green-500 text-xs">已处理</span>
          <span v-else-if="ann.status === 'failed'" class="text-red-500 text-xs">处理失败</span>
        </div>
        <button v-if="ann.status === 'pending'" @click="emit('remove', ann.id)" class="text-red-400 hover:text-red-600 text-xs">删除</button>
      </div>
    </div>
    <div class="flex gap-2">
      <input v-model="newContent" placeholder="添加标注..." @keyup.enter="submit"
        class="flex-1 px-3 py-1.5 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      <button @click="submit" class="px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">添加</button>
    </div>
  </div>
</template>
